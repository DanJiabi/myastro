"""数据源契约：只打桩网络层，描述符/落盘/入库走真实路径。

（测试分层重组迁移；断言未改动。）
"""

import pandas as pd
import pytest

from myastro.io.db import DB
from myastro.io.sources import gaia


@pytest.mark.cap("source.contract")
def test_gaia_without_columns(env, monkeypatch):
    """回归：描述符无 columns 字段时 gaia 任务不得 KeyError。"""
    monkeypatch.setenv("MYASTRO_DATA", str(env / "data"))
    monkeypatch.setenv("MYASTRO_DB", str(env / "astro.db"))
    import pandas as pd

    import myastro.io.sources.gaia as g

    monkeypatch.setattr(
        g,
        "_download_gaia",
        lambda ra, dec, r, cols=None: (pd.DataFrame({"source_id": [1]}), {"ra": ra}),
    )
    from myastro.io import jobs

    jobs._DEFAULT_SESSION.clear()
    import myastro as ma

    r = ma.fetch("gaia", ra=1.0, dec=2.0)  # 不传 columns
    assert r.paths[0].suffix == ".parquet"


class TestGaia:
    @pytest.mark.cap("source.contract")
    def test_radius_validation(self, env):
        DB().init()
        for bad in (0, -1, 10):
            try:
                gaia.gaia_cone(10, 10, bad)
                assert False
            except ValueError:
                pass

    @pytest.mark.cap("source.contract")
    def test_fn_writes_parquet_and_registers(self, env, monkeypatch):

        def fake(ra, dec, radius, columns):
            df = pd.DataFrame({"source_id": [1, 2], "parallax": [3.3, 0.5]})
            return df, {"ra": ra, "dec": dec, "radius_deg": radius, "n_rows": 2}

        monkeypatch.setattr(gaia, "_download_gaia", fake)
        r = gaia.gaia_cone(339.2729, 58.4153, 0.05)
        assert "cone_339.2729_+58.4153_r0.05.parquet" in str(r.paths[0])
        assert r.meta["n_rows"] == 2
        db = DB().init()
        assert (
            db.conn.execute(
                "SELECT COUNT(*) c FROM datasets WHERE source='gaia'"
            ).fetchone()["c"]
            == 1
        )


@pytest.mark.cap("source.contract")
def test_gaia_custom_columns_do_not_collide_with_default(env, monkeypatch):
    """默认列与自定义列的同位置锥搜必须落到不同文件（真实事故：账本 #3 幽灵）。

    #3（含 columns 参数）与 #36（同坐标同半径、无 columns）共用了同一个
    `cone_*.parquet` 文件名 → 后到者把文件据为己有，#3 成为无文件幽灵。
    """
    import pandas as pd

    import myastro.io.sources.gaia as g

    monkeypatch.setattr(
        g, "_download_gaia",
        lambda ra, dec, r, columns=None: (
            pd.DataFrame({"ra": [ra]}), {"ra": ra, "n_rows": 1}),
    )
    from myastro.io import jobs

    jobs._DEFAULT_SESSION.clear()
    a = g.gaia_cone(97.142, 30.493, 0.02)                       # 默认列
    jobs._DEFAULT_SESSION.clear()
    b = g.gaia_cone(97.142, 30.493, 0.02,                       # 自定义列
                    columns=["source_id", "ra", "dec"])
    assert a.paths[0] != b.paths[0], "columns 不同必须落到不同文件"
    assert b.paths[0].name.startswith("cone_97.1420_+30.4930_r0.02_c")
    # 向后兼容：默认列仍用旧文件名（既有缓存继续命中）
    assert a.paths[0].name == "cone_97.1420_+30.4930_r0.02.parquet"
