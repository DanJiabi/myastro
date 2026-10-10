"""内核：真 sqlite（tmp），网络打桩；账本/作业/索引/健康/调度/巡检/检索。

（测试分层重组迁移；断言未改动。）
"""

import time

import pytest

from myastro.io import jobs
from myastro.io.db import DB


def make_spec(fn, **params):
    return jobs.JobSpec(source="mock", params={"target": "T", **params}, fn=fn)


class TestHappyPath:
    @pytest.mark.cap("acquire.fetch")
    def test_fetch_registers_dataset_and_files(self, env):
        def fn(ctx):
            p = ctx.dest_dir / "lc.parquet"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"DATA")
            return jobs.FetchResult(paths=[p], dataset_id=-1, meta={"n": 1})

        result = jobs.fetch(make_spec(fn))
        assert result.cache_hit is False
        assert result.paths[0].read_bytes() == b"DATA"

        db = DB().init()
        ds = db.conn.execute("SELECT * FROM datasets").fetchone()
        assert ds["source"] == "mock"
        assert '"target": "T"' in ds["params_json"]
        f = db.conn.execute("SELECT * FROM files").fetchone()
        assert f["size"] == 4 and f["format"] == "parquet"
        j = db.conn.execute("SELECT * FROM jobs").fetchone()
        assert j["status"] == "done" and j["dataset_id"] == ds["id"]

    @pytest.mark.cap("acquire.fetch")
    def test_second_fetch_is_cache_hit_fn_called_once(self, env):
        calls = []

        def fn(ctx):
            calls.append(1)
            p = ctx.dest_dir / "f.bin"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"X")
            return jobs.FetchResult(paths=[p], dataset_id=-1)

        jobs.fetch(make_spec(fn))
        result2 = jobs.fetch(make_spec(fn))
        assert result2.cache_hit is True
        assert len(calls) == 1
        db = DB().init()
        assert db.conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"] == 1

    @pytest.mark.cap("acquire.fetch")
    def test_deleted_file_invalidates_cache(self, env):
        def fn(ctx):
            p = ctx.dest_dir / "f.bin"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"X")
            return jobs.FetchResult(paths=[p], dataset_id=-1)

        jobs.fetch(make_spec(fn))
        next(iter(env.glob("**/f.bin"))).unlink()  # 手动删数据
        result2 = jobs.fetch(make_spec(fn))  # 重新获取
        assert result2.cache_hit is False


class TestFailureAndRetry:
    @pytest.mark.cap("acquire.retry")
    def test_failure_recorded_then_retry_recovers(self, env):
        state = {"fail": True}

        def fn(ctx):
            if state["fail"]:
                raise ConnectionError("remote 503")
            p = ctx.dest_dir / "f.bin"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"OK")
            return jobs.FetchResult(paths=[p], dataset_id=-1)

        spec = make_spec(fn)
        job_id = jobs.submit(spec)
        with pytest.raises(RuntimeError, match="failed"):
            jobs.wait(job_id, timeout=5)

        db = DB().init()
        row = db.conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        assert row["status"] == "failed" and "503" in row["error"]

        state["fail"] = False
        jobs.retry(job_id)
        result = jobs.wait(job_id, timeout=5)
        assert result.paths[0].read_bytes() == b"OK"

    @pytest.mark.cap("acquire.retry")
    def test_done_python_in_registry_force_redownload(self, env):
        """done + force（默认）= 强制重下：注册表内的 python 作业可重提。"""

        def fn(ctx):
            p = ctx.dest_dir / "f.bin"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"X")
            return jobs.FetchResult(paths=[p], dataset_id=-1)

        job_id = jobs.submit(make_spec(fn))
        jobs.wait(job_id, timeout=5)
        jobs.retry(job_id)  # 不再拒绝
        result = jobs.wait(job_id, timeout=5)
        assert result.paths[0].read_bytes() == b"X"

    @pytest.mark.cap("acquire.retry")
    def test_done_no_force_still_rejected(self, env):
        def fn(ctx):
            p = ctx.dest_dir / "f.bin"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"X")
            return jobs.FetchResult(paths=[p], dataset_id=-1)

        job_id = jobs.submit(make_spec(fn))
        jobs.wait(job_id, timeout=5)
        with pytest.raises(ValueError, match="无需 retry"):
            jobs.retry(job_id, force=False)


