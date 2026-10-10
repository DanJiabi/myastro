"""内核：真 sqlite（tmp），网络打桩；账本/作业/索引/健康/调度/巡检/检索。

（测试分层重组迁移；断言未改动。）
"""
import pytest


class TestBatchE3:
    @pytest.mark.cap("acquire.batch")
    def test_submit_batch_shares_id(self, env, monkeypatch):
        from myastro.io import jobs
        from myastro.io.db import DB
        from myastro.io.jobs import JobSpec

        started = []
        monkeypatch.setattr(
            jobs.runner, "_start_aria2_job", lambda db, jid, spec, key: started.append(jid)
        )
        specs = [
            JobSpec(
                source="legacy",
                executor="aria2",
                params={"brick": b},
                url=f"https://x/{b}",
                dest=f"/tmp/{b}",
            )
            for b in ("0001m002", "0001m005")
        ]
        batch_id, ids = jobs.submit_batch(specs, db=DB().init())
        assert len(ids) == 2 and len(set(ids)) == 2
        rows = jobs.status(batch_id=batch_id)
        assert len(rows) == 2 and {r["batch_id"] for r in rows} == {batch_id}

    @pytest.mark.cap("acquire.batch")
    def test_facade_batch(self, env, monkeypatch):
        import myastro as ma
        from myastro.io import jobs

        monkeypatch.setattr(jobs.runner, "_start_aria2_job", lambda *a: None)
        out = ma.batch("legacy", [{"brick": "0001m002"}, {"brick": "0001m005"}])
        assert out["n"] == 2
        rows = ma.status(batch_id=out["batch_id"])
        assert len(rows) == 2


@pytest.mark.cap("acquire.batch")
def test_retry_batch(env, monkeypatch):
    from myastro.io import jobs
    from myastro.io.db import DB

    started = []
    from myastro.io.jobs import runner  # 打桩打在"使用处"
    monkeypatch.setattr(
        runner, "_start_aria2_job",
        lambda db, jid, spec, key: started.append(jid))
    db = DB().init()
    bid = "btest01"
    for st in ("failed", "done", "failed"):
        db.conn.execute(
            "INSERT INTO jobs(spec_json, executor, url, dest, status,"
            " batch_id) VALUES(?, 'aria2', 'u', 'd', ?, ?)",
            ('{"source":"legacy"}', st, bid),
        )
    db.conn.commit()
    out = jobs.retry_batch(bid, db=db)
    assert len(out["retried"]) == 2 and len(out["skipped"]) == 1

    with pytest.raises(LookupError):
        jobs.retry_batch("nope", db=db)


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
