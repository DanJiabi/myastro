"""生命周期策略：僵尸判定、重试准入、跨进程重建、删除与批次重试。"""
from __future__ import annotations

import json

from ..core import cache_key
from ..db import DB
from .rebuild import _infer_task
from .runner import _dispatch
from .spec import _DEFAULT_SESSION, ORPHAN_AFTER, JobSpec


def _retry_allowed(row, db: DB, force: bool) -> bool:
    """重试准入判定（唯一出口，四种语义集中于此）：
    failed/orphaned 直通；僵尸态（aria2 queued/running 且 daemon 离线或
    心跳超时）；done + force 且 spec 可得（本进程或 aria2 可重建）。
    """
    if row["status"] in ("failed", "orphaned"):
        return True
    if row["status"] in ("queued", "running"):
        age_days = db.conn.execute(
            "SELECT julianday('now') - julianday(?)",
            (row["updated_at"],)).fetchone()[0]
        stale_age = age_days is None or age_days * 86400 > 300
        if row["executor"] == "aria2":
            from .. import aria2 as _a2
            if not _a2.ping():
                return True                  # daemon 离线：不存在任何队列
            return stale_age                 # 心跳超时：无人收账的僵尸
        # python 执行器：寄生线程死了即僵尸；有具名 task 才可救（重建），
        # 无 task 的旧闭包作业跨进程无解（保持不可重试）
        if stale_age:
            meta = json.loads(row["spec_json"] or "{}")
            return bool(meta.get("task"))
        return False
    if row["status"] == "done" and force:
        if row["executor"] == "aria2":
            rebuildable = bool(row["url"] and row["dest"])
        else:
            meta = json.loads(row["spec_json"] or "{}")
            rebuildable = bool(meta.get("task")
                               or _infer_task(meta.get("source")))
        return _DEFAULT_SESSION.spec(row["id"]) is not None or rebuildable
    return False

def _resolve_retry_spec(row) -> JobSpec:
    """取得可执行的 spec：本进程会话直取；否则 aria2 作业从库重建。"""
    job_id = row["id"]
    spec = _DEFAULT_SESSION.spec(job_id)
    if spec is not None:
        return spec
    if row["executor"] == "aria2" and row["url"] and row["dest"]:
        meta = json.loads(row["spec_json"] or "{}")
        spec = JobSpec(source=meta.get("source", "aria2"),
                       params=meta.get("params", {}),
                       executor="aria2", url=row["url"], dest=row["dest"])
        _DEFAULT_SESSION.put(job_id, spec)
        return spec
    meta = json.loads(row["spec_json"] or "{}")
    if row["executor"] == "python":
        task = meta.get("task") or _infer_task(meta.get("source"))
        if task:
            spec = JobSpec(source=meta.get("source", "python"),
                           params=meta.get("params", {}),
                           executor="python", task=task)
            _DEFAULT_SESSION.put(row["id"], spec)
            return spec
    raise RuntimeError(
        f"job {job_id} 的 spec 不在本进程会话且无具名 task/url，"
        "不可跨进程恢复")

def retry(job_id: int, db: DB | None = None, force: bool = True) -> int:
    """重提作业：failed/orphaned/僵尸常规重试；done+force 强制重下。"""
    own = db is None
    db = db or DB().init()
    try:
        row = db.conn.execute(
            "SELECT id, status, spec_json, executor, url, dest, updated_at"
            " FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise LookupError(f"job {job_id} 不存在")
        if not _retry_allowed(row, db, force):
            raise ValueError(f"job {job_id} 状态 {row['status']}，无需 retry")

        spec = _resolve_retry_spec(row)
        key = cache_key(spec.source, spec.params)
        db.conn.execute(
            "UPDATE jobs SET status='queued', error=NULL,"
            " updated_at=datetime('now') WHERE id=?", (job_id,))
        db.conn.commit()
        return _dispatch(db, job_id, spec, key)
    finally:
        if own:
            db.close()

def delete_jobs(job_ids: list[int], db: DB | None = None) -> dict:
    """删除作业记录（过程记录，不动资产：dataset/files 保留）。

    - done 的 job 删除后其 dataset/files 完好（资产账本独立）
    - 健康 active（queued/running 且非僵尸）拒删——先 x 取消或等收账
    返回 {"deleted": [...], "refused": [(id, reason), ...]}
    """
    own = db is None
    db = db or DB().init()
    try:
        deleted, refused = [], []
        for job_id in job_ids:
            row = db.conn.execute(
                "SELECT id, status, executor, updated_at FROM jobs WHERE id=?",
                (job_id,)).fetchone()
            if row is None:
                refused.append((job_id, "不存在"))
                continue
            if row["status"] in ("queued", "running", "verifying") \
                    and not _retry_allowed(row, db, force=False):
                refused.append((job_id, f"活跃中（{row['status']}）"))
                continue
            db.conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
            deleted.append(job_id)
        db.conn.commit()
        return {"deleted": deleted, "refused": refused}
    finally:
        if own:
            db.close()

def retry_batch(batch_id: str, db: DB | None = None) -> dict:
    """整批重试：重提批次内全部 failed/orphaned（僵尸含）。

    返回 {"retried": [...], "skipped": [(id, reason), ...]}。
    典型场景：批量下载失败半批，一键重跑。
    """
    own = db is None
    db = db or DB().init()
    try:
        rows = db.conn.execute(
            "SELECT id, status FROM jobs WHERE batch_id=? ORDER BY id",
            (batch_id,)).fetchall()
        if not rows:
            raise LookupError(f"批次 {batch_id} 不存在")
        retried, skipped = [], []
        for r in rows:
            if r["status"] in ("failed", "orphaned"):
                try:
                    retry(r["id"], db=db)
                    retried.append(r["id"])
                except (ValueError, RuntimeError) as e:
                    skipped.append((r["id"], str(e)[:60]))
            else:
                skipped.append((r["id"], f"状态 {r['status']}，无需重试"))
        return {"retried": retried, "skipped": skipped}
    finally:
        if own:
            db.close()

def find_orphans(after: str = ORPHAN_AFTER, db: DB | None = None) -> int:
    """把心跳超时的 running/verifying 作业标记为 orphaned，返回数量。

    aria2 执行器跳过：其存活由 daemon 与 RPC 判定，不依赖本进程心跳。
    """
    own = db is None
    db = db or DB().init()
    try:
        cur = db.conn.execute(
            "UPDATE jobs SET status='orphaned' WHERE status IN ('running','verifying')"
            " AND executor='python'"
            " AND updated_at < datetime('now', ?)", (f"-{after}",))
        db.conn.commit()
        return cur.rowcount
    finally:
        if own:
            db.close()