class TestWaitSemantics:
    @pytest.mark.cap("acquire.fetch")
    def test_wait_timeout_on_slow_fn(self, env):
        def fn(ctx):
            time.sleep(1.0)
            return jobs.FetchResult(paths=[], dataset_id=-1)

        job_id = jobs.submit(make_spec(fn))
        with pytest.raises(TimeoutError):
            jobs.wait(job_id, timeout=0.1, poll=0.05)

    @pytest.mark.cap("acquire.fetch")
    def test_wait_missing_job(self, env):
        DB().init()
        with pytest.raises(LookupError):
            jobs.wait(999)


class TestOrphan:
    @pytest.mark.cap("acquire.retry")
    def test_stale_running_marked_orphaned(self, env):
        db = DB().init()
        db.conn.execute(
            "INSERT INTO jobs(spec_json, executor, status, updated_at)"
            " VALUES('{}','python','running', datetime('now','-10 minutes'))"
        )
        db.conn.commit()
        assert jobs.find_orphans(db=db) == 1
        row = db.conn.execute("SELECT status FROM jobs").fetchone()
        assert row["status"] == "orphaned"

    @pytest.mark.cap("acquire.retry")
    def test_fresh_running_not_marked(self, env):
        db = DB().init()
        db.conn.execute(
            "INSERT INTO jobs(spec_json, executor, status)"
            " VALUES('{}','python','running')"
        )
        db.conn.commit()
        assert jobs.find_orphans(db=db) == 0


class TestSpec:
    @pytest.mark.cap("acquire.fetch")
    def test_aria2_without_url_rejected(self, env):
        spec = jobs.JobSpec(source="ztf", params={}, executor="aria2")
        DB().init()
        with pytest.raises(ValueError):
            jobs.submit(spec)

    @pytest.mark.cap("acquire.fetch")
    def test_python_without_fn_rejected(self, env):
        spec = jobs.JobSpec(source="ztf", params={}, executor="python")
        DB().init()
        with pytest.raises(ValueError, match="fn"):
            jobs.submit(spec)


class TestCrossProcessRetry:
    @pytest.mark.cap("acquire.retry")
    def test_aria2_retry_rebuilds_spec_from_db(self, env, monkeypatch):
        """跨进程（无注册表）：aria2 失败作业可从库重建 spec 重提。"""
        import json as _json

        db = DB().init()
        spec_json = _json.dumps(
            {"source": "ztf", "params": {"name": "f.fits"}, "executor": "aria2"}
        )
        cur = db.conn.execute(
            "INSERT INTO jobs(spec_json, executor, url, dest, status,"
            " error) VALUES(?, 'aria2', 'http://x/f.fits',"
            " '/tmp/f.fits', 'failed', 'x')",
            (spec_json,),
        )
        db.conn.commit()
        job_id = cur.lastrowid
        assert job_id not in jobs._DEFAULT_SESSION._registry  # 模拟跨进程

        started = []

        def fake_start(db_, job_id_, spec_, key_):
            started.append((job_id_, spec_.url, spec_.dest, key_))

        monkeypatch.setattr(jobs.runner, "_start_aria2_job", fake_start)
        jobs.retry(job_id, db=db)
        assert started and started[0][1] == "http://x/f.fits"
        assert started[0][2] == "/tmp/f.fits"

    @pytest.mark.cap("acquire.retry")
    def test_python_cross_process_still_rejected(self, env):
        db = DB().init()
        cur = db.conn.execute(
            "INSERT INTO jobs(spec_json, executor, status)"
            " VALUES('{}', 'python', 'failed')"
        )
        db.conn.commit()
        with pytest.raises(RuntimeError, match="不可跨进程"):
            jobs.retry(cur.lastrowid, db=db)


