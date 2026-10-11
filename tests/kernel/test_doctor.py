"""环境自检（`manage.doctor`）：装完第一件事能自证"这里能不能用"。"""
from __future__ import annotations

import pytest

from myastro.io import doctor


@pytest.mark.cap("manage.doctor")
class TestDoctorChecks:
    def test_fresh_env_has_no_failures(self, env):
        checks = doctor.run()
        s = doctor.summary(checks)
        assert s["fail"] == 0, [c.as_dict() for c in checks if c.status == "fail"]
        assert s["ok"] > 10                        # 真的跑了检查，不是空转
        names = {c.name for c in checks}
        assert {"平台", "schema 版本", "账本文件系统"} <= names

    def test_reports_missing_files(self, env):
        """账本里有记录但文件不在盘上 → 警告（不是失败：可能是清理过数据）。"""
        from myastro.io.db import DB
        db = DB().init()
        cur = db.conn.execute(
            "INSERT INTO datasets(source,target,params_json,cache_key)"
            " VALUES('s','t','{}','k')")
        db.conn.execute("INSERT INTO files(dataset_id,path,size,format)"
                        " VALUES(?,?,1,'fits')", (cur.lastrowid, "/nonexistent/x.fits"))
        db.conn.commit()
        checks = {c.name: c for c in doctor.run()}
        assert checks["文件抽查"].status == doctor.WARN
        assert "不在盘上" in checks["文件抽查"].detail
        assert "audit" in checks["文件抽查"].fix

    def test_schema_ahead_of_code_is_failure(self, env):
        from myastro.io.db import DB
        db = DB().init()
        db.conn.execute("PRAGMA user_version=99")
        db.conn.commit()
        db.close()
        checks = {c.name: c for c in doctor.run()}
        assert checks["schema 版本"].status == doctor.FAIL
        assert "升级 myastro" in checks["schema 版本"].fix

    def test_network_filesystem_for_ledger_is_failure(self, env, monkeypatch):
        """账本放 NFS 是硬错误：SQLite WAL 与网络文件系统不兼容。"""
        monkeypatch.setattr(doctor, "_fs_type", lambda p: "nfs")
        checks = {c.name: c for c in doctor.run()}
        assert checks["账本文件系统"].status == doctor.FAIL
        assert "本地磁盘" in checks["账本文件系统"].fix

    def test_local_filesystem_is_ok(self, env, monkeypatch):
        monkeypatch.setattr(doctor, "_fs_type", lambda p: "apfs")
        checks = {c.name: c for c in doctor.run()}
        assert checks["账本文件系统"].status == doctor.OK

    def test_unwritable_data_root_is_failure(self, env, monkeypatch):
        from pathlib import Path

        from myastro.io.config import Config
        target = Path(env) / "ro" / "data"
        target.mkdir(parents=True)
        target.chmod(0o500)                        # 只读目录
        try:
            checks = {c.name: c for c in doctor.run(Config(data=target,
                                                          db=Path(env) / "x.db"))}
            assert checks["数据根可写"].status == doctor.FAIL
            assert "MYASTRO_DATA" in checks["数据根可写"].fix
        finally:
            target.chmod(0o700)

    def test_one_broken_check_does_not_kill_the_rest(self, env, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("模拟检查器自身出错")
        monkeypatch.setattr(doctor, "_check_indexes", boom)
        checks = doctor.run()
        assert any(c.name == "索引检查" and c.status == doctor.FAIL
                   for c in checks), [c.as_dict() for c in checks]
        assert any(c.name == "平台" for c in checks)   # 其余检查照跑

    def test_version_tuple_comparison(self):
        assert doctor._vtuple("2.0") < doctor._vtuple("2.0.1")
        assert doctor._vtuple("1.9.9") < doctor._vtuple("2.0")
        assert doctor._vtuple("0.4.11") > doctor._vtuple("0.4.9")
        assert doctor._vtuple("") == (0,)

    def test_json_serializable(self, env):
        import json
        json.dumps([c.as_dict() for c in doctor.run()], ensure_ascii=False)


@pytest.mark.cap("manage.doctor")
def test_optional_dep_hint_is_actually_runnable(env, monkeypatch):
    """提示里的命令必须真能跑通——这里拦的是两类实测事故：

    ① extra 名写错（曾提示 `myastro[pyasassn]`，实际是 `myastro[asassn]`）；
    ② extra 根本装不上（pyasassn 0.6.4 把 `pyarrow==4.0.1` 钉死，4.0.1 无
       Python 3.12+ 轮子 → pip 源码编译失败，用户实测），必须改走 `--no-deps`。
    """
    import importlib
    real = importlib.import_module

    def fake(mod, *a, **k):
        if mod in ("pyasassn", "ztfquery"):
            raise ImportError(mod)
        return real(mod, *a, **k)

    monkeypatch.setattr(doctor.importlib, "import_module", fake)
    fixes = {c.name: (c.fix or "") for c in doctor._check_deps()}

    assert "--no-deps pyasassn" in fixes["可选 pyasassn"], fixes["可选 pyasassn"]
    assert "myastro[pyasassn]" not in fixes["可选 pyasassn"]
    assert fixes["可选 ztfquery"] == "pip install 'myastro[ztfquery]'"
