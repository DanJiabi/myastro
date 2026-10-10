"""账本备份与恢复（`manage.backup`）：账本不可再生，这是它唯一的保险。"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from myastro.io import backup as bk
from myastro.io.config import Config
from myastro.io.db import DB


def _seed(n: int = 5) -> None:
    db = DB().init()
    for i in range(n):
        db.conn.execute(
            "INSERT INTO datasets(source,target,params_json,cache_key)"
            f" VALUES('s','t{i}','{{}}','k{i}')")
    db.conn.commit()
    db.close()


def _count() -> int:
    conn = sqlite3.connect(Config().db)
    try:
        return conn.execute("SELECT COUNT(*) FROM datasets").fetchone()[0]
    finally:
        conn.close()


@pytest.mark.cap("manage.backup")
class TestBackupRestore:
    def test_round_trip(self, env, tmp_path):
        _seed(5)
        out = bk.create(tmp_path / "bk")
        assert Path(out["db"]).is_file()
        manifest = json.loads(Path(out["manifest"]).read_text())
        assert manifest["counts"]["datasets"] == 5
        assert manifest["schema_version"] >= 1
        assert manifest["data_root"] == str(Config().data)

        conn = sqlite3.connect(Config().db)          # 破坏现有账本
        conn.execute("DELETE FROM datasets")
        conn.commit()
        conn.close()
        assert _count() == 0

        res = bk.restore(out["dir"], force=True)
        assert _count() == 5
        assert res["counts"]["datasets"] == 5
        assert Path(res["safety_copy"]).is_file()    # 覆盖前留了安全副本

    def test_refuses_to_overwrite_without_force(self, env, tmp_path):
        _seed(1)
        out = bk.create(tmp_path / "bk")
        with pytest.raises(ValueError, match="已存在"):
            bk.restore(out["dir"])
        assert _count() == 1                        # 未被改动

    def test_restore_accepts_db_file_path(self, env, tmp_path):
        _seed(2)
        out = bk.create(tmp_path / "bk")
        conn = sqlite3.connect(Config().db)
        conn.execute("DELETE FROM datasets")
        conn.commit()
        conn.close()
        bk.restore(out["db"], force=True)           # 直接给 astro.db 路径
        assert _count() == 2

    def test_rejects_non_myastro_database(self, env, tmp_path):
        fake = tmp_path / "fake.db"
        conn = sqlite3.connect(fake)
        conn.execute("CREATE TABLE t(x)")
        conn.commit()
        conn.close()
        with pytest.raises(ValueError, match="不是 myastro 账本"):
            bk.restore(fake, force=True)

    def test_rejects_future_schema(self, env, tmp_path):
        _seed(1)
        out = bk.create(tmp_path / "bk")
        conn = sqlite3.connect(out["db"])
        conn.execute("PRAGMA user_version=99")
        conn.commit()
        conn.close()
        with pytest.raises(ValueError, match="先升级 myastro"):
            bk.restore(out["dir"], force=True)

    def test_missing_ledger_is_a_clear_error(self, env, tmp_path):
        """env 夹具会自动建库，所以这里显式指向一个不存在的路径。"""
        cfg = Config(db=tmp_path / "nope" / "astro.db")
        with pytest.raises(ValueError, match="账本不存在"):
            bk.create(tmp_path / "bk", cfg=cfg)

    def test_restore_while_another_connection_is_open(self, env, tmp_path):
        """另有连接持有账本时也必须能恢复（TUI 在跑的场景）。

        教训：早期实现用 `shutil.copy2` + 删 `-wal`/`-shm`，在第二个连接
        仍打开时会报 `disk I/O error`。现在用 SQLite 备份 API 就地覆盖内容。
        """
        _seed(4)
        out = bk.create(tmp_path / "bk")
        holder = sqlite3.connect(Config().db)        # 模拟 TUI / 其它句柄
        try:
            holder.execute("DELETE FROM datasets")
            holder.commit()
            res = bk.restore(out["dir"], force=True)
            assert res["counts"]["datasets"] == 4
            # 就地覆盖：持有连接也立刻看到恢复后的内容
            assert holder.execute(
                "SELECT COUNT(*) FROM datasets").fetchone()[0] == 4
        finally:
            holder.close()

    def test_safety_copy_holds_pre_restore_state(self, env, tmp_path):
        """安全副本必须是"覆盖前"的内容（WAL 下用 copy2 做不到这点）。"""
        _seed(3)
        out = bk.create(tmp_path / "bk")
        conn = sqlite3.connect(Config().db)
        conn.execute("DELETE FROM datasets")
        conn.commit()
        conn.close()
        res = bk.restore(out["dir"], force=True)
        safety = sqlite3.connect(f"file:{res['safety_copy']}?mode=ro", uri=True)
        try:
            assert safety.execute(
                "SELECT COUNT(*) FROM datasets").fetchone()[0] == 0
        finally:
            safety.close()
        assert _count() == 3

    def test_with_index_copies_built_indexes(self, env, tmp_path):
        import pandas as pd

        from myastro.io import index as idx

        _seed(1)
        pd.DataFrame({"brickname": ["0001m002"], "ra": [0.1], "dec": [-0.2]}).to_parquet(
            idx.index_path("legacy-bricks"), index=False)
        out = bk.create(tmp_path / "bk", with_index=True)
        manifest = json.loads(Path(out["manifest"]).read_text())
        assert manifest["indexes"] and manifest["indexes"][0]["name"] == "legacy-bricks"
        assert (tmp_path / "bk" / "index" / "legacy-bricks.parquet").is_file()

    def test_backup_is_consistent_snapshot(self, env, tmp_path):
        """在线备份：备份文件本身是可独立打开的完整账本。"""
        _seed(3)
        out = bk.create(tmp_path / "bk")
        conn = sqlite3.connect(f"file:{out['db']}?mode=ro", uri=True)
        try:
            assert conn.execute("SELECT COUNT(*) FROM datasets").fetchone()[0] == 3
            assert {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")} >= \
                {"datasets", "files", "jobs"}
        finally:
            conn.close()


@pytest.mark.cap("manage.backup")
def test_facade_exports_round_trip(env, tmp_path):
    """门面导出（init_root / backup / restore）的端到端契约。

    造数据必须用账本，所以这条放在内核层；门面层只放无副作用的契约测试
    （门面测试不允许 import 内核，见 tests/guards/test_capability_map.py）。
    """
    import myastro as ma

    paths = ma.init_root()
    assert {"data", "db", "cache"} <= set(paths)

    db = DB().init()
    db.conn.execute("INSERT INTO datasets(source,target,params_json,cache_key)"
                    " VALUES('s','t','{}','k')")
    db.conn.commit()
    db.close()

    out = ma.backup(tmp_path / "bk")
    assert Path(out["db"]).is_file()

    conn = DB().init()
    conn.conn.execute("DELETE FROM datasets")
    conn.conn.commit()
    conn.close()

    res = ma.restore(out["dir"], force=True)
    assert res["counts"]["datasets"] == 1
    assert _count() == 1
