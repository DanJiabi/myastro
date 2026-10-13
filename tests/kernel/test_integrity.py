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


@pytest.mark.cap("manage.integrity")
def test_audit_unlinked_dataset(env):
    """有 dataset 无文件且非空结果 → audit 报 unlinked（真实事故 #39/#27 的防线）。"""
    from myastro.io.db import DB
    from myastro.io.integrity import audit, audit_detail

    db = DB().init()
    db.conn.execute(
        "INSERT INTO datasets(source,target,params_json,cache_key,meta_json)"
        " VALUES('mpc','Ceres','{}','k1',NULL)")
    db.conn.execute(
        "INSERT INTO datasets(source,target,params_json,cache_key,meta_json)"
        " VALUES('ztf-lc','','{}','k2','{\"empty\": true}')")
    db.conn.commit()

    r = audit(db=db)
    assert r["unlinked"] == 1, "只有无文件且非空结果的数据集才算 unlinked"
    detail = audit_detail("unlinked")
    assert len(detail) == 1 and detail[0]["source"] == "mpc"
    assert detail[0]["dataset_id"]
