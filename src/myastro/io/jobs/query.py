"""查询：作业状态列表与阻塞等待（含会话结果槽与最终异常）。"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..core import cache_key
from ..db import DB
from .aria2_exec import _poll_aria2
from .spec import _DEFAULT_SESSION, FetchResult, JobFailed


def status(db: DB | None = None, batch_id: str | None = None
           ) -> list[dict[str, Any]]:
    own = db is None
    db = db or DB().init()
    try:
        if batch_id:
            rows = db.conn.execute(
                "SELECT id, executor, status, progress, error, updated_at,"
                " dataset_id, batch_id FROM jobs WHERE batch_id=?"
                " ORDER BY id", (batch_id,)).fetchall()
        else:
            rows = db.conn.execute(
                "SELECT id, executor, status, progress, error, updated_at,"
                " dataset_id, batch_id FROM jobs ORDER BY id DESC LIMIT 100"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        if own:
            db.close()

def wait(job_id: int, *, timeout: float | None = None,
         poll: float = 0.2, db: DB | None = None) -> FetchResult:
    """阻塞等 job 完成。timeout 语义是"无进展的干等"，默认 None（无限），
    慢网络下靠心跳而非 wall-clock 判死。"""
    own = db is None
    db = db or DB().init()
    try:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            row = db.conn.execute(
                "SELECT status, dataset_id, executor, error_type FROM jobs"
                " WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise LookupError(f"job {job_id} 不存在")
            if row["status"] == "done":
                slot = _DEFAULT_SESSION.slot(job_id)
                if "result" in slot:
                    return slot["result"]
                files = db.conn.execute(
                    "SELECT path FROM files WHERE dataset_id=?",
                    (row["dataset_id"],)).fetchall()
                return FetchResult(paths=[Path(f["path"]) for f in files],
                                   dataset_id=row["dataset_id"])
            if row["status"] in ("failed", "orphaned"):
                slot = _DEFAULT_SESSION.slot(job_id)
                exc = slot.get("error")
                etype = type(exc).__name__ if exc is not None else None
                if etype is None:
                    # 注意：sqlite3.Row 的 `in` 判的是"值"，不是列名——
                    # 必须用 keys()（ruff SIM118 在此不适用）
                    etype = (row["error_type"]
                             if "error_type" in row.keys()  # noqa: SIM118
                             else None)
                raise JobFailed(
                    f"job {job_id} {row['status']}: "
                    f"{exc if exc is not None else '见 jobs.error'}", etype)
            if deadline is not None and time.monotonic() > deadline:
                raise TimeoutError(f"wait job {job_id} 超时")
            if row["executor"] == "aria2":
                spec = _DEFAULT_SESSION.spec(job_id)
                if spec is not None:      # 本进程提交的 job 才能主动轮询收账
                    done = _poll_aria2(db, job_id, spec,
                                       cache_key(spec.source, spec.params))
                    if done is not None:
                        return done
            time.sleep(poll)
    finally:
        if own:
            db.close()
