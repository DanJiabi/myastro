"""路径与配置管理。"""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_DATA = Path.home() / "myastro-data"
DEFAULT_DB = Path.home() / ".local" / "state" / "myastro" / "astro.db"


class Config:
    """数据根目录与元数据库路径。

    环境变量：MYASTRO_DATA（数据根，默认 ~/myastro-data）、
    MYASTRO_DB（SQLite 路径，默认 ~/.local/state/myastro/astro.db）。
    数据根可以放在网络盘（如 NAS）；**账本必须在本地磁盘**（见下）。
    astro.db 必须在本地文件系统上（SQLite 锁/WAL 与 NFS 不兼容，见设计文档 §4）。
    """

    def __init__(self, data: str | os.PathLike | None = None,
                 db: str | os.PathLike | None = None):
        self.data = Path(data or os.environ.get("MYASTRO_DATA", DEFAULT_DATA))
        self.db = Path(db or os.environ.get("MYASTRO_DB", DEFAULT_DB))
        self.cache = self.data / "cache"

    def init(self) -> None:
        """创建目录结构（幂等）。"""
        self.data.mkdir(parents=True, exist_ok=True)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.db.parent.mkdir(parents=True, exist_ok=True)

    def source_dir(self, source: str) -> Path:
        """某数据源的资产目录：data/<source>/。"""
        return self.data / source
