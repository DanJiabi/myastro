"""python 执行器与提交分发：submit / fetch / 批次。

fetch = 缓存短路 + submit + wait 的语法糖；缓存命中不产生 job。
"""
from __future__ import annotations

import threading
from pathlib import Path

from ..config import Config
from ..core import cache_key
from ..db import DB
from .aria2_exec import _start_aria2_job
from .query import wait
from .spec import (
    _DEFAULT_SESSION,
    HEARTBEAT_INTERVAL,
    FetchResult,
    JobSpec,
    RunContext,
)
from .store import _lookup_cached, _register_success


def _run_job(db_path: Path, job_id: int, spec: JobSpec, key: str) -> None:
    db = DB(db_path).init()
    slot = _DEFAULT_SESSION.put(job_id, spec)
    db.conn.execute(
        "UPDATE jobs SET status='running', started_at=datetime('now'),"
        " updated_at=datetime('now') WHERE id=?", (job_id,))
    db.conn.commit()

    stop = threading.Event()

    def heartbeat():
        # 独立连接：sqlite3 默认禁止跨线程使用同一连接
        hdb = DB(db_path).init()
        try:
            while not stop.wait(HEARTBEAT_INTERVAL):
                hdb.conn.execute(
                    "UPDATE jobs SET updated_at=datetime('now') WHERE id=?",
                    (job_id,))
                hdb.conn.commit()
        finally:
            hdb.close()

    hb = threading.Thread(target=heartbeat, daemon=True)
    hb.start()
    ctx = RunContext(source=spec.source, params=spec.params,
                     dest_dir=_dest_dir(spec), cfg=Config())
    fn = spec.fn
    if fn is None and spec.task is not None:
        from ...tasks import TASKS  # myastro.tasks（深度+1）
        fn = TASKS[spec.task]          # 具名任务：跨进程可恢复
    try:
        result = fn(ctx)
        dataset_id = _register_success(db, spec, key, job_id, result)
        db.conn.execute(
            "UPDATE jobs SET status='done', finished_at=datetime('now'),"
            " dataset_id=? WHERE id=?", (dataset_id, job_id))
        db.conn.commit()
        slot["result"] = FetchResult(paths=result.paths, dataset_id=dataset_id,
                                     meta=result.meta)
    except BaseException as exc:                       # noqa: BLE001
        db.conn.execute(
            "UPDATE jobs SET status='failed', error=?, error_type=?,"
            " finished_at=datetime('now') WHERE id=?",
            (repr(exc), type(exc).__name__, job_id))
        db.conn.commit()
        slot["error"] = exc
    finally:
        stop.set()
        db.close()

_dest_dir_cache: dict[str, Path] = {}

def _dest_dir(spec: JobSpec) -> Path:
    d = _dest_dir_cache.get(spec.source)
    if d is None:
        d = Config().source_dir(spec.source)
        d.mkdir(parents=True, exist_ok=True)
        _dest_dir_cache[spec.source] = d
    return d

def submit(spec: JobSpec, db: DB | None = None,
           batch_id: str | None = None, sync: bool = False) -> int:
    """提交作业（不做缓存短路——见 fetch）。返回 job_id。"""
    own = db is None
    db = db or DB().init()
    try:

        cur = db.conn.execute(
            "INSERT INTO jobs(spec_json, executor, url, dest, batch_id)"
            " VALUES(?, ?, ?, ?, ?)",
            (spec.to_json(), spec.executor, spec.url, spec.dest, batch_id))
        db.conn.commit()
        job_id = cur.lastrowid
        key = cache_key(spec.source, spec.params)

        if spec.executor == "python":
            if spec.fn is None and spec.task is None:
                raise ValueError("python 执行器需要 fn 或 task")
            if sync:
                # 阻塞式调用（facade/CLI/notebook）在**调用线程**里跑作业：
                # 非主线程里做 pyarrow 工作会段错误（见 core.write_parquet 文档），
                # 实测本路径 10/10 崩 → 0/5。异步语义仍保留给 submit（TUI/批量）。
                _run_job(db.path, job_id, spec, key)
            else:
                threading.Thread(target=_run_job, daemon=True,
                                 args=(db.path, job_id, spec, key)).start()
        elif spec.executor == "aria2":
            if not spec.url or not spec.dest:
                raise ValueError("aria2 执行器需要 url 与 dest")
            _DEFAULT_SESSION.put(job_id, spec)
            _start_aria2_job(db, job_id, spec, key)
        else:
            raise ValueError(f"未知执行器 {spec.executor}")
        return job_id
    finally:
        if own:
            db.close()

def submit_batch(specs: list[JobSpec],
                 db: DB | None = None) -> tuple[str, list[int]]:
    """批量提交：同一 batch_id，返回 (batch_id, job_ids)。

    批次是一组作业的管理单元（状态/重试/删除按组操作）；
    传输并发由 aria2 原生承担。
    """
    own = db is None
    db = db or DB().init()
    try:
        import uuid
        batch_id = f"b{uuid.uuid4().hex[:8]}"
        return batch_id, [submit(s, db=db, batch_id=batch_id) for s in specs]
    finally:
        if own:
            db.close()

def _dispatch(db: DB, job_id: int, spec: JobSpec, key: str) -> int:
    """按执行器分发（submit 与 retry 共用）。"""
    if spec.executor == "aria2":
        gid_row = db.conn.execute(
            "SELECT gid FROM jobs WHERE id=?", (job_id,)).fetchone()
        if gid_row["gid"]:
            from .. import aria2
            aria2.remove(gid_row["gid"])      # 控制文件保留，续传不从头
        _start_aria2_job(db, job_id, spec, key)
        return job_id
    threading.Thread(target=_run_job, daemon=True,
                     args=(db.path, job_id, spec, key)).start()
    return job_id

def fetch(spec: JobSpec, db: DB | None = None, **wait_kw) -> FetchResult:
    """缓存命中直接返回（不建 job）；否则 submit + wait。"""
    own = db is None
    db = db or DB().init()
    try:
        hit = _lookup_cached(db, cache_key(spec.source, spec.params))
        if hit is not None:
            return hit
        job_id = submit(spec, db=db, sync=True)   # 见 submit：阻塞式调用不用工作线程
        return wait(job_id, db=db, **wait_kw)
    finally:
        if own:
            db.close()
