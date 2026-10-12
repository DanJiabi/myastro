"""aria2 执行器：提交、轮询、收账（终态回写库）。

库为准、RPC 为饰：活动下载的实时进度只用于显示，不回写 DB；
终态（complete/error）必须收账，且任何观察者（TUI 刷新）都会触发。
"""
from __future__ import annotations

from pathlib import Path

from ..core import cache_key
from ..db import DB
from .rebuild import _rebuild_spec
from .spec import FetchResult, JobSpec
from .store import _register_success


def _start_aria2_job(db: DB, job_id: int, spec: JobSpec, key: str) -> None:
    from .. import aria2
    from ..config import Config
    cfg = Config()
    aria2.ensure_daemon(cfg.data)
    dest = Path(spec.dest)
    gid = aria2.add_uri(spec.url, dest.parent, dest.name)
    db.conn.execute(
        "UPDATE jobs SET status='running', gid=?, started_at=datetime('now'),"
        " updated_at=datetime('now') WHERE id=?", (gid, job_id))
    db.conn.commit()

def _finalize_aria2(db: DB, job_id: int, spec: JobSpec, key: str,
                    s: dict) -> tuple[str, FetchResult | None]:
    """RPC 终态 → 入库（wait 与 reconcile 的唯一收账实现）。

    返回 ("done", result) / ("failed", None) / ("active", None)。
    active 不写库（观察行为不制造写放大）。
    """
    if s["status"] == "complete":
        dest = Path(spec.dest)
        if not dest.exists():
            db.conn.execute(
                "UPDATE jobs SET status='failed',"
                " error='aria2 完成但文件缺失',"
                " finished_at=datetime('now'),"
                " updated_at=datetime('now') WHERE id=?", (job_id,))
            db.conn.commit()
            return "failed", None
        result = FetchResult(paths=[dest], dataset_id=-1)
        dataset_id = _register_success(db, spec, key, job_id, result)
        db.conn.execute(
            "UPDATE jobs SET status='done', finished_at=datetime('now'),"
            " dataset_id=?, updated_at=datetime('now') WHERE id=?",
            (dataset_id, job_id))
        db.conn.commit()
        return "done", FetchResult(paths=result.paths, dataset_id=dataset_id)
    if s["status"] in ("error", "removed"):
        msg = (f"aria2 {s['status']} {s['errorCode']}:"
               f" {s['errorMessage']}")
        db.conn.execute(
            "UPDATE jobs SET status='failed', error=?,"
            " finished_at=datetime('now'), updated_at=datetime('now')"
            " WHERE id=?",
            (msg, job_id))
        db.conn.commit()
        return "failed", None
    return "active", None

def _poll_aria2(db: DB, job_id: int, spec: JobSpec, key: str) -> FetchResult | None:
    """wait 路径：查一次 RPC，终态收账；失败抛异常（调用方语义）。"""
    from .. import aria2
    row = db.conn.execute(
        "SELECT gid FROM jobs WHERE id=?", (job_id,)).fetchone()
    s = aria2.status(row["gid"])
    if s["status"] == "active":
        db.conn.execute(
            "UPDATE jobs SET progress=?, updated_at=datetime('now')"
            " WHERE id=?",
            (float(s["completedLength"])
             / max(float(s["totalLength"]), 1) * 100, job_id))
        db.conn.commit()
        return None
    outcome, result = _finalize_aria2(db, job_id, spec, key, s)
    if outcome == "failed":
        raise RuntimeError(f"job {job_id} aria2 失败（详见 jobs.error）")
    return result

def reconcile_aria2(db: DB | None = None) -> int:
    """对 running/queued 的 aria2 作业查 RPC 终态并收账（done/failed）。

    背景：收账（wait/_poll_aria2）原本只属于提交进程；进程死后作业停在
    running。观察者（top 每 2s 刷新）定期调用本函数即可闭环。
    活动下载不写库（避免观察行为制造写放大），只处理终态。
    返回收账数量。
    """
    db = db or DB().init()
    rows = db.conn.execute(
        "SELECT id, status, gid, spec_json, url, dest FROM jobs"
        " WHERE executor='aria2' AND status IN ('queued','running')"
        " AND gid IS NOT NULL").fetchall()
    if not rows:
        return 0
    from .. import aria2
    if not aria2.ping():
        return 0
    n = 0
    for r in rows:
        try:
            s = aria2.status(r["gid"])
        except Exception:              # noqa: BLE001, S112 — 单条查询失败
            continue                   # 不影响其余作业的收账
        spec = _rebuild_spec(r)
        key = cache_key(spec.source, spec.params)
        outcome, _ = _finalize_aria2(db, r["id"], spec, key, s)
        if outcome != "active":
            n += 1
    return n
