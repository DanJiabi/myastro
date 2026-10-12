"""插件自动发现：契约骨架 + 反例（协议 v1 第三块，L3）。

分批实现：本文件先锁**接口与不变量**（2a-1），加载器实现（2a-2）与惰性触发/恢复兜底
（2a-3）随后补齐对应反例。
"""
from __future__ import annotations

import pytest

from myastro.io import plugins


@pytest.fixture(autouse=True)
def clean_state():
    plugins._reset_for_tests()
    yield
    plugins._reset_for_tests()


@pytest.mark.cap("source.contract")
class TestContract:
    def test_discover_is_idempotent(self):
        """反复调用不改变结果（不变量 I4）。"""
        plugins.discover()
        first = (plugins.loaded(), plugins.errors())
        plugins.discover()
        plugins.discover(force=True)
        assert (plugins.loaded(), plugins.errors()) == first

    def test_empty_by_default_without_plugins(self):
        """无插件的环境：不加载任何东西、不报错（不变量 I2 的接口面）。"""
        plugins.discover()
        assert plugins.loaded() == []
        assert plugins.errors() == []

    def test_views_are_read_only_copies(self):
        """`loaded()`/`errors()` 返回副本——调用方改不动内部状态。"""
        got = plugins.loaded()
        got.append("伪造的插件")
        assert plugins.loaded() == []
        errs = plugins.errors()
        errs.append(plugins.PluginError("x", "E", "m"))
        assert plugins.errors() == []

    def test_error_record_shape(self):
        """错误记录必须带得出"哪个模块、什么错、怎么办"。"""
        err = plugins.PluginError(module="bad_plugin", error_type="ImportError",
                                  message="No module named 'nope'",
                                  hint="pip install bad_plugin")
        d = err.as_dict()
        assert d == {"module": "bad_plugin", "error_type": "ImportError",
                     "message": "No module named 'nope'",
                     "hint": "pip install bad_plugin"}

    def test_constants_are_the_documented_contract(self):
        """组名与环境变量名是**对外契约**（插件作者按它写），不能随手改。"""
        assert plugins.PLUGIN_GROUP == "myastro.sources"
        assert plugins.ENV_VAR == "MYASTRO_SOURCES"


@pytest.mark.cap("source.contract")
class TestEnvParsing:
    def test_empty_when_unset(self, monkeypatch):
        monkeypatch.delenv(plugins.ENV_VAR, raising=False)
        assert plugins.env_entries() == []

    def test_parses_list_and_ignores_blanks(self, monkeypatch):
        monkeypatch.setenv(plugins.ENV_VAR, " mod_a , ,mod_b:OBJ ,")
        assert plugins.env_entries() == ["mod_a", "mod_b:OBJ"]

    def test_does_not_trigger_discovery(self, monkeypatch):
        """解析环境变量本身不得触发发现（惰性，不变量 I6）。"""
        monkeypatch.setenv(plugins.ENV_VAR, "mod_a")
        plugins.env_entries()
        assert not plugins._STATE.discovered


# ── 2a-2：加载器实现（真导入 / 预探测 / 错误隔离）─────────────────────────────

GOOD_PLUGIN = '''
import myastro as ma

def _task(ctx):
    raise RuntimeError("不该被调用")

ma.register_task("disc_demo_task", _task)
ma.register_source(ma.SourceDescriptor(
    name="disc-demo", desc="发现测试源", product="parquet", status="ok",
    fields=[ma.FieldSpec("target", pattern=r"^[A-Za-z0-9 _-]{1,32}$")],
    task="disc_demo_task", example_params={"target": "M31"},
))
'''

BAD_REGISTER = '''
import myastro as ma
ma.register_task("bad_api_task", lambda ctx: None)
ma.register_source(ma.SourceDescriptor(
    name="bad-api", desc="协议版本不符", product="parquet", status="ok",
    fields=[ma.FieldSpec("t", pattern=r"^\\w+$")],
    task="bad_api_task", example_params={"t": "x"}, api_version=99,
))
'''

