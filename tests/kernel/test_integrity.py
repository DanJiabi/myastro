"""内核：真 sqlite（tmp），网络打桩；账本/作业/索引/健康/调度/巡检/检索。

（测试分层重组迁移；断言未改动。）
"""
import pytest


@pytest.mark.cap("manage.integrity")
def test_audit_baseline_then_corrupt(env, monkeypatch):
    from myastro.io.integrity import audit, audit_detail

    db, f = _mk(env, monkeypatch)
    r1 = audit(db=db)  # 首次：建基线
    assert r1["baselined"] == 1 and r1["corrupt"] == 0
    f.write_bytes(b"EVIL")  # 篡改（同长度 4B 防 size 拦截）
    r2 = audit(db=db)
    assert r2["corrupt"] == 1
    assert audit_detail("corrupt")[0]["path"].endswith(".fits")


@pytest.mark.cap("manage.integrity")
def test_audit_missing(env, monkeypatch):
    from myastro.io.integrity import audit

    db, f = _mk(env, monkeypatch)
    f.unlink()
    r = audit(db=db)
    assert r["missing"] == 1


def _mk(env, monkeypatch, content=b"DATA", sha=None):
    monkeypatch.setenv("MYASTRO_DATA", str(env / "data"))
    monkeypatch.setenv("MYASTRO_DB", str(env / "astro.db"))
    from myastro.io import jobs
    from myastro.io.db import DB

    jobs._DEFAULT_SESSION.clear()
    db = DB().init()
    f = env / "data" / "legacy" / "tractor-0001x002.fits"
    f.parent.mkdir(parents=True)
    f.write_bytes(content)
    cur = db.conn.execute(
        "INSERT INTO datasets(source,target,params_json,cache_key)"
        " VALUES('legacy','t','{}','kc1')"
    )
    db.conn.execute(
        "INSERT INTO files(dataset_id,path,size,sha256,format) VALUES(?,?,?,?,?)",
        (cur.lastrowid, str(f), len(content), sha, "fits"),
    )
    db.conn.commit()
    return db, f
