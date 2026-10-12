"""纯逻辑单元：无 db / 网络 / TUI。

（测试分层重组迁移；断言未改动。）
"""

import numpy as np
import pandas as pd
import pytest

from myastro import lc

"""lc 时序工具测试：全部用合成信号（确定性，无网络/文件依赖）。

重点覆盖三类：
1. 纯变换的正确性（归一化/筛选/折叠/分箱）
2. 周期搜索的两种方法（LS 粗搜 + PDM 精化）
3. **教训回归**：TLS 未归一化静默 nan、depth 语义反转
"""


def _sine(period=3.75, n=2000, span=60.0, amp=0.3, noise=0.005, seed=42):
    rng = np.random.default_rng(seed)
    t = np.linspace(0, span, n)
    f = 1.0 + amp * np.sin(2 * np.pi * t / period) + rng.normal(0, noise, n)
    return t, f


def _transit(
    period=1.09,
    depth=0.01,
    dur=0.1,
    t0=0.5,
    span=27.0,
    cadence_min=10.0,
    offset=1.0,
    seed=7,
):
    """盒模型凌星：先在**相对通量**域建模，再整体乘 offset。

    教训：凌星深度是相对量——若在 6000 计数上直接减 0.01，
    相对深度只剩 1.7e-6，等于没有凌星（夹具曾因此自欺）。
    """
    rng = np.random.default_rng(seed)
    t = np.arange(0, span, cadence_min / 1440.0)
    model = np.ones_like(t)
    in_transit = ((t - t0) % period) < dur
    model[in_transit] -= depth  # 相对域
    model += rng.normal(0, 0.0005, t.size)
    return t, model * offset


class TestTransforms:
    @pytest.mark.cap("process.lc")
    def test_normalize_median_one(self):
        _, f = _sine()
        n = lc.normalize(f * 6000)
        assert abs(np.median(n) - 1.0) < 1e-9

    @pytest.mark.cap("process.lc")
    def test_normalize_rejects_zero_median(self):
        with pytest.raises(ValueError, match="中位数"):
            lc.normalize(np.array([1.0, -1.0, 0.0]))

    @pytest.mark.cap("process.lc")
    def test_quality_cut(self):
        df = pd.DataFrame({"time": [1, 2, 3], "quality": [0, 1, 0]})
        assert len(lc.quality_cut(df)) == 2
        assert len(lc.quality_cut(df.drop(columns=["quality"]))) == 3

    @pytest.mark.cap("process.lc")
    def test_clip_range(self):
        # 小幅信号（如凌星搜索前的 0.9–1.1 窗口）：峰谷在窗内
        t, f = _sine(amp=0.03, noise=0.002)
        f = f.copy()
        f[0] = 5.0
        t2, f2 = lc.clip_range(f, 0.9, 1.1, t=t)
        assert len(f2) == len(f) - 1 and len(t2) == len(f2)

    @pytest.mark.cap("process.lc")
    def test_sigma_clip_removes_outliers(self):
        # 基线近平坦（amp 远小于离群量级）——sigma_clip 的适用前提
        t, f = _sine(amp=0.01, noise=0.002)
        f = f.copy()
        f[:5] += 0.5
        _, f2 = lc.sigma_clip(t, f, sigma=5)
        assert len(f2) == len(f) - 5

    @pytest.mark.cap("process.lc")
    def test_fold_range_and_sorting(self):
        t, f = _sine()
        ph, ff = lc.fold(t, f, 3.75)
        assert ph.min() >= -0.5 and ph.max() < 0.5
        assert np.all(np.diff(ph) >= 0)
        assert len(ff) == len(f)

    @pytest.mark.cap("process.lc")
    def test_fold_unit_convention(self):
        """centered=False → [0,1)：周期变星用例（nb02）依赖此约定。"""
        t, f = _sine()
        ph, _ = lc.fold(t, f, 3.75, centered=False)
        assert ph.min() >= 0.0 and ph.max() < 1.0
        # 两种约定在模 1 意义下是同一组相位（排序后逐点相等）
        phc, _ = lc.fold(t, f, 3.75)
        assert np.allclose(np.sort(ph % 1.0), np.sort(phc % 1.0))

    @pytest.mark.cap("process.lc")
    def test_bin_phase_matches_convention(self):
        t, f = _sine()
        ph_u, ff_u = lc.fold(t, f, 3.75, centered=False)
        cu, _ = lc.bin_phase(ph_u, ff_u, nbins=10)
        assert cu.min() >= 0.0 and cu.max() < 1.0  # [0,1) 约定
        ph_c, ff_c = lc.fold(t, f, 3.75)
        cc, _ = lc.bin_phase(ph_c, ff_c, nbins=10)
        assert cc.min() < 0.0  # [-0.5,0.5) 约定

    @pytest.mark.cap("process.lc")
    def test_fold_collapses_variance(self):
        """正确周期折叠后，相位分箱的散射应远小于未折叠数据。"""
        t, f = _sine(noise=0.01)
        ph, ff = lc.fold(t, f, 3.75)
        _, vals = lc.bin_phase(ph, ff, nbins=20)
        assert np.nanstd(vals) < np.std(f)

    @pytest.mark.cap("process.lc")
    def test_bin_phase_empty_bins_nan(self):
        ph = np.linspace(-0.5, 0.5, 100)
        _, vals = lc.bin_phase(ph, np.ones(100), nbins=200)
        assert np.isnan(vals).any()

    @pytest.mark.cap("process.lc")
    def test_mag_amplitude(self):
        f = np.array([0.9, 1.0, 1.1])
        assert lc.mag_amplitude(f) == pytest.approx(-2.5 * np.log10(0.9 / 1.1))
        with pytest.raises(ValueError):
            lc.mag_amplitude(np.array([-0.1, 1.0]))