class TestZombieRetry:
    @pytest.mark.cap("acquire.retry")
    def test_stale_queued_aria2_retryable(self, env, monkeypatch):
        """僵尸态（aria2 queued 心跳超时）可重试——提交进程死了也要能救。"""
        import json as _json

        db = DB().init()
        cur = db.conn.execute(
            "INSERT INTO jobs(spec_json, executor, url, dest, status,"
            " updated_at) VALUES(?, 'aria2', 'http://x/f.fits',"
            " '/tmp/f.fits', 'queued', datetime('now','-10 minutes'))",
            (_json.dumps({"source": "ztf", "params": {}}),),
        )
        db.conn.commit()
        started = []
        monkeypatch.setattr(jobs.runner, "_start_aria2_job", lambda *a: started.append(a[1]))
        jobs.retry(cur.lastrowid, db=db)
        assert started == [cur.lastrowid]

    @pytest.mark.cap("acquire.retry")
    def test_fresh_running_not_retryable(self, env, monkeypatch):
        # 显式声明"守护进程在线"：aria2 离线时 running 作业会被判为僵尸而可重试，
        # 那样本用例的语义就不成立了（CI 上没有 daemon，实测确实因此失败）
        monkeypatch.setattr("myastro.io.aria2.ping", lambda: True)
        db = DB().init()
        cur = db.conn.execute(
            "INSERT INTO jobs(spec_json, executor, status)"
            " VALUES('{}', 'aria2', 'running')"
        )
        db.conn.commit()
        with pytest.raises(ValueError, match="无需 retry"):
            jobs.retry(cur.lastrowid, db=db)


class TestReconcile:
    @pytest.mark.cap("acquire.fetch")
    def test_complete_download_reconciled_to_done(self, env, monkeypatch):
        """RPC 报 complete + 文件在盘 → 收账 done 并入库 dataset。"""
        import json as _json

        db = DB().init()
        # dest 必须在数据根内（与生产一致：dest 由 Config().data 派生）；
        # 路径兜底见 tests/kernel/test_path_containment.py
        f = env / "data" / "ztf" / "f.fits"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"FITS")
        cur = db.conn.execute(
            "INSERT INTO jobs(spec_json, executor, url, dest, status, gid)"
            " VALUES(?, 'aria2', 'http://x/f.fits', ?, 'running', 'g1')",
            (_json.dumps({"source": "ztf", "params": {"name": "f.fits"}}), str(f)),
        )
        db.conn.commit()

        monkeypatch.setattr("myastro.io.aria2.ping", lambda: True)
        monkeypatch.setattr(
            "myastro.io.aria2.status",
            lambda gid: {
                "status": "complete",
                "completedLength": "4",
                "totalLength": "4",
                "downloadSpeed": "0",
                "errorCode": "0",
                "errorMessage": "",
            },
        )
        n = jobs.reconcile_aria2(db=db)
        assert n == 1
        row = db.conn.execute(
            "SELECT status, dataset_id FROM jobs WHERE id=?", (cur.lastrowid,)
        ).fetchone()
        assert row["status"] == "done" and row["dataset_id"] is not None

    @pytest.mark.cap("acquire.fetch")
    def test_error_download_reconciled_to_failed(self, env, monkeypatch):
        db = DB().init()
        cur = db.conn.execute(
            "INSERT INTO jobs(spec_json, executor, url, dest, status, gid)"
            " VALUES('{}', 'aria2', 'http://x/f.fits', '/tmp/none.fits',"
            " 'running', 'g2')"
        )
        db.conn.commit()
        monkeypatch.setattr("myastro.io.aria2.ping", lambda: True)
        monkeypatch.setattr(
            "myastro.io.aria2.status",
            lambda gid: {
                "status": "error",
                "completedLength": "0",
                "totalLength": "0",
                "downloadSpeed": "0",
                "errorCode": "3",
                "errorMessage": "not found",
            },
        )
        assert jobs.reconcile_aria2(db=db) == 1
        row = db.conn.execute(
            "SELECT status, error FROM jobs WHERE id=?", (cur.lastrowid,)
        ).fetchone()
        assert row["status"] == "failed" and "3" in row["error"]

    @pytest.mark.cap("acquire.fetch")
    def test_active_download_not_written(self, env, monkeypatch):
        db = DB().init()
        db.conn.execute(
            "INSERT INTO jobs(spec_json, executor, url, dest, status, gid)"
            " VALUES('{}', 'aria2', 'http://x/f.fits', '/tmp/x.fits',"
            " 'running', 'g3')"
        )
        db.conn.commit()
        monkeypatch.setattr("myastro.io.aria2.ping", lambda: True)
        monkeypatch.setattr(
            "myastro.io.aria2.status",
            lambda gid: {
                "status": "active",
                "completedLength": "10",
                "totalLength": "100",
                "downloadSpeed": "1000",
                "errorCode": "0",
                "errorMessage": "",
            },
        )
        assert jobs.reconcile_aria2(db=db) == 0  # 活动中不写库
        assert (
            db.conn.execute("SELECT status FROM jobs WHERE gid='g3'").fetchone()[0]
            == "running"
        )

    @pytest.mark.cap("acquire.fetch")
    def test_daemon_offline_noop(self, env, monkeypatch):
        db = DB().init()
        db.conn.execute(
            "INSERT INTO jobs(spec_json, executor, url, dest, status, gid)"
            " VALUES('{}', 'aria2', 'u', 'd', 'running', 'g4')"
        )
        db.conn.commit()
        monkeypatch.setattr("myastro.io.aria2.ping", lambda: False)
        assert jobs.reconcile_aria2(db=db) == 0