HANGS = '''
import time
time.sleep(30)          # import 阶段挂死：预探测必须挡住它
'''

RAISES = "raise RuntimeError('插件导入即失败')\n"

SYNC_PLUGIN = '''
import pandas as pd

import myastro as ma


def _sync_task(ctx):
    dest = ctx.dest_dir / f"{ctx.params['target']}.parquet"
    ma.write_parquet(pd.DataFrame({"x": [1]}), dest)
    return ma.FetchResult(paths=[dest], dataset_id=0, meta={"n": 1})


ma.register_task("disc_sync_task", _sync_task)
ma.register_source(ma.SourceDescriptor(
    name="disc-sync", desc="同步发现测试源", product="parquet", status="ok",
    fields=[ma.FieldSpec("target", pattern=r"^[A-Za-z0-9 _-]{1,32}$")],
    task="disc_sync_task", example_params={"target": "M31"},
))
'''


@pytest.fixture
def plugin_env(tmp_path, monkeypatch):
    """把临时目录挂到 sys.path，并按需写插件模块。"""
    import sys

    from myastro.descriptors import REGISTRY
    from myastro.tasks import TASKS

    reg, tasks = dict(REGISTRY), dict(TASKS)
    modules: list[str] = []
    monkeypatch.syspath_prepend(str(tmp_path))

    def write(name: str, code: str) -> str:
        (tmp_path / f"{name}.py").write_text(code)
        modules.append(name)
        return name

    yield write

    for name in modules:
        sys.modules.pop(name, None)
    REGISTRY.clear(); REGISTRY.update(reg)
    TASKS.clear(); TASKS.update(tasks)
    monkeypatch.delenv(plugins.ENV_VAR, raising=False)


@pytest.mark.cap("source.contract")
class TestLoader:
    def test_loads_plugin_from_env_var(self, plugin_env, monkeypatch):
        name = plugin_env("disc_good", GOOD_PLUGIN)
        monkeypatch.setenv(plugins.ENV_VAR, name)
        plugins.discover()
        assert plugins.loaded() == [name]
        assert plugins.errors() == []
        assert "disc-demo" in {s["name"] for s in __import__("myastro").sources()}

    def test_duplicate_module_listed_twice_loads_once(self, plugin_env, monkeypatch):
        name = plugin_env("disc_dup", GOOD_PLUGIN)
        monkeypatch.setenv(plugins.ENV_VAR, f"{name},{name}")
        plugins.discover()
        assert plugins.loaded() == [name]

    def test_missing_module_is_recorded_not_raised(self, monkeypatch):
        monkeypatch.setenv(plugins.ENV_VAR, "no_such_plugin_module_xyz")
        plugins.discover()                       # 不抛
        (err,) = plugins.errors()
        assert err.module == "no_such_plugin_module_xyz"
        assert err.error_type in ("ProbeFailed", "ModuleNotFoundError")

    def test_import_error_is_recorded(self, plugin_env, monkeypatch):
        name = plugin_env("disc_raises", RAISES)
        monkeypatch.setenv(plugins.ENV_VAR, name)
        plugins.discover()
        (err,) = plugins.errors()
        # 探测子进程导入即抛 → 结构化标记让主进程拿到**精确类型**
        assert err.error_type == "RuntimeError" and "插件导入即失败" in err.message
        assert err.hint == ""                     # 非注册类错误不给协议提示
        assert plugins.loaded() == []

    def test_registration_error_is_recorded_with_hint(self, plugin_env, monkeypatch):
        """注册被拒（协议版本不符）必须被记录，且提示指向协议规则。"""
        name = plugin_env("disc_bad_api", BAD_REGISTER)
        monkeypatch.setenv(plugins.ENV_VAR, name)
        plugins.discover()
        (err,) = plugins.errors()
        assert err.error_type == "ParamError" and "协议版本" in err.message
        assert "插件协议" in err.hint
        assert plugins.loaded() == []

    def test_hanging_plugin_is_isolated_by_probe(self, plugin_env, monkeypatch):
        """import 阶段挂死的插件被预探测挡住：主进程不受影响（不变量 I1/I5）。

        `PROBE_TIMEOUT` 调成 1s——刻意不用"等 20 秒"来验证超时行为。
        """
        name = plugin_env("disc_hangs", HANGS)
        monkeypatch.setenv(plugins.ENV_VAR, name)
        monkeypatch.setattr(plugins, "PROBE_TIMEOUT", 1.0)
        plugins.discover()
        (err,) = plugins.errors()
        assert err.error_type == "ProbeTimeout"
        assert "挂死" in err.message
        assert plugins.loaded() == []

    def test_bad_env_format_is_tolerated(self, monkeypatch):
        """格式非法（多余冒号/空格/空项）不得抛异常。"""
        monkeypatch.setenv(plugins.ENV_VAR, " , : , ,")
        plugins.discover()
        assert plugins.loaded() == []
        assert plugins.errors() == []

    def test_attr_form_invokes_register_function(self, plugin_env, monkeypatch):
        """`模块:属性` 形态：属性是可调用对象时被调用（约定：注册函数）。"""
        name = plugin_env("disc_attr", '''
def register():
    import myastro as ma
    ma.register_task("disc_attr_task", lambda ctx: None)
    ma.register_source(ma.SourceDescriptor(
        name="disc-attr", desc="attr 形态", product="parquet", status="ok",
        fields=[ma.FieldSpec("t", pattern=r"^\\w+$")],
        task="disc_attr_task", example_params={"t": "x"}))
''')
        monkeypatch.setenv(plugins.ENV_VAR, f"{name}:register")
        plugins.discover()
        assert plugins.loaded() == [name]
        assert "disc-attr" in REGISTRY_OF_SOURCES()

    def test_entry_points_channel_is_supported(self, monkeypatch):
        """entry-points 组 `myastro.sources` 是正式通道（用假 EP 验证装配）。"""
        import importlib.metadata as md

        class FakeEP:
            name, value = "fake", "disc_good"

        monkeypatch.setattr(md, "entry_points",
                            lambda **kw: [FakeEP()] if kw.get("group") == plugins.PLUGIN_GROUP else [])
        monkeypatch.setenv(plugins.ENV_VAR, "")
        plugins.discover()
        (err,) = plugins.errors()                # 模块不存在 → 记录，而不是崩
        assert err.module == "disc_good"


