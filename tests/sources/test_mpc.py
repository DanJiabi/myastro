"""数据源契约：只打桩网络层，描述符/落盘/入库走真实路径。

（测试分层重组迁移；断言未改动。）
"""
import pytest


@pytest.mark.cap("source.contract")
def test_mpc_registers_parquet(env, monkeypatch):
    import pandas as pd

    import myastro.io.sources.mpc as m

    monkeypatch.setattr(
        m,
        "_download_mpc",
        lambda t, n, s: (pd.DataFrame({"RA": [1.0]}), {"target": t, "n_rows": 1}),
    )
    from myastro.io import jobs

    jobs._DEFAULT_SESSION.clear()
    r = m.mpc_ephemeris("Ceres", number=3)
    assert r.paths[0].name == "eph_Ceres.parquet"
