"""CLI 层冒烟：16 个子命令的参数接线、输出与非零退出码。

为什么需要这一层：`fetch` 的参数表由描述符**自动生成**，argparse 接线错、
字段名写错、退出码约定坏掉，都不会被内核/门面测试发现——而 CLI 正是
脚本与第三方使用的"可编程界面"（退出码即契约）。

约定：
- 退出码 2=参数错 / 3=未找到 / 4=网络 / 5=状态不允许（见 cli.EXIT_CODES）
- 命令一律走门面（错误分类只做一次），内核异常不泄漏到 stderr 栈
"""
from __future__ import annotations

import pytest

from myastro import cli
from myastro.descriptors import REGISTRY


def run(capsys, *argv):
    """跑一次 CLI，返回 (退出码, stdout, stderr)。"""
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


@pytest.mark.cap("present.cli")
class TestParseSurface:
    """参数接线：每个描述符源都必须能被 fetch 子命令接住。"""

    @pytest.mark.parametrize("source", sorted(REGISTRY))
    def test_fetch_help_exposes_every_field(self, source, capsys):
        with pytest.raises(SystemExit) as e:          # argparse --help
            cli.main(["fetch", source, "--help"])
        out = capsys.readouterr().out
        assert e.value.code == 0
        for f in REGISTRY[source].fields:
            assert f"--{f.name.replace('_', '-')}" in out, \
                f"{source} 的字段 {f.name} 未出现在 CLI 参数表"

    def test_top_level_help_lists_all_commands(self, capsys):
        with pytest.raises(SystemExit):
            cli.main(["--help"])
        out = capsys.readouterr().out
        for cmd in ("jobs", "wait", "retry", "fetch", "index", "audit",
                    "search", "coverage", "retry-batch", "delete", "orphans",
                    "health", "schedule", "test-map", "doc-sync", "top"):
            assert cmd in out, f"缺少子命令 {cmd}"


@pytest.mark.cap("present.cli")
class TestHappyPaths:
    def test_jobs_empty(self, env, capsys):
        code, out, _ = run(capsys, "jobs")
        assert code == 0 and "无作业" in out

    def test_fetch_unknown_source_rejected_by_argparse(self, env, capsys):
        """源名是 argparse choices → 以退出码 2 退出（与 ParamError 同码）。"""
        with pytest.raises(SystemExit) as e:
            cli.main(["fetch", "no-such-source"])
        assert e.value.code == cli.EXIT_CODES["ParamError"]
        assert "invalid choice" in capsys.readouterr().err

    def test_index_list_and_update_builder(self, env, capsys):
        code, out, _ = run(capsys, "index", "list")
        assert code == 0 and "ztf-fields" in out and "未构建" in out

        code, out, _ = run(capsys, "index", "update", "ztf-fields")
        assert code == 0 and "索引已更新" in out
        code, out, _ = run(capsys, "index", "list")
        assert "已构建" in out

    def test_coverage_after_index_build(self, env, capsys):
        run(capsys, "index", "update", "ztf-fields")
        code, out, _ = run(capsys, "coverage", "ztf-fields")
        assert code == 0 and "1776" in out

    def test_search_renders_rows_with_separation(self, env, capsys):
        from myastro.io.db import DB
        db = DB().init()
        db.conn.execute(
            "INSERT INTO datasets(source,target,params_json,cache_key,ra,dec)"
            " VALUES('vizier','X','{}','k',150.0,2.0)")
        db.conn.commit()
        code, out, _ = run(capsys, "search", "--near", "150.0", "2.0",
                           "--radius", "0.5")
        assert code == 0 and "sep=0.0000" in out and "共 1 条" in out

    def test_audit_empty_ledger(self, env, capsys):
        code, out, _ = run(capsys, "audit")
        assert code == 0 and "核对 0" in out

    def test_orphans_and_delete_and_batch(self, env, capsys):
        assert run(capsys, "orphans")[0] == 0
        assert run(capsys, "orphans")[1].strip() == "标记孤儿作业 0 个"
        code, out, _ = run(capsys, "delete", "999999")
        # 不存在的 id 被"拒绝"而非崩溃；部分失败约定为退出码 1
        assert code == 1 and "拒绝" in out

    def test_schedule_list_offline(self, env, monkeypatch, capsys, tmp_path):
        monkeypatch.setattr("myastro.io.schedule.LAUNCHD_DIR",
                            tmp_path / "LaunchAgents")
        code, out, _ = run(capsys, "schedule", "list")
        assert code == 0 and "health" in out and "index-weekly" in out

    def test_schedule_install_and_remove(self, env, monkeypatch, capsys,
                                        tmp_path):
        monkeypatch.setattr("myastro.io.schedule.LAUNCHD_DIR",
                            tmp_path / "LaunchAgents")
        monkeypatch.setattr("myastro.io.schedule.subprocess.run",
                            lambda *a, **k: None)
        code, out, _ = run(capsys, "schedule", "install", "health")
        assert code == 0 and "已安装" in out
        code, out, _ = run(capsys, "schedule", "remove", "health")
        assert code == 0 and "已移除" in out

    def test_test_map_write_and_check(self, env, monkeypatch, capsys, tmp_path):
        """生成到临时路径再自检（测试不改仓库里的 docs/zh/dev/test-map.md）。"""
        from myastro.io import testmap
        monkeypatch.setattr(testmap, "DOC", tmp_path / "test-map.md")
        code, out, _ = run(capsys, "test-map")
        assert code == 0 and "已生成" in out
        code, out, _ = run(capsys, "test-map", "--check")
        assert code == 0 and "一致" in out

    def test_doc_sync_into_temp_doc(self, env, monkeypatch, capsys, tmp_path):
        """doc-sync 不得改仓库文档（把 DOC 指向临时文件）。"""
        import shutil

        from myastro.io import docsync
        tmp_doc = tmp_path / "design-io.md"
        shutil.copy(docsync.DOC, tmp_doc)
        monkeypatch.setattr(docsync, "DOC", tmp_doc)
        code, _, _ = run(capsys, "doc-sync")
        assert code == 0


