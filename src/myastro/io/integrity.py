"""完整性巡检：sha256 基线 + 全库核对（capabilities §3 完整性校验）。

信任模型：**首次巡检建立基线**（文件存在 + 尺寸一致即记 sha）；
此后巡检用基线 sha 检测静默损坏（bit rot / 传输中断残留 / 误写）。
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from .db import DB


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def audit(db: DB | None = None) -> dict:
    """全库核对。返回报告并回写 sha 基线（首次见到且完好的文件）。

    {"total", "ok", "missing", "size_mismatch", "corrupt", "baselined"}
    corrupt = sha 与基线不符（静默损坏，最严重）。
    """
    own = db is None
    db = db or DB().init()
    try:
        rows = db.conn.execute(
            "SELECT f.id, f.path, f.size, f.sha256 FROM files f").fetchall()
        report = {"total": len(rows), "ok": 0, "missing": 0,
                  "size_mismatch": 0, "corrupt": 0, "baselined": 0,
                  # 账本说"有"但没有文件的数据集（空结果 empty=true 除外）——
                  # 真实事故：取数成功却未落盘/未登记（#39/#27），audit 必须能发现
                  "unlinked": db.conn.execute(
                      "SELECT count(*) FROM datasets d"
                      " LEFT JOIN files f ON f.dataset_id = d.id"
                      " WHERE f.id IS NULL"
                      " AND COALESCE(json_extract(d.meta_json, '$.empty'), 0) = 0"
                  ).fetchone()[0]}
        for r in rows:
            p = Path(r["path"])
            if not p.exists():
                report["missing"] += 1
                continue
            actual_size = p.stat().st_size
            if r["size"] is not None and actual_size != r["size"]:
                report["size_mismatch"] += 1
                continue
            sha = _sha256(p)
            if r["sha256"]:
                if sha != r["sha256"]:
                    report["corrupt"] += 1
                else:
                    report["ok"] += 1
            else:                       # 首次：建基线
                db.conn.execute("UPDATE files SET sha256=? WHERE id=?",
                                (sha, r["id"]))
                report["baselined"] += 1
        db.conn.commit()
        return report
    finally:
        if own:
            db.close()


def audit_detail(kind: str, limit: int = 50) -> list[dict]:
    """问题明细（missing/size_mismatch/corrupt 的具体文件 + unlinked 的数据集）。

    corrupt 需先有基线。
    """
    db = DB().init()
    out = []
    if kind == "unlinked":
        for r in db.conn.execute(
                "SELECT d.id, d.source, d.target, d.params_json FROM datasets d"
                " LEFT JOIN files f ON f.dataset_id = d.id"
                " WHERE f.id IS NULL"
                " AND COALESCE(json_extract(d.meta_json, '$.empty'), 0) = 0"
                " LIMIT ?", (limit,)):
            out.append({"dataset_id": r["id"], "source": r["source"],
                        "target": r["target"], "params": r["params_json"],
                        "why": "数据集无任何文件登记"})
        db.close()
        return out
    for r in db.conn.execute(
            "SELECT f.id, f.path, f.size, f.sha256 FROM files f").fetchall():
        p = Path(r["path"])
        if not p.exists():
            if kind == "missing":
                out.append({"path": r["path"], "why": "文件不在盘"})
            continue
        actual = p.stat().st_size
        if r["size"] is not None and actual != r["size"]:
            if kind == "size_mismatch":
                out.append({"path": r["path"],
                            "why": f"库 {r['size']}B ≠ 盘 {actual}B"})
            continue
        if kind == "corrupt" and r["sha256"] and _sha256(p) != r["sha256"]:
            out.append({"path": r["path"], "why": "sha256 与基线不符"})
        if len(out) >= limit:
            break
    db.close()
    return out