def REGISTRY_OF_SOURCES() -> set[str]:
    from myastro.descriptors import REGISTRY
    return set(REGISTRY)


# ── 2a-3：惰性触发点与恢复兜底 ────────────────────────────────────────────────

@pytest.mark.cap("source.contract")
class TestLazyWiring:
    def test_import_myastro_does_not_discover(self):
        """不变量：`import myastro` 本身**不**触发发现（惰性）。"""
        assert not plugins._STATE.discovered or plugins.loaded() == []

    def test_sources_triggers_discovery(self, plugin_env, monkeypatch):
        import myastro as ma

        name = plugin_env("lazy_good", GOOD_PLUGIN)
        monkeypatch.setenv(plugins.ENV_VAR, name)
        assert plugins._STATE.discovered is False
        names = {s["name"] for s in ma.sources()}          # 触发点
        assert plugins._STATE.discovered is True
        assert "disc-demo" in names

    def test_descriptor_lookup_triggers_discovery(self, plugin_env, monkeypatch, env):
        """`_descriptor()`（fetch/batch 按源名查表走这里）**自己**就能触发发现。

        两个测试卫生要点（初版都踩了）：
        ① 必须让本用例成为**首个**触发者——初版先调 `describe()`（经 `sources()`
           已经触发过），把 `_descriptor` 的触发删掉测试依然绿，变异验证抓到了；
        ② 用**同步**的 `ma.fetch`（0.3.5 起在调用线程执行），不要用 `batch`——
           后者提交后台作业，任务抛错会变成"游离线程异常"，被 pytest 的
           thread-exception 插件算到**下一个用例**头上。
        """
        import myastro as ma

        name = plugin_env("lazy_desc", SYNC_PLUGIN)
        monkeypatch.setenv(plugins.ENV_VAR, name)
        assert plugins._STATE.discovered is False             # 还没人触发过
        result = ma.fetch("disc-sync", target="M31")          # ← 首个触发者
        assert result.paths and result.paths[0].exists()
        assert plugins._STATE.discovered is True

    def test_cli_parser_includes_plugin_source_after_discovery(
            self, plugin_env, monkeypatch):
        """CLI 的 `fetch <源>` 子命令由注册表生成：发现之后必须出现。"""
        from myastro import cli

        name = plugin_env("lazy_cli", GOOD_PLUGIN)
        monkeypatch.setenv(plugins.ENV_VAR, name)
        plugins.ensure_discovered()
        parser = cli._build_parser()
        fetch_cmd = next(a for a in parser._actions
                         if getattr(a, "choices", None) and "fetch" in a.choices)
        subs = fetch_cmd.choices["fetch"]._actions
        choices = next(a for a in subs if getattr(a, "choices", None)).choices
        assert "disc-demo" in choices

    def test_cli_main_triggers_discovery(self, monkeypatch, capsys):
        """`main()` 必须先发现再建解析器（用假发现函数记录调用）。"""
        from myastro import cli

        called = []
        monkeypatch.setattr(plugins, "ensure_discovered", lambda: called.append(1))
        with pytest.raises(SystemExit):                      # `--help` 走 argparse 退出
            cli.main(["--help"])
        assert called, "cli.main 未触发插件发现"