@pytest.mark.cap("present.cli")
class TestErrorExitCodes:
    """退出码是脚本可编程契约——每条都要落到约定值。"""

    def test_not_found(self, env, capsys):
        import myastro as ma

        code, _, err = run(capsys, "retry", "999999")
        assert code == cli.EXIT_CODES["NotFoundError"]
        assert "未找到" in err and "Traceback" not in err
        code, _, _ = run(capsys, "wait", "999999")
        assert code == cli.EXIT_CODES["NotFoundError"]
        code, _, _ = run(capsys, "retry-batch", "nope")
        assert code == cli.EXIT_CODES["NotFoundError"]
        code, _, _ = run(capsys, "coverage", "no-such-index")
        assert code == cli.EXIT_CODES["NotFoundError"]
        assert ma is not None

    def test_healthy_delete_is_refused_with_partial_code(self, env, monkeypatch,
                                                        capsys):
        """运行中的作业被拒绝删除：打印原因 + 退出码 1（部分失败），不崩。

        必须显式声明守护进程在线：离线时该作业判为僵尸、允许删除（语义不同），
        CI 上没有 daemon，实测因此失败过。
        """
        monkeypatch.setattr("myastro.io.aria2.ping", lambda: True)
        import json

        from myastro.io.db import DB
        db = DB().init()
        db.conn.execute(
            "INSERT INTO jobs(spec_json,executor,status,updated_at)"
            " VALUES(?,?,?,datetime('now'))",
            (json.dumps({"source": "legacy", "params": {}}), "aria2", "running"))
        db.conn.commit()
        job_id = db.conn.execute("SELECT id FROM jobs").fetchone()["id"]
        code, out, _ = run(capsys, "delete", str(job_id))
        assert code == 1
        assert "拒绝" in out and "running" in out

    def test_invalid_task_rejected_by_argparse(self, env, capsys):
        """任务名是 choices：非法值以退出码 2 退出，且不打印栈。"""
        with pytest.raises(SystemExit) as e:
            cli.main(["schedule", "remove", "no-such-task"])
        assert e.value.code == cli.EXIT_CODES["ParamError"]
        assert "Traceback" not in capsys.readouterr().err


@pytest.mark.cap("present.cli")
class TestVersion:
    """--version 必须可用且与包元数据同源（版本只有一处手写）。"""

    def test_version_flag(self, capsys):
        import myastro
        with pytest.raises(SystemExit) as e:
            cli.main(["--version"])
        out = capsys.readouterr().out.strip()
        assert e.value.code == 0
        assert out == f"myastro {myastro.__version__}"

    def test_version_is_single_sourced(self):
        """pyproject 的 version 与运行时版本一致（防止再次漂移）。"""
        import tomllib
        from pathlib import Path

        import myastro
        py = tomllib.loads(Path("pyproject.toml").read_text())
        declared = py["project"]["version"]
        assert myastro.__version__.split("+")[0] == declared, (
            f"pyproject {declared} 与运行时 {myastro.__version__} 漂移")


