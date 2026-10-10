"""SQLite 元数据库：datasets / files / jobs 三表 + user_version 迁移。

路径必须在本地文件系统（NFS 上 SQLite 锁/WAL 不可靠，见设计文档 §4）。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Self

from .config import Config

SCHEMA_VERSION = 8

_MIGRATIONS: dict[int, str] = {
    1: """
    CREATE TABLE IF NOT EXISTS datasets (
        id          INTEGER PRIMARY KEY,
        source      TEXT NOT NULL,
        target      TEXT,
        params_json TEXT NOT NULL,
        cache_key   TEXT NOT NULL UNIQUE,
        created_at  TEXT NOT NULL DEFAULT (datetime('now')),
        status      TEXT NOT NULL DEFAULT 'ok'
    );
    CREATE INDEX IF NOT EXISTS idx_datasets_source ON datasets(source);

    CREATE TABLE IF NOT EXISTS files (
        id          INTEGER PRIMARY KEY,
        dataset_id  INTEGER NOT NULL REFERENCES datasets(id),
        path        TEXT NOT NULL UNIQUE,
        size        INTEGER NOT NULL DEFAULT 0,
        sha256      TEXT,
        remote_url  TEXT,
        fetched_at  TEXT NOT NULL DEFAULT (datetime('now')),
        format      TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_files_dataset ON files(dataset_id);

    CREATE TABLE IF NOT EXISTS jobs (
        id            INTEGER PRIMARY KEY,
        spec_json     TEXT NOT NULL,
        executor      TEXT NOT NULL CHECK (executor IN ('python', 'aria2')),
        url           TEXT,
        dest          TEXT,
        status        TEXT NOT NULL DEFAULT 'queued'
                      CHECK (status IN ('queued','running','verifying',
                                        'done','failed','orphaned')),
        progress      REAL,
        speed         REAL,
        error         TEXT,
        updated_at    TEXT NOT NULL DEFAULT (datetime('now')),
        started_at    TEXT,
        finished_at   TEXT,
        file_id       INTEGER REFERENCES files(id)
    );
    CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
    """,
    2: """
    ALTER TABLE jobs ADD COLUMN dataset_id INTEGER REFERENCES datasets(id);
    CREATE INDEX IF NOT EXISTS idx_jobs_dataset ON jobs(dataset_id);
    """,
    3: """
    ALTER TABLE jobs ADD COLUMN gid TEXT;
    """,
    4: """
    ALTER TABLE jobs ADD COLUMN batch_id TEXT;
    CREATE INDEX IF NOT EXISTS idx_jobs_batch ON jobs(batch_id);
    """,
    5: """
    CREATE TABLE IF NOT EXISTS health (
        source     TEXT PRIMARY KEY,
        status     TEXT NOT NULL,
        detail     TEXT,
        checked_at TEXT NOT NULL
    );
    """,
    6: """
    ALTER TABLE datasets ADD COLUMN meta_json TEXT;
    """,
    7: """
    ALTER TABLE jobs ADD COLUMN error_type TEXT;
    """,
    8: """
    ALTER TABLE datasets ADD COLUMN ra REAL;
    ALTER TABLE datasets ADD COLUMN dec REAL;
    CREATE INDEX IF NOT EXISTS idx_datasets_pos ON datasets(ra, dec);
    """,
}


class DB:
    """连接管理与迁移。用法：db = DB(); db.init(); db.conn.execute(...)。"""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else Config().db
        self.conn: sqlite3.Connection | None = None

    def init(self) -> DB:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()
        return self

    def _migrate(self) -> None:
        assert self.conn is not None
        current = self.conn.execute("PRAGMA user_version").fetchone()[0]
        for version in sorted(_MIGRATIONS):
            if version > current:
                self.conn.executescript(_MIGRATIONS[version])
                self.conn.execute(f"PRAGMA user_version={version}")
                self.conn.commit()

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def __enter__(self) -> Self:
        return self if self.conn else self.init()

    def __exit__(self, *exc) -> None:
        self.close()
