"""坐标解析与圆锥几何（capabilities §3 本地检索坐标精确化）。

覆盖三类真实形态：
1. 参数直带 ra/dec（gaia/simbad/vizier/ztf-lc/unwise）
2. 坐标藏在 meta（tess：FITS 头 RA_OBJ/DEC_OBJ 随 meta_json 落库）
3. 参数只有编号（ztf/f 号、legacy brick 名）→ 查索引解析
4. 兜底：文件名带编号（tractor-<brick>.fits，TUI 快速下载/清单进来的数据）
"""
from __future__ import annotations

import pandas as pd
import pytest

from myastro.io.coords import angular_separation, resolve_coords


@pytest.fixture
def indexes(env, monkeypatch):
    """合成两份索引：ztf-fields（编号键）与 legacy-bricks（名字键）。

    用 monkeypatch.setitem 覆盖注册项（teardown 自动还原）——
    早期版本用 pop 清场，会把**真实的注册项删掉**，污染后续所有用索引的测试。
    """
    from myastro.io import index as idx

    monkeypatch.setitem(idx.INDEXES, "ztf-fields",
                        {"desc": "测试", "key_col": "field"})
    monkeypatch.setitem(idx.INDEXES, "legacy-bricks",
                        {"desc": "测试", "key_col": "brickname"})
    pd.DataFrame({"field": [673, 674], "ra": [196.1766, 196.5],
                  "dec": [33.35, 33.4]}).to_parquet(
        idx.index_path("ztf-fields"), index=False)
    pd.DataFrame({"brickname": ["0001m002"], "ra": [0.125],
                  "dec": [-0.25]}).to_parquet(
        idx.index_path("legacy-bricks"), index=False)
    yield
    for name in ("ztf-fields", "legacy-bricks"):
        idx.index_path(name).unlink(missing_ok=True)


@pytest.mark.cap("manage.search")
class TestResolve:
    def test_params_direct(self):
        assert resolve_coords("gaia", {"ra": 10.0, "dec": -5.0}) == (10.0, -5.0)

    def test_ra_normalized_to_0_360(self):
        ra, _ = resolve_coords("gaia", {"ra": -10.0, "dec": 0.0})
        assert ra == pytest.approx(350.0)

    def test_meta_fallback(self):
        """tess：参数无坐标，坐标在 meta（FITS 头）。"""
        c = resolve_coords("tess", {"target": "X"},
                           {"ra": 97.6367, "dec": 29.6723})
        assert c == pytest.approx((97.6367, 29.6723))

    def test_field_via_index(self, indexes):
        c = resolve_coords("ztf", {"field": 673, "ffd": "2020..."})
        assert c == pytest.approx((196.1766, 33.35))
        assert resolve_coords("ztf-meta", {"field": 674})[0] == \
            pytest.approx(196.5)

    def test_brick_via_index(self, indexes):
        assert resolve_coords("legacy", {"brick": "0001m002"}) == \
            pytest.approx((0.125, -0.25))

    def test_filename_fallback_legacy(self, indexes):
        """参数只剩 name/url 时的兜底：从 tractor-<brick>.fits 解析。"""
        c = resolve_coords("legacy", {"name": "tractor-0001m002.fits"},
                           {}, ["/data/MAD/legacy/tractor-0001m002.fits"])
        assert c == pytest.approx((0.125, -0.25))

    def test_unknown_field_not_resolved(self, indexes):
        assert resolve_coords("ztf", {"field": 99999}) is None

    def test_unresolvable_returns_none(self):
        assert resolve_coords("mpc", {"target": "Ceres"}) is None
        assert resolve_coords("index", {"name": "legacy-bricks"}) is None

    def test_invalid_dec_rejected(self):
        """赤纬越界的数据不当成坐标用。"""
        assert resolve_coords("gaia", {"ra": 10.0, "dec": 95.0}) is None

    def test_params_win_over_index(self, indexes):
        c = resolve_coords("ztf", {"field": 673, "ra": 1.0, "dec": 2.0})
        assert c == pytest.approx((1.0, 2.0))


@pytest.mark.cap("manage.search")
class TestAngularSeparation:
    def test_zero(self):
        assert angular_separation(10.0, 20.0, 10.0, 20.0) == 0.0

    def test_known_pair(self):
        # 赤道上相距 1° 赤经 → 1° 角距
        assert angular_separation(0.0, 0.0, 1.0, 0.0) == pytest.approx(1.0)

    def test_declination_scales(self):
        """dec=60° 处 1° 赤经差 ≈ 0.5° 角距。

        注意容差：`cos(dec)·Δra` 是小角度近似，1° 尺度上真值略小
        （实测 0.4999952），故用 1e-4 而非机器精度。
        """
        assert angular_separation(0.0, 60.0, 1.0, 60.0) == \
            pytest.approx(0.5, abs=1e-4)

    def test_wraparound_is_short_path(self):
        # 359.9° 与 0.1° 只差 0.2°，不是 359.8°
        assert angular_separation(359.9, 0.0, 0.1, 0.0) == \
            pytest.approx(0.2, abs=1e-6)

    def test_pole(self):
        assert angular_separation(0.0, 90.0, 123.0, 89.0) == \
            pytest.approx(1.0)
