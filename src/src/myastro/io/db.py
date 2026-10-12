"""SQLite 元数据库：datasets / files / jobs 三表 + user_version 迁移。

路径必须在本地文件系统（NFS 上 SQLite 锁/WAL 不可靠，见设计文档 §4）。
"""
from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path
from typing import Self

from .config import Config

SCHEMA_VERSION = 8

_MIGRATIONS: dict[int, tuple[str, ...]] = {
    1: (
        "CREATE TABLE IF NOT EXISTS datasets (\n        id          INTEGER PRIMARY KEY,\n        source      TEXT NOT NULL,\n        target      TEXT,\n        params_json TEXT NOT NULL,\n        cache_key   TEXT NOT NULL UNIQUE,\n        created_at  TEXT NOT NULL DEFAULT (datetime('now')),\n        status      TEXT NOT NULL DEFAULT 'ok'\n    )",
        'CREATE INDEX IF NOT EXISTS idx_datasets_source ON datasets(source)',
        "CREATE TABLE IF NOT EXISTS files (\n        id          INTEGER PRIMARY KEY,\n        dataset_id  INTEGER NOT NULL REFERENCES datasets(id),\n        path        TEXT NOT NULL UNIQUE,\n        size        INTEGER NOT NULL DEFAULT 0,\n        sha256      TEXT,\n        remote_url  TEXT,\n        fetched_at  TEXT NOT NULL DEFAULT (datetime('now')),\n        format      TEXT\n    )",
        'CREATE INDEX IF NOT EXISTS idx_files_dataset ON files(dataset_id)',
        "CREATE TABLE IF NOT EXISTS jobs (\n        id            INTEGER PRIMARY KEY,\n        spec_json     TEXT NOT NULL,\n        executor      TEXT NOT NULL CHECK (executor IN ('python', 'aria2')),\n        url           TEXT,\n        dest          TEXT,\n        status        TEXT NOT NULL DEFAULT 'queued'\n                      CHECK (status IN ('queued','running','verifying',\n                                        'done','failed','orphaned')),\n        progress      REAL,\n        speed         REAL,\n        error         TEXT,\n        updated_at    TEXT NOT NULL DEFAULT (datetime('now')),\n        started_at    TEXT,\n        finished_at   TEXT,\n        file_id       INTEGER REFERENCES files(id)\n    )",
        'CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)',
    ),
    2: (
        'ALTER TABLE jobs ADD COLUMN dataset_id INTEGER REFERENCES datasets(id)',
        'CREATE INDEX IF NOT EXISTS idx_jobs_dataset ON jobs(dataset_id)',
    ),
    3: (
        'ALTER TABLE jobs ADD COLUMN gid TEXT',
    ),
    4: (
        'ALTER TABLE jobs ADD COLUMN batch_id TEXT',
        'CREATE INDEX IF NOT EXISTS idx_jobs_batch ON jobs(batch_id)',
    ),
    5: (
        'CREATE TABLE IF NOT EXISTS health (\n        source     TEXT PRIMARY KEY,\n        status     TEXT NOT NULL,\n        detail     TEXT,\n        checked_at TEXT NOT NULL\n    )',
    ),
    6: (
        'ALTER TABLE datasets ADD COLUMN meta_json TEXT',
    ),
    7: (
        'ALTER TABLE jobs ADD COLUMN error_type TEXT',
    ),
    8: (
        'ALTER TABLE datasets ADD COLUMN ra REAL',
        'ALTER TABLE datasets ADD COLUMN dec REAL',
        'CREATE INDEX IF NOT EXISTS idx_datasets_pos ON datasets(ra, dec)',
    ),
}


# WAL 开启的重试预算：journal_mode 变更不走 busy handler，只能自己重试。
WAL_ENABLE_RETRIES = 60          # × 50ms ≈ 最多等 3s
WAL_ENABLE_BACKOFF = 0.05

# ADD COLUMN 语句（用于幂等判断：并发或中断后可能"列已存在但版本号落后"）
_ADD_COLUMN_RE = re.compile(r"^\s*ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+(\w+)",
                            re.IGNORECASE)


def _add_column_already_applied(conn: sqlite3.Connection, stmt: str) -> bool:
    m = _ADD_COLUMN_RE.match(stmt)
    if not m:
        return False
    table, column = m.group(1), m.group(2)
    return column in {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


class DB:
    """连接管理与迁移。用法：db = DB(); db.init(); db.conn.execute(...)。"""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else Config().db
        self.conn: sqlite3.Connection | None = None

    def init(self) -> DB:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout=30000")     # 先立规矩，再做别的
        self._enable_wal()
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()
        return self

    def _enable_wal(self) -> None:
        """开启 WAL（设置写入库头后持久生效）：**先查再改**，改动失败则短重试。

        为什么不能只写一句 `PRAGMA journal_mode=WAL`：journal_mode 变更**不经过
        busy handler**——实测另一个连接持锁时，即使 `timeout=5s` 也立刻抛
        `database is locked`。并发打开同一个新库时必然有一个进程撞上它：
        CI（ubuntu）三个矩阵项正是这样红的，而 macOS 本地 18/18 全过，
        因为两个平台的加锁时序不同。
        正常情况下库已是 wal，"查"就命中，根本不会走到改动分支。
        """
        assert self.conn is not None
        for attempt in range(WAL_ENABLE_RETRIES):
            mode = self.conn.execute("PRAGMA journal_mode").fetchone()[0]
            if str(mode).lower() == "wal":
                return
            try:
                self.conn.execute("PRAGMA journal_mode=WAL")
                return
            except sqlite3.OperationalError:
                if attempt == WAL_ENABLE_RETRIES - 1:
                    raise
                time.sleep(WAL_ENABLE_BACKOFF)

    def _migrate(self) -> None:
        """应用迁移：**并发安全 + 幂等**，可自愈"半迁移"状态。

        两道保险（0.3.2 修，事故见 CHANGELOG）：
        1. **串行化**：`BEGIN IMMEDIATE` 拿写锁后再读版本、执行 DDL，并在锁内重读一次。
           两个进程同时 `myastro init`（或 TUI 与 CLI 并发）不会再各自跑一遍 ALTER。
           注意**不能用 `executescript`**：它会隐式提交，锁随即丢失——那正是原实现
           在并发下报 `duplicate column name` 的原因。因此迁移以单条语句存储。
        2. **幂等**：`ALTER TABLE ... ADD COLUMN` 前先查 `table_info`，已存在就跳过。
           这样"版本号落后但列已存在"的残局能自动修好，而不是永久卡死
           （用户实测：一旦卡住，之后每个命令都报同一个 duplicate column 错误）。
        """
        assert self.conn is not None
        conn = self.conn
        conn.execute("PRAGMA busy_timeout=10000")      # 等锁而不是立刻失败
        if conn.execute("PRAGMA user_version").fetchone()[0] >= SCHEMA_VERSION:
            return
        conn.execute("BEGIN IMMEDIATE")
        try:
            current = conn.execute("PRAGMA user_version").fetchone()[0]
            for version in sorted(_MIGRATIONS):
                if version <= current:
                    continue
                for stmt in _MIGRATIONS[version]:
                    if _add_column_already_applied(conn, stmt):
                        continue                            # 幂等：列已存在
                    conn.execute(stmt)
                conn.execute(f"PRAGMA user_version={version}")
            conn.commit()
        except BaseException:
            conn.rollback()
            raise

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def __enter__(self) -> Self:
        return self if self.conn else self.init()

    def __exit__(self, *exc) -> None:
        self.close()
