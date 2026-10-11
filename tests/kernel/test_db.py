"""内核：真 sqlite（tmp），网络打桩；账本/作业/索引/健康/调度/巡检/检索。

（测试分层重组迁移；断言未改动。）
"""

import sqlite3

import pytest

from myastro.io.config import Config
from myastro.io.db import DB, SCHEMA_VERSION


@pytest.fixture
def db(tmp_path) -> DB:
    return DB(tmp_path / "astro.db").init()


class TestConfig:
    @pytest.mark.cap("manage.ledger")
    def test_env_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MYASTRO_DATA", str(tmp_path / "data"))
        monkeypatch.setenv("MYASTRO_DB", str(tmp_path / "astro.db"))
        cfg = Config()
        assert cfg.data == tmp_path / "data"
        assert cfg.db == tmp_path / "astro.db"

    @pytest.mark.cap("manage.ledger")
    def test_init_idempotent(self, tmp_path):
        cfg = Config(data=tmp_path / "d", db=tmp_path / "d" / "astro.db")
        cfg.init()
        cfg.init()
        assert (tmp_path / "d" / "cache").is_dir()

    @pytest.mark.cap("manage.ledger")
    def test_source_dir(self, tmp_path):
        cfg = Config(data=tmp_path)
        assert cfg.source_dir("tess") == tmp_path / "tess"


