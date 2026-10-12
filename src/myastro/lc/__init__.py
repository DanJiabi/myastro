"""时序处理工具：从三份 notebook 中反复出现的手写代码提取的纯变换。

边界（capabilities §4）：**"换个目标还会一模一样地做"的进这里，
"取决于这次想干什么"的留在 notebook**（选目标、挑参数、画图、叙述）。

这些函数同时是**教训的载体**——notebook 里以文字记下的坑，
在这里变成代码约束：
- `transit_search` 内部强制归一化（早期未归一化导致 TLS 静默返回 nan）
- `transit_search` 返回的深度是**真深度**（TLS 的 depth 是凌内/凌外通量比）
- `period_search` 默认 LS 粗搜 + PDM 精化（LS 对非正弦光变系统性偏峰）

输入输出约定：数组进数组出（numpy），不打乱调用方的 DataFrame 结构；
`quality_cut` 例外——它按我们的 parquet 契约直接吃 DataFrame。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = [
    "PeriodResult",
    "TransitResult",
    "bin_phase",
    "clip_range",
    "fold",
    "mag_amplitude",
    "normalize",
    "period_search",
    "quality_cut",
    "sigma_clip",
    "transit_search",
]


# ────────────────────────── 基础变换 ──────────────────────────

def normalize(flux: np.ndarray) -> np.ndarray:
    """通量归一化（除以中位数）——进任何周期/凌星搜索前的必要步骤。

    中位数为 0 时抛错而非静默产生 inf。
    """
    flux = np.asarray(flux, dtype=float)
    med = np.nanmedian(flux)
    if not np.isfinite(med) or med == 0:
        raise ValueError(f"通量中位数无效（{med}），无法归一化")
    return flux / med


def quality_cut(df, quality_col: str = "quality", keep: int = 0):
    """按任务管线的质量标记筛选（TESS/Kepler：quality==0 为干净点）。

    列不存在时原样返回（非所有产物都有 quality 列）。
    """
    if quality_col not in df.columns:
        return df
    return df[df[quality_col] == keep]


def clip_range(flux: np.ndarray, low: float, high: float,
               t: np.ndarray | None = None):
    """按绝对范围剔除（如归一化后保留 0.9–1.1：凌星深度仅 ~1%）。

    返回 (mask 后的 t, flux)；t=None 时返回 (None, flux)。
    """
    flux = np.asarray(flux, dtype=float)
    m = (flux > low) & (flux < high)
    if t is None:
        return None, flux[m]
    return np.asarray(t)[m], flux[m]


def sigma_clip(t: np.ndarray, flux: np.ndarray, sigma: float = 5.0,
               iters: int = 3):
    """迭代 sigma 剔除（中位数/MAD 稳健版，抗离群污染均值）。

    ⚠ 前提：基线近平坦。**不要直接用于变化剧烈的光变曲线**——它会把人眼
    看来正常的峰谷当离群剪掉。正确用法是先减去趋势/中值，或在平台段使用。
    """
    t = np.asarray(t, dtype=float)
    f = np.asarray(flux, dtype=float)
    m = np.ones(f.shape, dtype=bool)
    for _ in range(iters):
        med = np.nanmedian(f[m])
        mad = np.nanmedian(np.abs(f[m] - med)) or 1e-12
        scale = 1.4826 * mad
        new = np.abs(f - med) < sigma * scale
        if (new == m).all():
            break
        m = new
    return t[m], f[m]


def fold(t: np.ndarray, flux: np.ndarray, period: float,
         t0: float | None = None, centered: bool = True):
    """相位折叠，按相位升序返回。两种约定（两个真实用例各要一种）：

    - centered=True（默认）：phase ∈ [-0.5, 0.5)，凌星/食适合（事件居中）
    - centered=False：[0, 1)，周期变星适合（相位从极小时刻起算）

    t0 缺省取首历元；凌星用目录 T0 可获得与目录一致的相位零点。
    """
    t = np.asarray(t, dtype=float)
    flux = np.asarray(flux, dtype=float)
    if t0 is None:
        t0 = float(t.min())
    phase = ((t - t0) % period) / period
    if centered:
        phase = np.where(phase >= 0.5, phase - 1.0, phase)
    order = np.argsort(phase)
    return phase[order], flux[order]


def bin_phase(phase: np.ndarray, flux: np.ndarray, nbins: int = 30,
              statistic: str = "median"):
    """相位分箱（默认中位数，抗离群）→ (bin 中心, bin 值)；空箱为 NaN。

    相位区间按数据推断：出现负相位 → [-0.5, 0.5)；否则 [0, 1)。
    与 `fold` 的两种约定自动配套。
    """
    phase = np.asarray(phase, dtype=float)
    flux = np.asarray(flux, dtype=float)
    lo, hi = (-0.5, 0.5) if np.nanmin(phase) < 0 else (0.0, 1.0)
    edges = np.linspace(lo, hi, nbins + 1)
    idx = np.clip(np.digitize(phase, edges) - 1, 0, nbins - 1)
    centers = 0.5 * (edges[:-1] + edges[1:])
    vals = np.full(nbins, np.nan)
    for i in range(nbins):
        sel = flux[idx == i]
        if sel.size:
            vals[i] = np.median(sel) if statistic == "median" else sel.mean()
    return centers, vals


def mag_amplitude(flux: np.ndarray) -> float:
    """峰谷幅度（星等）：-2.5·log10(min/max)。注意 TESS 波段幅度比 V 波段压缩。"""
    flux = np.asarray(flux, dtype=float)
    lo, hi = np.nanmin(flux), np.nanmax(flux)
    if lo <= 0:
        raise ValueError("归一化通量含非正值，无法换算星等幅度")
    return float(-2.5 * np.log10(lo / hi))


# ────────────────────────── 周期搜索 ──────────────────────────

@dataclass
class PeriodResult:
    best_period: float          # 精化后的最优周期
    method: str                 # "ls"（仅粗搜）或 "pdm"（粗搜+精化）
    coarse_period: float        # LS 粗搜峰
    periods: np.ndarray         # LS 周期图横轴
    power: np.ndarray           # LS 功率
    refine_periods: np.ndarray | None = None   # PDM 精化网格（refine=False 时 None）
    refine_theta: np.ndarray | None = None     # 对应 θ 值（可直接画图）

    @property
    def correction_pct(self) -> float:
        """精化相对粗搜的修正量（%）。"""
        return abs(self.best_period - self.coarse_period) \
            / self.coarse_period * 100


def _pdm_theta(t: np.ndarray, flux: np.ndarray, period: float,
               nbins: int = 15) -> float:
    """相位离散度 θ：分箱内方差和 / 总方差。越小越像一个真周期。"""
    ph = np.mod(t, period) / period
    var_w, ntot = 0.0, 0
    s2 = ((flux - flux.mean()) ** 2).sum()
    order = np.argsort(ph)
    for chunk in np.array_split(order, nbins):
        if chunk.size < 3:
            continue
        f = flux[chunk]
        var_w += ((f - f.mean()) ** 2).sum()
        ntot += chunk.size
    if ntot <= 1 or s2 <= 0:
        return np.inf
    return (var_w / (ntot - 1)) / (s2 / (len(flux) - 1))


def period_search(t: np.ndarray, flux: np.ndarray,
                  min_period: float, max_period: float,
                  samples_per_peak: int = 10,
                  refine: bool = True,
                  refine_window: float = 0.05,
                  refine_steps: int = 2000) -> PeriodResult:
    """周期搜索：LS 粗搜 →（默认）PDM 精化。

    为什么两步：LS 用单正弦拟合，对造父这类非正弦光变系统性偏峰
    （实测 RT Aur 偏 1.2%，PDM 精化后 0.6%）。
    """
    from astropy.timeseries import LombScargle

    t = np.asarray(t, dtype=float)
    flux = np.asarray(flux, dtype=float)
    freq, power = LombScargle(t, flux).autopower(
        minimum_frequency=1.0 / max_period,
        maximum_frequency=1.0 / min_period,
        samples_per_peak=samples_per_peak)
    periods = 1.0 / freq
    p_coarse = float(1.0 / freq[power.argmax()])

    if not refine:
        return PeriodResult(p_coarse, "ls", p_coarse, periods, power)

    grid = np.linspace(p_coarse * (1 - refine_window),
                       p_coarse * (1 + refine_window), refine_steps)
    thetas = np.array([_pdm_theta(t, flux, p) for p in grid])
    p_best = float(grid[np.argmin(thetas)])
    return PeriodResult(p_best, "pdm", p_coarse, periods, power,
                        refine_periods=grid, refine_theta=thetas)


# ────────────────────────── 凌星搜索 ──────────────────────────

@dataclass
class TransitResult:
    period: float
    depth: float                # 真深度（相对通量，0.014 = 1.4%）
    duration_days: float
    t0: float
    snr: float
    raw: object = None          # TLS 原结果（进阶用法）


def transit_search(t: np.ndarray, flux: np.ndarray,
                   period_min: float = 0.5, period_max: float = 3.0,
                   n_transits_min: int = 3,
                   r_star: float | None = None,
                   m_star: float | None = None) -> TransitResult:
    """TLS 凌星搜索。

    两处焊死的坑（早期真实故障）：
    1. **内部强制归一化**——TLS 要求均值 1；未归一化时它"no transit fit"
       并静默返回 nan，而不是报错
    2. **depth 语义修正**——TLS 的 `depth` 是凌内/凌外通量比（如 0.984），
       真深度 = 1 − depth（如 1.6%）；这里直接返回真深度

    `r_star` / `m_star`（太阳半径/质量，单位同 TLS）是**可选**的恒星参数：
    不传时 TLS 会按默认值（1.0/1.0）构造周期网格，并在网格过稀时警告
    （"period_grid defaults to R_star=1 and M_star=1 ..."）——那条警告是**真问题**
    的提示（网格可能不足以覆盖真实周期），不是噪音，所以我们不抑制它，
    而是把参数暴露出来让调用方给出真实值。传了就转发给 TLS。
    """
    from transitleastsquares import transitleastsquares

    t = np.asarray(t, dtype=float)
    flux = normalize(flux)
    kwargs: dict = {"period_min": period_min, "period_max": period_max,
                    "n_transits_min": n_transits_min}
    if r_star is not None:
        kwargs["R_star"] = float(r_star)
    if m_star is not None:
        kwargs["M_star"] = float(m_star)
    res = transitleastsquares(t, flux).power(**kwargs)
    return TransitResult(
        period=float(res.period),
        depth=float(1.0 - res.depth),
        duration_days=float(res.duration),
        t0=float(getattr(res, "T0", np.nan)),
        snr=float(res.snr),
        raw=res)