class TestPeriodSearch:
    @pytest.mark.cap("process.lc")
    def test_sine_recovery(self):
        t, f = _sine()
        r = lc.period_search(t, f, min_period=1.0, max_period=10.0)
        assert r.method == "pdm"
        assert abs(r.best_period - 3.75) / 3.75 < 0.005

    @pytest.mark.cap("process.lc")
    def test_ls_only_mode(self):
        t, f = _sine()
        r = lc.period_search(t, f, 1.0, 10.0, refine=False)
        assert r.method == "ls" and r.best_period == r.coarse_period
        assert r.power.size == r.periods.size
        assert r.refine_periods is None and r.refine_theta is None

    @pytest.mark.cap("process.lc")
    def test_refine_curve_exposed_for_plotting(self):
        """PDM θ 曲线随结果返回（客户端无需私有符号、无需重算）。"""
        t, f = _sine()
        r = lc.period_search(t, f, 1.0, 10.0)
        assert r.refine_periods is not None and r.refine_theta is not None
        assert r.refine_periods.size == r.refine_theta.size
        i = int(np.argmin(r.refine_theta))
        assert abs(r.refine_periods[i] - r.best_period) < 1e-12

    @pytest.mark.cap("process.lc")
    def test_pdm_not_worse_than_ls_on_asymmetric(self):
        """非正弦光变（强谐波）：PDM 精化不应比 LS 粗搜差。"""
        rng = np.random.default_rng(3)
        t = np.linspace(0, 80, 3000)
        phase = (t / 3.7) % 1.0
        # 非对称波形：尖锐下降 + 缓慢上升（Cepheid 风格）
        f = 1.0 - 0.35 * np.exp(-phase / 0.08) + rng.normal(0, 0.004, t.size)
        r = lc.period_search(t, f, 1.0, 10.0)
        err_ls = abs(r.coarse_period - 3.7) / 3.7
        err_pdm = abs(r.best_period - 3.7) / 3.7
        assert err_pdm <= err_ls + 1e-9


