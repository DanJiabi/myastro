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
