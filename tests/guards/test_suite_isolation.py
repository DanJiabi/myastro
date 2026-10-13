"""测试套件不得触碰用户的默认数据根/账本（会话安全网的守卫）。

真实事故（2026-10-12）：一条漏挂 `env` fixture 的测试通过 `ma.batch` 提交了真作业，
把 7 条幽灵作业（`disc-demo`，2 failed + 5 永远 running）写进了用户真账本
`~/.local/state/myastro/astro.db`。环境变量必须在**会话开始**就指向沙箱，
否则"忘了挂 fixture"这种失误会静默污染用户数据。
"""
from __future__ import annotations

import os
import pathlib

import pytest


@pytest.mark.cap("manage.ledger")
def test_ledger_env_var_points_into_sandbox():
    db = os.environ.get("MYASTRO_DB", "")
    assert db, "MYASTRO_DB 未设置——会话安全网（conftest 的 _sandbox_user_paths）被拆了？"
    assert "myastro-session-sandbox" in db, f"账本不在会话沙箱内: {db}"
    default = pathlib.Path.home() / ".local" / "state" / "myastro" / "astro.db"
    assert pathlib.Path(db).resolve() != default.resolve(), "测试套件不得写用户默认账本"


@pytest.mark.cap("manage.ledger")
def test_data_root_env_var_points_into_sandbox():
    data = os.environ.get("MYASTRO_DATA", "")
    assert data, "MYASTRO_DATA 未设置——会话安全网被拆了？"
    assert "myastro-session-sandbox" in data, f"数据根不在会话沙箱内: {data}"


@pytest.mark.cap("manage.ledger")
def test_resolved_db_path_is_sandboxed():
    """不只是环境变量：`Config()` 解析出来的账本路径也必须在沙箱里。"""
    from myastro.io.config import Config

    db_path = pathlib.Path(Config().db).resolve()
    assert "myastro-session-sandbox" in str(db_path), f"解析出的账本路径不在沙箱: {db_path}"