@pytest.mark.cap("source.contract")
class TestRecoveryFallback:
    def test_resolve_fn_recovers_plugin_task(self, plugin_env, monkeypatch):
        """`runner._resolve_fn` 是**真实代码路径**：任务缺失时兜底发现再解析。

        模拟"另一个进程创建的作业"：插件模块与任务都不在内存里
        （`sys.modules`/`TASKS` 已清），只靠环境变量指向插件模块。
        """
        import sys

        from myastro.descriptors import REGISTRY
        from myastro.io.jobs import runner
        from myastro.tasks import TASKS

        name = plugin_env("recover_good", GOOD_PLUGIN)
        monkeypatch.setenv(plugins.ENV_VAR, name)
        plugins.discover()
        assert "disc-demo" in REGISTRY
        spec = REGISTRY["disc-demo"].build_spec({"target": "M31"})

        # 清成"另一个进程刚启动"的样子：插件没导入、任务表里没有它
        TASKS.pop("disc_demo_task", None)
        sys.modules.pop(name, None)
        plugins._reset_for_tests()
        assert "disc_demo_task" not in TASKS
        assert plugins._STATE.discovered is False

        fn = runner._resolve_fn(spec)                       # ← 真实函数
        assert callable(fn)
        assert plugins._STATE.discovered is True            # 兜底确实触发了发现

    def test_resolve_fn_still_raises_when_task_truly_missing(self, env, monkeypatch):
        """真正不存在（也没插件提供）时，错误语义不变：KeyError。"""
        from myastro.io.jobs import runner
        from myastro.io.jobs.spec import JobSpec

        monkeypatch.delenv(plugins.ENV_VAR, raising=False)
        spec = JobSpec(source="x", params={}, task="no_such_task_anywhere")
        with pytest.raises(KeyError):
            runner._resolve_fn(spec)


@pytest.mark.cap("source.contract")
class TestUnresolvableTask:
    def test_missing_task_marks_job_failed_instead_of_killing_thread(self, env):
        """任务解析失败必须落成**作业失败**，而不是让工作线程带异常退出。

        真实风险：线程死掉后作业永远停在 `running`，只能靠孤儿巡检兜底。
        修法是把解析放进 `_run_job` 的 try 内（本次 2a-3 的顺带修复）。
        """
        import myastro as ma
        from myastro.io.jobs import JobSpec, fetch
        from myastro.io.jobs.spec import (
            JobFailed,  # kernel 层异常（门面才映射成 StateError）
        )

        spec = JobSpec(source="ghost", params={}, task="no_such_task_anywhere")
        with pytest.raises(JobFailed) as excinfo:
            fetch(spec, timeout=5)
        assert "no_such_task_anywhere" in str(excinfo.value)

        # 作业被标成 failed（而不是留在 running）
        rows = ma.status()
        assert rows and rows[-1]["status"] in ("failed", "orphaned")