class TestTransitSearch:
    """教训回归：这两条曾是真故障。"""

    @pytest.mark.cap("process.lc")
    def test_unnormalized_flux_still_works(self):
        """TLS 未归一化会静默返回 nan——transit_search 内部必须归一化。"""
        t, f = _transit(offset=6000.0)  # 未归一化的原始计数
        assert np.median(f) > 1000  # 前提：确实是未归一化输入
        r = lc.transit_search(t, f, period_min=0.5, period_max=2.0)
        assert np.isfinite(r.period) and np.isfinite(r.depth)
        assert abs(r.period - 1.09) / 1.09 < 0.02

    @pytest.mark.cap("process.lc")
    def test_depth_semantics_is_true_depth(self):
        """TLS 的 depth 是凌内/凌外比；返回值必须是真深度（~0.01 而非 ~0.99）。"""
        t, f = _transit(depth=0.01)
        r = lc.transit_search(t, f, period_min=0.5, period_max=2.0)
        assert 0.003 < r.depth < 0.03  # 真深度量级
        assert r.depth < 0.5  # 明确不是 1-depth 的旧语义

    @pytest.mark.cap("process.lc")
    def test_raw_available_for_advanced_use(self):
        t, f = _transit()
        r = lc.transit_search(t, f, period_min=0.5, period_max=2.0)
        assert r.raw is not None and hasattr(r.raw, "period")


@pytest.mark.cap("process.lc")
class TestStellarParams:
    """`r_star`/`m_star` 是可选恒星参数：给了就转发给 TLS，不给就保持原行为。

    为什么需要它们：TLS 用 R_star/M_star 构造周期网格；不传时按 1.0/1.0 估算，
    网格过稀就警告 "period_grid defaults to R_star=1 and M_star=1 ..."。
    那条警告指向真问题（网格可能覆盖不到真实周期），因此**不抑制**，而是暴露参数。
    """

    def test_params_are_forwarded_when_given(self, monkeypatch):
        """给了就转发（用假 TLS 捕获 kwargs，确定性、不依赖网络）。"""
        import sys
        import types

        captured: dict = {}

        class FakeResult:
            period, depth, duration, T0, snr = 1.0, 0.99, 0.1, 0.0, 5.0

        class FakeTLS:
            def __init__(self, t, flux):
                pass

            def power(self, **kwargs):
                captured.update(kwargs)
                return FakeResult()

        fake = types.ModuleType("transitleastsquares")
        fake.transitleastsquares = FakeTLS
        monkeypatch.setitem(sys.modules, "transitleastsquares", fake)

        from myastro import lc
        t = np.linspace(0, 10, 200)
        f = np.ones_like(t)

        lc.transit_search(t, f, r_star=1.2, m_star=0.9)
        assert captured["R_star"] == 1.2 and captured["M_star"] == 0.9

        captured.clear()
        lc.transit_search(t, f)                       # 不给 → 不传这两个键
        assert "R_star" not in captured and "M_star" not in captured

    def test_real_run_with_stellar_params_is_warning_free(self):
        """真实跑一次：给了恒星参数就不该再出现 period_grid 警告。

        这是这条改动**唯一有意义的证据**——假 TLS 只能证明"转发到位"，
        不能证明"警告消失"。
        """
        import warnings

        rng = np.random.default_rng(42)
        t = np.linspace(0, 20, 2000)
        period, depth = 1.5, 0.01
        phase = (t % period) / period
        flux = np.where((phase > 0.45) & (phase < 0.55), 1 - depth, 1.0)
        flux = flux + rng.normal(0, 3e-4, t.size)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = lc.transit_search(t, flux, period_min=0.5, period_max=3.0,
                                       r_star=1.0, m_star=1.0)
        noisy = [str(w.message) for w in caught if "period_grid" in str(w.message)]
        assert not noisy, f"给了恒星参数仍出现网格警告：{noisy}"
        assert result.period > 0 and 0 < result.depth < 1
