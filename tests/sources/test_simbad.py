"""数据源契约：只打桩网络层，描述符/落盘/入库走真实路径。

（测试分层重组迁移；断言未改动。）
"""
import pytest


@pytest.mark.cap("source.contract")
def test_simbad_empty_ok(env, monkeypatch):
    import myastro.io.sources.simbad as sm

    monkeypatch.setattr(
        sm, "_download_simbad", lambda ra, dec, r: (None, {"n_rows": 0})
    )
    from myastro.io import jobs

    jobs._DEFAULT_SESSION.clear()
    r = sm.simbad_cone(180.0, 0.0)
    assert r.meta["empty"] is True and r.paths == []
