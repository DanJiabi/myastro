"""数据源契约：只打桩网络层，描述符/落盘/入库走真实路径。

（测试分层重组迁移；断言未改动。）
"""

import numpy as np
import pytest

from myastro.io.sources.exoplanet import _FIELDS, exoplanet_params

"""exoplanet 源测试：多解选择必须确定性（真实故障回归）。

故障回溯：ps 表对同一行星有多组解，早期实现"取第一组周期非空的"，
行序随归档漂移 → 同一行星两次调用给出不同 T0/深度，
notebook 复跑时拿到 pl_trandep=None 直接崩。
"""


class _FakeTable(list):
    """够用的假表：len/迭代/下标取列，模拟 astroquery 返回。"""

    def __getitem__(self, i):
        row = super().__getitem__(i)
        return row


def _row(**kw):
    base = {f: np.ma.masked for f in _FIELDS}
    base.update(kw)
    return base


@pytest.fixture
def patch_archive(monkeypatch):
    def install(rows):
        from astroquery.ipac.nexsci.nasa_exoplanet_archive import NasaExoplanetArchive

        monkeypatch.setattr(
            NasaExoplanetArchive,
            "query_criteria",
            staticmethod(lambda **kw: _FakeTable(rows)),
        )

    return install


class TestSolutionSelection:
    @pytest.mark.cap("source.contract")
    def test_prefers_complete_solution_regardless_of_row_order(self, patch_archive):
        """深度缺失的解排在最前——仍须选到信息完整的那组。"""
        incomplete = _row(
            pl_name="X b", pl_orbper=1.09, pl_orbpererr1=1e-6, pl_tranmid=111.0
        )
        complete = _row(
            pl_name="X b",
            pl_orbper=1.0914,
            pl_orbpererr1=3e-6,
            pl_trandep=1.53,
            pl_tranmid=2458842.99,
        )
        patch_archive([incomplete, complete])
        got = exoplanet_params("X b")
        assert got["pl_trandep"] == pytest.approx(1.53)
        assert got["pl_tranmid"] == pytest.approx(2458842.99)

    @pytest.mark.cap("source.contract")
    def test_most_precise_among_complete(self, patch_archive):
        coarse = _row(pl_name="Y b", pl_orbper=2.0, pl_orbpererr1=1e-3, pl_trandep=1.0)
        precise = _row(
            pl_name="Y b", pl_orbper=2.0001, pl_orbpererr1=1e-7, pl_trandep=1.0
        )
        patch_archive([coarse, precise])
        assert exoplanet_params("Y b")["pl_orbper"] == pytest.approx(2.0001)

    @pytest.mark.cap("source.contract")
    def test_deterministic_across_orderings(self, patch_archive):
        a = _row(
            pl_name="Z b",
            pl_orbper=3.0,
            pl_orbpererr1=5e-6,
            pl_trandep=1.2,
            pl_tranmid=5.0,
        )
        b = _row(
            pl_name="Z b",
            pl_orbper=3.0001,
            pl_orbpererr1=5e-6,
            pl_trandep=1.2,
            pl_tranmid=6.0,
        )
        patch_archive([a, b])
        first = exoplanet_params("Z b")
        patch_archive([b, a])  # 行序颠倒
        second = exoplanet_params("Z b")
        assert first == second

    @pytest.mark.cap("source.contract")
    def test_fallback_to_period_only(self, patch_archive):
        patch_archive([_row(pl_name="W b", pl_orbper=7.0, pl_orbpererr1=1e-5)])
        got = exoplanet_params("W b")
        assert got["pl_orbper"] == pytest.approx(7.0)
        assert got["pl_trandep"] is None

    @pytest.mark.cap("source.contract")
    def test_unknown_planet_raises(self, patch_archive):
        patch_archive([])
        with pytest.raises(LookupError):
            exoplanet_params("Nope b")
