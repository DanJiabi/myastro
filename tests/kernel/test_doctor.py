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
def test_optional_dep_hint_uses_real_extra_name(env, monkeypatch):
    """提示里的 pip 命令必须真能执行：发行名 ≠ extra 名（pyasassn → [asassn]）。"""
    import importlib
    real = importlib.import_module

    def fake(mod, *a, **k):
        if mod in ("pyasassn", "ztfquery"):
            raise ImportError(mod)
        return real(mod, *a, **k)

    monkeypatch.setattr(doctor.importlib, "import_module", fake)
    checks = {c.name: c for c in doctor._check_deps()}
    assert "[asassn]" in checks["可选 pyasassn"].fix
    assert "[ztfquery]" in checks["可选 ztfquery"].fix
    assert "pyasassn]" not in checks["可选 pyasassn"].fix


@pytest.mark.cap("manage.doctor")
class TestAria2Checks:
    """aria2 是可选系统依赖：缺失只报警告（用它的只有 legacy/ztf/manifest）。"""

    def _state(self, monkeypatch, **over):
        base = {"binary": None, "daemon": False, "auth_ok": None,
                "secret": "myastro-legacy", "port": 6800,
                "install_hint": "macOS: brew install aria2 | Debian/Ubuntu: sudo apt install aria2"}
        base.update(over)
        monkeypatch.setattr("myastro.io.aria2.diagnose", lambda root=None: base)
        return {c.name: c for c in doctor._check_aria2()}

    def test_missing_binary_is_warning_not_failure(self, monkeypatch):
        checks = self._state(monkeypatch)
        c = checks["aria2（可选）"]
        assert c.status == doctor.WARN
        assert "批量下载" in c.detail and "其余源不受影响" in c.detail
        assert "apt install aria2" in c.fix

    def test_binary_present_daemon_down_is_ok(self, monkeypatch):
        """装了但没起不是问题：首次使用会自动拉起。"""
        checks = self._state(monkeypatch, binary="/usr/bin/aria2c")
        assert checks["aria2（可选）"].status == doctor.OK
        assert checks["aria2 守护进程"].status == doctor.OK
        assert "自动拉起" in checks["aria2 守护进程"].detail

    def test_daemon_running_is_ok(self, monkeypatch):
        checks = self._state(monkeypatch, binary="/usr/bin/aria2c",
                             daemon=True, auth_ok=True)
        assert checks["aria2 守护进程"].status == doctor.OK
        assert "RPC 在线" in checks["aria2 守护进程"].detail

    def test_wrong_secret_is_called_out(self, monkeypatch):
        checks = self._state(monkeypatch, binary="/usr/bin/aria2c",
                             daemon=True, auth_ok=False)
        c = checks["aria2 守护进程"]
        assert c.status == doctor.WARN and "密钥不匹配" in c.detail
        assert "MYASTRO_ARIA2_SECRET" in c.fix