class TestDoneForceRedownload:
    @pytest.mark.cap("acquire.retry")
    def test_done_aria2_cross_process_force(self, env, monkeypatch):
        """done 的 aria2 作业跨进程可强制重下（spec 从库重建）。"""
        import json as _json

        db = DB().init()
        cur = db.conn.execute(
            "INSERT INTO jobs(spec_json, executor, url, dest, status)"
            " VALUES(?, 'aria2', 'http://x/f.fits', '/tmp/f.fits', 'done')",
            (_json.dumps({"source": "ztf", "params": {}}),),
        )
        db.conn.commit()
        started = []
        monkeypatch.setattr(jobs.runner, "_start_aria2_job", lambda *a: started.append(a[1]))
        jobs.retry(cur.lastrowid, db=db)
        assert started == [cur.lastrowid]


class TestDeleteJobs:
    @pytest.mark.cap("acquire.cancel")
    def test_delete_failed_keeps_assets(self, env):
        db = DB().init()
        f = env / "data" / "ztf" / "x.fits"
        f.parent.mkdir(parents=True)
        f.write_bytes(b"F")
        cur = db.conn.execute(
            "INSERT INTO jobs(spec_json,executor,url,dest,status)"
            " VALUES('{}','aria2','u','d','failed')"
        )
        jid = cur.lastrowid
        ds = db.conn.execute(
            "INSERT INTO datasets(source,params_json,cache_key) VALUES('ztf','{}','k')"
        )
        db.conn.execute(
            "INSERT INTO files(dataset_id,path,size) VALUES(?,?,1)",
            (ds.lastrowid, str(f)),
        )
        db.conn.commit()
        out = jobs.delete_jobs([jid], db=db)
        assert out["deleted"] == [jid]
        assert (
            db.conn.execute("SELECT COUNT(*) c FROM files").fetchone()["c"] == 1
        )  # 资产保留
        assert db.conn.execute("SELECT COUNT(*) c FROM datasets").fetchone()["c"] == 1

    @pytest.mark.cap("acquire.cancel")
    def test_healthy_running_refused(self, env, monkeypatch):
        db = DB().init()
        cur = db.conn.execute(
            "INSERT INTO jobs(spec_json,executor,status,updated_at)"
            " VALUES('{}','aria2','running', datetime('now'))"
        )
        db.conn.commit()
        monkeypatch.setattr("myastro.io.aria2.ping", lambda: True)
        out = jobs.delete_jobs([cur.lastrowid], db=db)
        assert out["refused"] and "活跃" in out["refused"][0][1]

    @pytest.mark.cap("acquire.cancel")
    def test_missing_id_reported(self, env):
        DB().init()
        out = jobs.delete_jobs([999], db=DB().init())
        assert out["refused"][0][1] == "不存在"