# ── 2b：插件状态的可见性（来源标注 + doctor 展示）──────────────────────────────

@pytest.mark.cap("source.contract")
class TestOrigenVisibility:
    def test_builtin_sources_are_marked_builtin(self, env):
        import myastro as ma

        origins = {s["name"]: s["origin"] for s in ma.sources()}
        assert origins, "源清单为空"
        assert all(v == "builtin" for v in origins.values()), origins

    def test_plugin_sources_are_marked_with_module(self, plugin_env, monkeypatch, env):
        import myastro as ma

        name = plugin_env("origin_good", GOOD_PLUGIN)
        monkeypatch.setenv(plugins.ENV_VAR, name)
        origins = {s["name"]: s["origin"] for s in ma.sources()}
        assert origins["disc-demo"] == f"plugin:{name}"
        assert origins["tess"] == "builtin"          # 内置不受影响

    def test_runtime_registered_source_is_marked_runtime(self, env):
        """插件机制之外显式注册的源（如 notebook 里临时加的）标 runtime。"""
        import myastro as ma
        from myastro.descriptors import REGISTRY

        def _noop(ctx):
            raise RuntimeError("不该被调用")

        ma.register_task("origin_runtime_task", _noop)
        ma.register_source(ma.SourceDescriptor(
            name="origin-runtime", desc="临时源", product="parquet", status="ok",
            fields=[ma.FieldSpec("t", pattern=r"^\w+$")],
            task="origin_runtime_task", example_params={"t": "x"}))
        try:
            origins = {s["name"]: s["origin"] for s in ma.sources()}
            assert origins["origin-runtime"] == "runtime"
        finally:
            REGISTRY.pop("origin-runtime", None)
            from myastro.tasks import TASKS
            TASKS.pop("origin_runtime_task", None)


@pytest.mark.cap("source.contract")
class TestDoctorVisibility:
    def _plugin_checks(self) -> list[dict]:
        import myastro as ma

        return [c for c in ma.doctor() if "插件" in c["name"]]

    def test_reports_none_installed(self, env):
        (check,) = self._plugin_checks()
        assert check["status"] == "ok" and "未安装" in check["detail"]

    def test_reports_loaded_plugin(self, plugin_env, monkeypatch, env):
        name = plugin_env("doc_good", GOOD_PLUGIN)
        monkeypatch.setenv(plugins.ENV_VAR, name)
        checks = self._plugin_checks()
        assert any(c["status"] == "ok" and name in c["detail"] for c in checks), checks

    def test_reports_failure_with_reason_and_hint(self, plugin_env, monkeypatch, env):
        """失败插件必须在 doctor 里**可见**（类型 + 原因 + 建议），而不是被静默吞掉。"""
        name = plugin_env("doc_bad", BAD_REGISTER)
        monkeypatch.setenv(plugins.ENV_VAR, name)
        checks = self._plugin_checks()
        bad = [c for c in checks if c["status"] == "warn" and name in c["name"]]
        assert bad, checks
        assert "ParamError" in bad[0]["detail"] and "协议版本" in bad[0]["detail"]
        assert bad[0].get("fix"), "失败插件应给出修复建议"

    def test_hanging_plugin_is_reported_not_fatal(self, plugin_env, monkeypatch, env):
        """挂死插件：doctor 报 WARN，但 doctor 本身正常返回。"""
        name = plugin_env("doc_hang", HANGS)
        monkeypatch.setenv(plugins.ENV_VAR, name)
        monkeypatch.setattr(plugins, "PROBE_TIMEOUT", 1.0)
        checks = self._plugin_checks()
        warn = [c for c in checks if c["status"] == "warn"]
        assert warn and "ProbeTimeout" in warn[0]["detail"]
