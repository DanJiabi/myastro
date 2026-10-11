"""aria2 配置与失败路径（可选系统依赖：只有批量下载需要它）。

背景：`RPC_SECRET` 曾是硬编码常量——任何本机进程知道这个字符串就能通过 RPC
控制用户的 aria2（往数据目录塞下载）。另外 aria2 缺失时旧实现会先白等 10 秒，
提示还只写 `brew install aria2`（Linux 用户照做不了）。
"""
from __future__ import annotations

import time

import pytest

from myastro.io import aria2


@pytest.mark.cap("acquire.fetch")
class TestConfig:
    def test_secret_and_port_are_runtime_configurable(self, monkeypatch):
        monkeypatch.setenv("MYASTRO_ARIA2_SECRET", "own-secret")
        monkeypatch.setenv("MYASTRO_ARIA2_PORT", "6899")
        assert aria2.rpc_secret() == "own-secret"
        assert aria2.rpc_port() == 6899
        assert aria2.rpc_url() == "http://127.0.0.1:6899/jsonrpc"

    def test_defaults_preserve_backward_compatibility(self, monkeypatch):
        monkeypatch.delenv("MYASTRO_ARIA2_SECRET", raising=False)
        monkeypatch.delenv("MYASTRO_ARIA2_PORT", raising=False)
        assert aria2.rpc_secret() == aria2.DEFAULT_RPC_SECRET
        assert aria2.rpc_port() == aria2.DEFAULT_RPC_PORT

    def test_daemon_command_matches_runtime_config(self, monkeypatch):
        monkeypatch.setenv("MYASTRO_ARIA2_SECRET", "s3cret")
        monkeypatch.setenv("MYASTRO_ARIA2_PORT", "6877")
        cmd = aria2.daemon_command("/data/root")
        assert "--rpc-secret=s3cret" in cmd
        assert "--rpc-listen-port=6877" in cmd
        assert cmd[cmd.index("-d") + 1] == "/data/root"


@pytest.mark.cap("acquire.fetch")
class TestFailFast:
    """失败路径必须"立刻说清问题"，且**不产生副作用**（测试里不能真拉起 daemon）。"""

    @pytest.fixture
    def no_side_effects(self, monkeypatch):
        """替换 Popen 与 sleep：测试既不 spawn 真进程，也不白等 10 秒。"""
        calls = []
        monkeypatch.setattr(aria2.subprocess, "Popen",
                            lambda cmd, **kw: calls.append(cmd))
        monkeypatch.setattr(aria2.time, "sleep", lambda s: None)
        return calls

    def test_missing_binary_fails_immediately_with_cross_platform_hint(
            self, monkeypatch, no_side_effects):
        monkeypatch.setattr(aria2, "ping", lambda: False)
        monkeypatch.setattr("shutil.which", lambda name: None)
        t0 = time.monotonic()
        with pytest.raises(RuntimeError) as e:
            aria2.ensure_daemon("/tmp/whatever")
        elapsed = time.monotonic() - t0
        msg = str(e.value)
        assert elapsed < 1.0, f"缺二进制还等了 {elapsed:.1f}s（旧实现等 10s）"
        assert "apt install aria2" in msg and "brew install aria2" in msg
        assert no_side_effects == [], "缺二进制时不该尝试启动"
        assert "MYASTRO_ARIA2_SECRET" not in msg      # 与密钥无关，别混淆用户

    def test_starts_daemon_when_binary_present(self, monkeypatch, no_side_effects,
                                               tmp_path):
        """装了但没起：按运行期配置拉起，成功即返回（不打日志、不占终端）。"""
        pings = iter([False, True])
        monkeypatch.setattr(aria2, "ping", lambda: next(pings))
        monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/aria2c")
        monkeypatch.setenv("MYASTRO_ARIA2_SECRET", "s3cret")
        aria2.ensure_daemon(tmp_path / "root")
        assert len(no_side_effects) == 1
        assert "--rpc-secret=s3cret" in no_side_effects[0]

    def test_wrong_secret_is_reported_as_such(self, monkeypatch, no_side_effects):
        """daemon 在跑但密钥不匹配：必须说清是密钥问题，而不是"离线"。"""
        monkeypatch.setattr(aria2, "ping", lambda: False)
        monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/aria2c")
        monkeypatch.setattr(aria2, "diagnose",
                            lambda root=None: {"binary": "/usr/bin/aria2c",
                                               "daemon": True, "auth_ok": False,
                                               "secret": "expected-secret",
                                               "port": 6800, "install_hint": ""})
        with pytest.raises(RuntimeError) as e:
            aria2.ensure_daemon("/tmp/whatever")
        msg = str(e.value)
        assert "密钥不匹配" in msg
        assert "expected-secret" in msg and "MYASTRO_ARIA2_SECRET" in msg

    def test_diagnose_distinguishes_not_running_from_wrong_secret(
            self, monkeypatch):
        """真路径探测：端口没人听 → daemon=False；能应答但密钥错 → daemon=True, auth_ok=False。"""
        monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/aria2c")
        monkeypatch.setattr(aria2, "ping", lambda: False)
        monkeypatch.setenv("MYASTRO_ARIA2_PORT", "9")     # 保留端口：必然连接被拒
        state = aria2.diagnose()
        assert state["binary"] and state["daemon"] is False
        assert state["auth_ok"] is None