class TestDB:
    @pytest.mark.cap("manage.ledger")
    def test_migration_sets_user_version(self, db):
        assert db.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION

    @pytest.mark.cap("manage.ledger")
    def test_fresh_schema_covers_all_code_columns(self, db):
        """新建库（空文件跑完全部迁移）必须含代码用到的所有列。

        真实需求：迁路径与建表路径曾经分叉——把新列直接写进 v1 建表语句，
        新库再跑 ALTER 就 duplicate column（真事故）。此测试锁住"新库 == 老库升级"。
        """
        expected = {
            "datasets": {
                "id",
                "source",
                "target",
                "params_json",
                "cache_key",
                "created_at",
                "status",
                "meta_json",
            },
            "files": {
                "id",
                "dataset_id",
                "path",
                "size",
                "sha256",
                "remote_url",
                "fetched_at",
                "format",
            },
            "jobs": {
                "id",
                "spec_json",
                "executor",
                "url",
                "dest",
                "status",
                "progress",
                "speed",
                "error",
                "updated_at",
                "started_at",
                "finished_at",
                "file_id",
                "dataset_id",
                "gid",
                "batch_id",
                "error_type",
            },
            "health": {"source", "status", "detail", "checked_at"},
        }
        for table, cols in expected.items():
            actual = {r["name"] for r in db.conn.execute(f"PRAGMA table_info({table})")}
            assert cols <= actual, f"{table} 缺列: {cols - actual}"

    @pytest.mark.cap("manage.ledger")
    def test_reinit_idempotent(self, tmp_path):
        """重复 init 不得重复应用迁移（否则新库/升级库会分叉）。"""
        from myastro.io.db import SCHEMA_VERSION

        first = DB(tmp_path / "a.db").init()
        tables_before = sorted(
            r[0] for r in first.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"))
        version_before = first.conn.execute("PRAGMA user_version").fetchone()[0]
        first.close()

        second = DB(tmp_path / "a.db").init()      # 不应抛错，也不应改变结构
        tables_after = sorted(
            r[0] for r in second.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"))
        assert second.conn.execute("PRAGMA user_version").fetchone()[0] == \
            version_before == SCHEMA_VERSION
        assert tables_after == tables_before
        assert {"datasets", "files", "jobs", "health"} <= set(tables_after)
        second.close()

    @pytest.mark.cap("manage.ledger")
    def test_wal_mode(self, db):
        mode = db.conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"

    @pytest.mark.cap("manage.ledger")
    def test_roundtrip_dataset_file(self, db):
        cur = db.conn.execute(
            "INSERT INTO datasets(source, target, params_json, cache_key)"
            " VALUES('tess','WASP-12','{}','k1')"
        )
        ds_id = cur.lastrowid
        db.conn.execute(
            "INSERT INTO files(dataset_id, path, size, format)"
            " VALUES(?, 'data/tess/WASP-12/lc.parquet', 1024, 'parquet')",
            (ds_id,),
        )
        db.conn.commit()
        row = db.conn.execute(
            "SELECT f.path, d.source FROM files f"
            " JOIN datasets d ON d.id = f.dataset_id WHERE d.cache_key='k1'"
        ).fetchone()
        assert row["path"].endswith("lc.parquet")
        assert row["source"] == "tess"

    @pytest.mark.cap("manage.ledger")
    def test_job_executor_check_constraint(self, db):
        with pytest.raises(sqlite3.IntegrityError):
            db.conn.execute("INSERT INTO jobs(spec_json, executor) VALUES('{}','ftp')")

    @pytest.mark.cap("manage.ledger")
    def test_job_status_check_constraint(self, db):
        with pytest.raises(sqlite3.IntegrityError):
            db.conn.execute(
                "INSERT INTO jobs(spec_json, executor, status)"
                " VALUES('{}','python','weird')"
            )

    @pytest.mark.cap("manage.ledger")
    def test_context_manager(self, tmp_path):
        with DB(tmp_path / "b.db") as db:
            assert db.conn is not None
        assert db.conn is None


@pytest.mark.cap("manage.ledger")
class TestConnectionLifecycle:
    """自建连接必须被关闭（长驻进程里靠 GC 回收会短时堆积连接）。"""

    def _spy(self, monkeypatch):
        from myastro.io.db import DB
        closed = []
        real = DB.close

        def spy(self):
            closed.append(id(self))
            return real(self)

        monkeypatch.setattr(DB, "close", spy)
        return closed

    def test_status_closes_own_connection(self, env, monkeypatch):
        closed = self._spy(monkeypatch)
        from myastro.io.jobs import status
        status()
        assert closed, "status 自建的连接未关闭"

    def test_audit_closes_own_connection(self, env, monkeypatch):
        closed = self._spy(monkeypatch)
        from myastro.io.integrity import audit
        audit()
        assert closed, "audit 自建的连接未关闭"

    def test_shared_handle_is_not_closed(self, env, monkeypatch):
        """调用方传入的连接不归函数管——不能被它关掉。"""
        from myastro.io.db import DB
        from myastro.io.jobs import status
        db = DB().init()
        status(db=db)
        assert db.conn is not None
        assert db.conn.execute("SELECT 1").fetchone()[0] == 1   # 仍然可用
        db.close()


@pytest.mark.cap("manage.ledger")
class TestMigrationRobustness:
    """迁移必须并发安全 + 幂等（0.3.1 之前：并发 init 会留下永久卡死的库）。

    用户实测（MacBook，`myastro init & myastro doctor` 并行）：
    `sqlite3.OperationalError: duplicate column name: dataset_id`，
    且此后**每个命令都失败**——半迁移状态不自愈。
    """

    def _make_stale_version(self, db_path, version: int = 1):
        """造出"结构已是最新、版本号却落后"的残局。"""
        import sqlite3
        DB(db_path).init().close()
        conn = sqlite3.connect(db_path)
        conn.execute(f"PRAGMA user_version={version}")
        conn.commit()
        conn.close()

    def test_heals_stale_version_when_columns_exist(self, tmp_path):
        from myastro.io.db import SCHEMA_VERSION
        path = tmp_path / "stale.db"
        self._make_stale_version(path, 1)
        db = DB(path).init()                       # 曾经在这里抛 duplicate column
        try:
            assert db.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        finally:
            db.close()

    def test_concurrent_init_is_safe(self, tmp_path):
        """多进程同时 init 同一个新库：全部成功，且最终版本/结构正确。

        旧实现的 `executescript` 会隐式提交、拿不住锁，两个进程会各自跑一遍
        ALTER；实测 6 进程必现 duplicate column。
        这里用**独立解释器**（最贴近用户场景：`myastro init & myastro doctor`）。
        """
        import os
        import subprocess
        import sys
        from pathlib import Path

        from myastro.io.db import SCHEMA_VERSION

        path = tmp_path / "race.db"
        src = Path(__file__).resolve().parents[2] / "src"
        env = dict(os.environ, MYASTRO_DB=str(path),
                   PYTHONPATH=f"{src}{os.pathsep}{os.environ.get('PYTHONPATH', '')}")
        code = ("from myastro.io.db import DB\n"
                "db = DB().init()\n"
                "print(db.conn.execute('PRAGMA user_version').fetchone()[0])\n"
                "db.close()")
        procs = [subprocess.Popen([sys.executable, "-c", code], env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                 for _ in range(6)]
        results = []
        for p_ in procs:
            out, err = p_.communicate(timeout=60)
            results.append((p_.returncode, out.decode().strip(), err.decode()[-200:]))
        failed = [r for r in results if r[0] != 0]
        assert not failed, f"并发 init 失败：{failed}"
        # 自证：每个子进程都报告了迁移后的版本（不是"跑了个空壳还退出 0"）
        versions = {r[1] for r in results}
        assert versions == {str(SCHEMA_VERSION)}, f"子进程报告版本不一致：{versions}"

        db = DB(path).init()
        try:
            assert db.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
            cols = {r[1] for r in db.conn.execute("PRAGMA table_info(jobs)")}
            assert {"dataset_id", "gid", "batch_id", "error_type"} <= cols
        finally:
            db.close()

    def test_failed_migration_does_not_advance_version(self, tmp_path, monkeypatch):
        """迁移中途失败必须回滚版本号（否则下次启动会跳过没应用的迁移）。"""
        import sqlite3

        from myastro.io import db as dbmod

        path = tmp_path / "broken.db"
        monkeypatch.setitem(dbmod._MIGRATIONS, 99, ("SELECT * FROM no_such_table",))
        monkeypatch.setattr(dbmod, "SCHEMA_VERSION", 99)
        with pytest.raises(sqlite3.OperationalError):
            DB(path).init()
        conn = sqlite3.connect(path)
        try:
            assert conn.execute("PRAGMA user_version").fetchone()[0] < 99
        finally:
            conn.close()


@pytest.mark.cap("manage.ledger")
def test_init_survives_concurrent_wal_change(tmp_path):
    """另一连接持写锁时，init 仍须成功。

    `PRAGMA journal_mode=WAL` 的变更**不经过 busy handler**：实测即便
    `timeout=5s` 也立刻抛 `database is locked`。并发打开同一个新库时必然有一个
    进程撞上（CI ubuntu 三个矩阵项就是这样红的，macOS 本地却 18/18 全过——
    两个平台加锁时序不同），所以必须先查再改 + 短重试。
    """
    import sqlite3
    import threading
    import time

    path = tmp_path / "wal.db"
    holder = sqlite3.connect(path, check_same_thread=False)
    holder.execute("CREATE TABLE t(x)")
    holder.execute("BEGIN IMMEDIATE")
    holder.execute("INSERT INTO t VALUES (1)")

    def release():
        time.sleep(0.5)
        holder.rollback()
        holder.close()

    threading.Thread(target=release, daemon=True).start()
    db = DB(path).init()                     # 旧实现在这里立刻 database is locked
    try:
        assert db.conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert db.conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 10000
    finally:
        db.close()
