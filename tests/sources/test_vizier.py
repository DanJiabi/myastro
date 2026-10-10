"""数据源契约：只打桩网络层，描述符/落盘/入库走真实路径。

（测试分层重组迁移；断言未改动。）
"""
import pytest


@pytest.mark.cap("source.contract")
def test_vizier_via_facade(env, monkeypatch):
    import pandas as pd

    import myastro.io.sources.vizier as vz

    monkeypatch.setattr(
        vz,
        "_download_vizier",
        lambda c, ra, dec, r: (pd.DataFrame({"j": [1]}), {"catalog": c, "n_rows": 1}),
    )
    import myastro as ma

    r = ma.fetch("vizier", catalog="II/246", ra=1.0, dec=2.0)
    assert r.paths[0].suffix == ".parquet"