@pytest.mark.cap("present.cli")
class TestSourceCheckoutOnlyCommands:
    """开发向命令（test-map / doc-sync）在非源码仓库必须清晰报错。

    真实问题：从已安装的 wheel 运行时，`test-map` 因相对 CWD 路径直接抛
    FileNotFoundError 栈；`doc-sync` 用 `__file__` 上溯，会**往 venv 的
    site-packages 写文件**。现在两者都先确认"我在源码树里"。
    """

    def _break_source_root(self, monkeypatch):
        def boom(*a, **k):
            raise ValueError("未找到 myastro 源码仓库")
        monkeypatch.setattr("myastro.io.core.source_root", boom)

    def _assert_no_docs_written(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert not (tmp_path / "docs").exists()

    def test_test_map_outside_checkout(self, env, monkeypatch, capsys, tmp_path):
        self._break_source_root(monkeypatch)
        self._assert_no_docs_written(tmp_path, monkeypatch)
        code, _out, err = run(capsys, "test-map")
        assert code == cli.EXIT_CODES["ParamError"]
        assert "仅用于源码仓库" in err and "Traceback" not in err
        assert not (tmp_path / "docs").exists()

    def test_doc_sync_outside_checkout(self, env, monkeypatch, capsys, tmp_path):
        self._break_source_root(monkeypatch)
        self._assert_no_docs_written(tmp_path, monkeypatch)
        code, _out, err = run(capsys, "doc-sync")
        assert code == cli.EXIT_CODES["ParamError"]
        assert "仅用于源码仓库" in err
        assert not (tmp_path / "docs").exists(), "不得在 CWD 造出 docs/ 目录"


@pytest.mark.cap("design.guards")
class TestSourceRoot:
    def test_finds_repo_root_from_source_tree(self):
        from myastro.io.core import source_root
        root = source_root()
        assert (root / "pyproject.toml").is_file()
        assert (root / "src" / "myastro").is_dir()

    def test_raises_outside_source_tree(self, tmp_path):
        from myastro.io.core import source_root
        with pytest.raises(ValueError, match="源码仓库"):
            source_root(tmp_path / "not_a_repo" / "x.py")

    def test_rejects_other_projects_pyproject(self, tmp_path):
        """别的项目的 pyproject.toml 不算（按 [project].name 判定）。"""
        from myastro.io.core import source_root
        proj = tmp_path / "other"
        proj.mkdir()
        (proj / "pyproject.toml").write_text('[project]\nname = "other"\n')
        with pytest.raises(ValueError):
            source_root(proj / "x.py")


@pytest.mark.cap("present.cli")
class TestDoctorInitBackupRestore:
    """新命令的 CLI 契约：init / doctor / backup / restore。"""

    def test_init_creates_paths(self, env, tmp_path, monkeypatch, capsys):
        # env 已建库；指向新位置验证"创建"行为
        data, db = tmp_path / "d2", tmp_path / "db2" / "astro.db"
        monkeypatch.setenv("MYASTRO_DATA", str(data))
        monkeypatch.setenv("MYASTRO_DB", str(db))
        code, out, _ = run(capsys, "init")
        assert code == 0 and str(data) in out and str(db) in out
        assert data.is_dir() and db.is_file()

    def test_doctor_ok_in_clean_env(self, env, capsys):
        code, out, _ = run(capsys, "doctor")
        assert code == 0
        assert "自检完成" in out and "0 个问题" in out

    def test_doctor_exit_1_on_failure(self, env, monkeypatch, capsys):
        """有 FAIL 时退出码 1（脚本可据此判断环境是否可用）。"""
        import myastro as ma
        monkeypatch.setattr(ma, "doctor",
                            lambda: [{"name": "假检查", "status": "fail",
                                      "detail": "坏了", "fix": "修一下"}])
        code, out, _ = run(capsys, "doctor")
        assert code == 1 and "✗ 假检查" in out and "修一下" in out

    def test_backup_then_restore_round_trip(self, env, tmp_path, capsys):
        from myastro.io.db import DB
        db = DB().init()
        db.conn.execute("INSERT INTO datasets(source,target,params_json,cache_key)"
                        " VALUES('s','t','{}','k')")
        db.conn.commit()
        db.close()

        bkdir = tmp_path / "bk"
        code, out, _ = run(capsys, "backup", "--out", str(bkdir))
        assert code == 0 and "备份目录" in out and (bkdir / "astro.db").is_file()

        conn = __import__("sqlite3").connect(
            __import__("os").environ["MYASTRO_DB"])
        conn.execute("DELETE FROM datasets")
        conn.commit()
        conn.close()

        code, out, _ = run(capsys, "restore", str(bkdir), "--force")
        assert code == 0 and "已从" in out and "安全副本" in out or "已留存" in out

    def test_restore_without_force_fails_cleanly(self, env, tmp_path, capsys):
        code, _, err = run(capsys, "restore", str(tmp_path / "nope"))
        assert code == cli.EXIT_CODES["ParamError"]
        assert "备份里没有 astro.db" in err and "Traceback" not in err

    @pytest.mark.cap("present.cli")
    def test_preview_command(self, env, capsys, tmp_path):
        """preview 输出嗅探类型与 schema；#id 形式走账本解析。"""
        import pandas as pd
        f = tmp_path / "x.parquet"
        pd.DataFrame({"a": [1, 2]}).to_parquet(f)
        code, out, _ = run(capsys, "preview", str(f))
        assert code == 0 and "【parquet】" in out and "schema" in out and "行数：2" in out

    @pytest.mark.cap("present.cli")
    def test_describe_and_version(self, env, capsys):
        """describe 输出详情与参数表；version 输出版本身份块。"""
        code, out, _ = run(capsys, "describe", "tess")
        assert code == 0
        assert "前置" in out and "target" in out and "示例" in out
        assert "（可空）" in out or "（必填）" in out

        code, out, _ = run(capsys, "version")
        assert code == 0 and "myastro" in out and "schema v8" in out
