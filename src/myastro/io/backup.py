"""账本备份与恢复（`myastro backup` / `myastro restore`）。

为什么这是发布前必须有的：**账本是这个工具最不可再生的资产**——FITS/parquet
可以重下，但"取过什么、用什么参数、sha 基线"只存在于 astro.db。数据根丢了还能
重取，账本丢了等于全部重来。

设计要点：
- 备份用 SQLite 自带的在线备份 API（`Connection.backup`），不用 `cp`：
  后者在 WAL 模式下可能拷到不一致的快照。
- 恢复**默认拒绝**覆盖已有账本；`--force` 时先留一份安全副本，并清理
  `-wal`/`-shm`（否则 SQLite 可能与旧 WAL 错配）。
- 恢复前校验来源确实是 myastro 账本（有 datasets/files/jobs 表且 schema 不超前）。
- 索引（parquet，可能上百 MB）默认不备份，可用 with_index 一并复制。
"""
from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .config import Config
from .db import DB, SCHEMA_VERSION

TABLES = ("datasets", "files", "jobs")


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _row_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("datasets", "files", "jobs", "health")}


def create(out_dir: Path | str | None = None, *, with_index: bool = False,
           cfg: Config | None = None) -> dict:
    """做一份账本备份，返回 {dir, db, manifest, bytes, with_index}。"""
    cfg = cfg or Config()
    if not cfg.db.exists():
        raise ValueError(f"账本不存在，无可备份：{cfg.db}")
    target = Path(out_dir) if out_dir else cfg.db.parent / "backups" / \
        f"myastro-{_stamp()}"
    target.mkdir(parents=True, exist_ok=True)

    live = sqlite3.connect(cfg.db)
    try:
        counts = _row_counts(live)
        version = live.execute("PRAGMA user_version").fetchone()[0]
        dest_path = target / "astro.db"
        dest = sqlite3.connect(dest_path)
        try:
            live.backup(dest)          # 在线备份：WAL 下也能拿到一致快照
        finally:
            dest.close()
    finally:
        live.close()

    manifest = {
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source_db": str(cfg.db),
        "data_root": str(cfg.data),
        "schema_version": version,
        "counts": counts,
        "with_index": bool(with_index),
        "indexes": [],
    }
    if with_index:
        from . import index as idx

        idx_dir = target / "index"
        idx_dir.mkdir(exist_ok=True)
        for name in idx.INDEXES:
            src = idx.index_path(name)
            if src.exists():
                shutil.copy2(src, idx_dir / src.name)
                manifest["indexes"].append(
                    {"name": name, "file": src.name, "bytes": src.stat().st_size})
    (target / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2))
    return {"dir": str(target), "db": str(target / "astro.db"),
            "manifest": str(target / "manifest.json"),
            "bytes": (target / "astro.db").stat().st_size,
            "with_index": bool(with_index)}


def _resolve_source(source: Path | str) -> Path:
    p = Path(source)
    if p.is_dir():
        p = p / "astro.db"
    if not p.exists():
        raise ValueError(f"备份里没有 astro.db：{p}")
    return p


def _validate(path: Path) -> int:
    """确认这是 myastro 账本；返回 schema 版本。"""
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.close()
    except sqlite3.Error as e:
        raise ValueError(f"不是有效的 SQLite 文件：{path}（{e}）") from e
    missing = set(TABLES) - names
    if missing:
        raise ValueError(f"不是 myastro 账本（缺表 {sorted(missing)}）：{path}")
    if version > SCHEMA_VERSION:
        raise ValueError(
            f"备份 schema {version} 比当前代码 {SCHEMA_VERSION} 新，请先升级 myastro")
    return version


def restore(source: Path | str, *, force: bool = False,
            cfg: Config | None = None) -> dict:
    """从备份恢复账本内容。

    实现要点（都是踩过的坑）：
    - **不使用文件复制**：`cp` 一个 WAL 模式的库会丢 `-wal` 里的数据；删除
      `-wal`/`-shm` 又会在"另有连接打开"时让后续打开报 `disk I/O error`
      （TUI 正在跑、或调用方持有句柄时就会发生）。改用 SQLite 的备份 API
      **就地覆盖内容**，由 SQLite 自己处理锁与 WAL。
    - 覆盖前留安全副本也用备份 API（同样为了 WAL 安全）。
    - 恢复后再跑一次迁移：备份可能是旧 schema。
    """
    cfg = cfg or Config()
    src_path = _resolve_source(source)
    version = _validate(src_path)

    cfg.db.parent.mkdir(parents=True, exist_ok=True)
    existed = cfg.db.exists()
    if existed and not force:
        raise ValueError(
            f"账本已存在：{cfg.db}（用 force=True / --force 覆盖，"
            "覆盖前会自动留存一份 .pre-restore-*.bak）")

    safety: Path | None = None
    dest = DB(cfg.db).init()                    # 打开即迁移到当前 schema
    try:
        if existed:
            safety = cfg.db.with_name(
                f"{cfg.db.name}.pre-restore-{_stamp()}.bak")
            safety_conn = sqlite3.connect(safety)
            try:
                dest.conn.backup(safety_conn)   # 先保住覆盖前的内容
            finally:
                safety_conn.close()
        src_conn = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
        try:
            src_conn.backup(dest.conn)          # 就地覆盖（不碰文件/WAL）
        finally:
            src_conn.close()
    finally:
        dest.close()

    probe = DB(cfg.db).init()                   # 恢复的内容可能是旧 schema
    counts = _row_counts(probe.conn)
    probe.close()
    return {"restored_from": str(src_path), "db": str(cfg.db),
            "safety_copy": str(safety) if safety else None,
            "schema_version": version, "counts": counts}