class TestPythonZombie:
    @pytest.mark.cap("acquire.retry")
    def test_stale_python_with_task_retryable(self, env, monkeypatch):
        """python 执行器：心跳超时 + 有具名 task → 僵尸可跨进程重试。"""
        import json as _json

        db = DB().init()
        cur = db.conn.execute(
            "INSERT INTO jobs(spec_json, executor, status, updated_at)"
            " VALUES(?, 'python', 'running', datetime('now','-10 minutes'))",
            (
                _json.dumps(
                    {"source": "gaia", "params": {"ra": 1}, "task": "gaia_cone"}
                ),
            ),
        )
        db.conn.commit()
        ran = []

        def fake_run(*a):
            ran.append(a[1])

        monkeypatch.setattr(jobs.runner, "_run_job", fake_run)
        jobs.retry(cur.lastrowid, db=db)
        assert ran == [cur.lastrowid]

    @pytest.mark.cap("acquire.retry")
    def test_stale_python_without_task_still_blocked(self, env):
        db = DB().init()
        cur = db.conn.execute(
            "INSERT INTO jobs(spec_json, executor, status, updated_at)"
            " VALUES('{}', 'python', 'running', datetime('now','-10 minutes'))"
        )
        db.conn.commit()
        with pytest.raises(ValueError, match="无需 retry"):
            jobs.retry(cur.lastrowid, db=db)


class TestOldJobTaskInference:
    @pytest.mark.cap("acquire.retry")
    def test_pre_E0_python_job_retryable_via_descriptor(self, env, monkeypatch):
        """E0 前的无 task 旧作业：从源描述符推断具名任务，跨进程可重下。"""
        import json as _json

        db = DB().init()
        cur = db.conn.execute(  # 无 task 字段的旧格式 spec
            "INSERT INTO jobs(spec_json, executor, status) VALUES(?, 'python', 'done')",
            (_json.dumps({"source": "gaia", "params": {"ra": 1.0, "dec": 2.0}}),),
        )
        db.conn.commit()
        ran = []
        monkeypatch.setattr(jobs.runner, "_run_job", lambda *a: ran.append(a[1]))
        jobs.retry(cur.lastrowid, db=db)  # done + force（默认）
        assert ran == [cur.lastrowid]


class TestMetaPersisted:
    @pytest.mark.cap("manage.ledger")
    def test_cache_hit_returns_meta(self, env):
        """meta（溯源信息，如 ra/dec）必须随缓存命中返回。

        真实故障：notebook 02 依赖 result.meta['ra']，首次下载有值，
        二次缓存命中为空 → KeyError('ra')。
        """

        def fn(ctx):
            p = ctx.dest_dir / "lc.parquet"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"DATA")
            return jobs.FetchResult(
                paths=[p],
                dataset_id=-1,
                meta={"ra": 97.14203, "dec": 30.49304, "sector": 20},
            )

        first = jobs.fetch(make_spec(fn))
        assert first.meta["ra"] == 97.14203

        second = jobs.fetch(make_spec(fn))
        assert second.cache_hit is True
        assert second.meta == first.meta  # 缓存命中 meta 不丢

    @pytest.mark.cap("manage.ledger")
    def test_empty_meta_does_not_clobber(self, env):
        """无 meta 的重复获取不应清掉已存 meta。"""

        def with_meta(ctx):
            p = ctx.dest_dir / "a.parquet"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"A")
            return jobs.FetchResult(paths=[p], dataset_id=-1, meta={"k": 1})

        jobs.fetch(make_spec(with_meta))
        jobs.fetch(make_spec(with_meta))  # 命中（不再执行 fn）
        db = DB().init()
        import json as _json

        stored = _json.loads(
            db.conn.execute("SELECT meta_json m FROM datasets").fetchone()["m"]
        )
        assert stored == {"k": 1}


class TestAria2Validation:
    @pytest.mark.cap("acquire.fetch")
    def test_aria2_requires_url_dest(self, env):
        DB().init()
        spec = jobs.JobSpec(source="ztf", params={}, executor="aria2")
        with pytest.raises(ValueError, match="url"):
            jobs.submit(spec)


@pytest.mark.cap("acquire.retry")
def test_named_task_cross_process_retry(env, monkeypatch):
    """python 作业带具名 task：跨进程（无会话）可重建 spec 重试。

    走公开 jobs.retry()（而非私有 _resolve_retry_spec）；执行入口打桩
    仅为隔离网络，断言的是"作业确实被重新跑起来"这一行为。
    """
    import json as _json

    from myastro.io import jobs
    from myastro.io.db import DB

    db = DB().init()
    cur = db.conn.execute(
        "INSERT INTO jobs(spec_json, executor, status, error)"
        " VALUES(?, 'python', 'failed', 'x')",
        (
            _json.dumps(
                {
                    "source": "tess",
                    "params": {"target": "T", "sector": 20, "cadence": "2m"},
                    "task": "tess_lightcurve",
                }
            ),
        ),
    )
    db.conn.commit()
    jobs._DEFAULT_SESSION.clear()  # 模拟跨进程（新会话）
    restarted = []
    monkeypatch.setattr(jobs.runner, "_run_job", lambda *a: restarted.append(a[1]))
    jobs.retry(cur.lastrowid, db=db)
    assert restarted == [cur.lastrowid], "跨进程重试未真正重跑作业"


class TestTuiCacheShortCircuit:
    @pytest.mark.cap("acquire.fetch")
    def test_check_cache_public(self, env, monkeypatch):
        """jobs.check_cache 公开可用（TUI 提交前短路依据）。"""
        monkeypatch.setenv("MYASTRO_DATA", str(env / "data"))
        monkeypatch.setenv("MYASTRO_DB", str(env / "astro.db"))
        from myastro.io import jobs
        from myastro.io.db import DB
        from myastro.io.jobs import JobSpec

        db = DB().init()
        f = env / "data" / "ztf" / "x.fits"
        f.parent.mkdir(parents=True)
        f.write_bytes(b"F")
        from myastro.io.core import cache_key

        key = cache_key("ztf", {"name": "x.fits"})
        cur = db.conn.execute(
            "INSERT INTO datasets(source,params_json,cache_key) VALUES('ztf','{}',?)",
            (key,),
        )
        db.conn.execute(
            "INSERT INTO files(dataset_id,path,size) VALUES(?,?,1)",
            (cur.lastrowid, str(f)),
        )
        db.conn.commit()
        spec = JobSpec(
            source="ztf",
            params={"name": "x.fits"},
            executor="aria2",
            url="u",
            dest=str(f),
        )
        hit = jobs.check_cache(spec)
        assert hit is not None and hit.cache_hit
        miss = jobs.check_cache(
            JobSpec(
                source="ztf",
                params={"name": "other.fits"},
                executor="aria2",
                url="u",
                dest="d",
            )
        )
        assert miss is None
