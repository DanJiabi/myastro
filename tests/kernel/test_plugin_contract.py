"""插件协议 v1：注册校验与离线端到端（`docs/plugin-api.md`）。

为什么在 kernel 层：要用真 SQLite 账本跑一次注册→取数→入账的完整路径。
反例逐条对应协议规则——**坏插件必须在注册时被拒，且报错指得出改哪儿**。
"""
from __future__ import annotations

import pytest

import myastro as ma
from myastro.descriptors import (
    BUILTIN_SOURCES,
    PLUGIN_API_VERSION,
    REGISTRY,
    FieldSpec,
    SourceDescriptor,
    validate_descriptor,
)
from myastro.tasks import BUILTIN_TASKS, TASKS


def _desc(**over) -> SourceDescriptor:
    base = {
        "name": "synth", "desc": "合成源（离线，测试用）", "product": "test-product",
        "status": "ok",
        "fields": [FieldSpec("target", label="目标名",
                             pattern=r"^[A-Za-z0-9 _-]{1,32}$")],
        "task": "synth_fetch",
        "example_params": {"target": "M31"},
    }
    base.update(over)
    return SourceDescriptor(**base)


def _synth_task(ctx: ma.RunContext) -> ma.FetchResult:
    """离线合成任务：写一个真 parquet 到 dest_dir 并返回路径。

    **只用公开 API**（`ma.write_parquet` / `ma.FetchResult`）——与
    `docs/plugin-api.md` 的示例一致。真实教训：0.4.0 发布后，按文档写的插件在
    已安装的 wheel 上直接失败（`module 'myastro' has no attribute 'write_parquet'`），
    因为当时的测试用的是内部导入路径，本地全绿。
    """
    import pandas as pd

    dest = ctx.dest_dir / "synth.parquet"
    ma.write_parquet(pd.DataFrame({"x": [1, 2, 3],
                                   "target": [ctx.params["target"]] * 3}), dest)
    return ma.FetchResult(paths=[dest], dataset_id=0, meta={"n": 3})


@pytest.fixture
def clean_registries():
    """注册会改全局表 → 用完必须还原，避免污染其它测试。"""
    reg, tasks = dict(REGISTRY), dict(TASKS)
    yield
    REGISTRY.clear(); REGISTRY.update(reg)
    TASKS.clear(); TASKS.update(tasks)


@pytest.mark.cap("source.contract")
class TestBuiltinUnchanged:
    """内置源是协议的参考实现：新校验必须全部通过（零变化保证）。"""

    def test_all_builtins_pass_validation(self):
        for d in REGISTRY.values():
            validate_descriptor(d)
        assert len(BUILTIN_SOURCES) == 10

    def test_builtin_lists_are_frozen_snapshots(self):
        from myastro.descriptors import builtin_registry
        assert set(builtin_registry()) == set(BUILTIN_SOURCES) == set(REGISTRY)
        assert BUILTIN_TASKS <= set(TASKS)


@pytest.mark.cap("source.contract")
class TestRejectsBadPlugins:
    """每条规则一个反例：注册时 fail-fast（而不是等到 fetch 才炸）。

    autouse fixture 先把 `synth_fetch` 注册好——否则每条用例都会被
    "任务不在 TASKS"抢先拒绝，测试就会**因为错误的理由通过**
    （实测：去掉 example_params 自洽性检查后，本类中对应用例仍是绿的）。
    """

    @pytest.fixture(autouse=True)
    def _synth_task_registered(self, clean_registries):
        ma.register_task("synth_fetch", _synth_task)

    @pytest.mark.parametrize("bad", ["Synth", "1synth", "syn th", "synth_", "a" * 33, ""])
    def test_rejects_invalid_name(self, bad, clean_registries):
        with pytest.raises(ma.ParamError, match="不合法"):
            ma.register_source(_desc(name=bad))

    @pytest.mark.parametrize("field,value", [("desc", "  "), ("product", "")])
    def test_rejects_empty_meta(self, field, value, clean_registries):
        with pytest.raises(ma.ParamError, match="不能为空"):
            ma.register_source(_desc(**{field: value}))

    def test_rejects_unknown_status(self, clean_registries):
        with pytest.raises(ma.ParamError, match="status"):
            ma.register_source(_desc(status="dreamy"))

    def test_rejects_duplicate_field_names(self, clean_registries):
        dup = [FieldSpec("target", pattern=r"^\w+$"), FieldSpec("target")]
        with pytest.raises(ma.ParamError, match="字段名重复"):
            ma.register_source(_desc(fields=dup, example_params={"target": "x"}))

    def test_rejects_bad_field_name(self, clean_registries):
        with pytest.raises(ma.ParamError, match="字段名"):
            ma.register_source(_desc(
                fields=[FieldSpec("Target Name", pattern=r"^.+$")],
                example_params={"Target Name": "x"}))

    def test_rejects_uncompilable_pattern(self, clean_registries):
        with pytest.raises(ma.ParamError, match="pattern 无法编译"):
            ma.register_source(_desc(
                fields=[FieldSpec("target", pattern="([")],
                example_params={"target": "x"}))

    def test_rejects_unknown_index(self, clean_registries):
        with pytest.raises(ma.ParamError, match="未知索引"):
            ma.register_source(_desc(
                fields=[FieldSpec("target", pattern=r"^\w+$", index="no-such-index")]))

    def test_rejects_no_executor(self, clean_registries):
        with pytest.raises(ma.ParamError, match="必须且只能"):
            ma.register_source(_desc(task=None))

    def test_rejects_both_executors(self, clean_registries):
        with pytest.raises(ma.ParamError, match="必须且只能"):
            ma.register_source(_desc(task="synth_fetch", url_key="legacy"))

    def test_rejects_unknown_task(self, clean_registries):
        with pytest.raises(ma.ParamError, match="不在 TASKS"):
            ma.register_source(_desc(task="typo_task"))

    def test_rejects_unknown_url_key(self, clean_registries):
        with pytest.raises(ma.ParamError, match="不在 URL_SOURCES"):
            ma.register_source(_desc(task=None, url_key="typo"))

    def test_url_key_source_requires_field_guard(self, clean_registries):
        """aria2 路径会把参数拼进 URL/文件名 → 字符串字段必须有防线。"""
        with pytest.raises(ma.ParamError, match="防路径穿越"):
            ma.register_source(_desc(
                task=None, url_key="legacy",
                fields=[FieldSpec("brick")],                 # 无 pattern/choices/name_like
                example_params={"brick": "0001m002"}))

    def test_rejects_missing_example_params(self, clean_registries):
        with pytest.raises(ma.ParamError, match="example_params"):
            ma.register_source(_desc(example_params={}))

    def test_rejects_inconsistent_example_params(self, clean_registries):
        """示例必须能通过自己的校验（这条能挡住绝大多数劣质插件）。"""
        with pytest.raises(ma.ParamError):
            ma.register_source(_desc(example_params={"target": "带/斜杠"}))

    def test_rejects_api_version_mismatch(self, clean_registries):
        with pytest.raises(ma.ParamError, match="插件协议版本"):
            ma.register_source(_desc(api_version=PLUGIN_API_VERSION + 98))

    def test_rejects_requires_without_install_hint(self, clean_registries):
        with pytest.raises(ma.ParamError, match="install_hint"):
            ma.register_source(_desc(requires=["somemod"]))

    def test_rejects_bad_probe_url(self, clean_registries):
        with pytest.raises(ma.ParamError, match="probe_url"):
            ma.register_source(_desc(probe_url="ftp://example.org"))

    def test_refuses_to_shadow_builtin_source(self, clean_registries):
        """内置源不可覆盖——连 replace=True 也不行。"""
        for replace in (False, True):
            with pytest.raises(ma.ParamError, match="不允许覆盖内置源"):
                ma.register_source(_desc(name="tess", task="synth_fetch"), replace=replace)

    def test_refuses_duplicate_plugin_without_replace(self):
        # 任务已由 autouse fixture 注册好
        ma.register_source(_desc())
        with pytest.raises(ma.ParamError, match="已注册"):
            ma.register_source(_desc())
        ma.register_source(_desc(desc="改过的描述"), replace=True)      # 显式替换可以
        assert REGISTRY["synth"].desc == "改过的描述"

    def test_failed_registration_leaves_registry_clean(self, clean_registries):
        before = dict(REGISTRY)
        with pytest.raises(ma.ParamError):
            ma.register_source(_desc(name="BadName"))
        assert REGISTRY == before, "失败的注册不能留下部分状态"


@pytest.mark.cap("source.contract")
class TestTaskRegistration:
    def test_rejects_bad_name(self, clean_registries):
        with pytest.raises(ma.ParamError, match="任务名"):
            ma.register_task("Bad Task", _synth_task)

    def test_rejects_non_callable(self, clean_registries):
        with pytest.raises(ma.ParamError, match="可调用"):
            ma.register_task("synth_fetch", 42)

    def test_refuses_to_shadow_builtin_task(self, clean_registries):
        for replace in (False, True):
            with pytest.raises(ma.ParamError, match="不允许覆盖内置任务"):
                ma.register_task("tess_lightcurve", _synth_task, replace=replace)

    def test_refuses_duplicate_task_without_replace(self, clean_registries):
        ma.register_task("synth_fetch", _synth_task)
        with pytest.raises(ma.ParamError, match="已注册"):
            ma.register_task("synth_fetch", _synth_task)
        ma.register_task("synth_fetch", _synth_task, replace=True)      # 显式替换


@pytest.mark.cap("source.contract")
class TestEndToEnd:
    def test_plugin_task_fetches_end_to_end(self, env, clean_registries):
        """注册 → 取数 → 落盘 → 入账本：插件走的是与内置源完全相同的路径。"""
        ma.register_task("synth_fetch", _synth_task)
        ma.register_source(_desc())

        result = ma.fetch("synth", target="M31")
        assert result.paths and result.paths[0].exists()
        assert result.paths[0].name == "synth.parquet"
        assert result.dataset_id > 0
        assert result.meta.get("n") == 3

        # 入账本且可检索（facet: 源名）
        found = ma.search(source="synth")
        assert found, "插件源的数据集必须出现在本地检索里"


@pytest.mark.cap("source.contract")
def test_plugin_does_not_perturb_guards_or_snapshot(env, clean_registries):
    """装插件不得让守卫/`--check` 变红：契约快照只绑内置。

    这是 1b 的核心性质——否则每个装插件的用户跑 `pytest` 都会看到假红，
    守卫立刻失去可信度。
    """
    from myastro import contract
    from myastro.descriptors import builtin_registry
    from myastro.tasks import BUILTIN_TASKS

    before_snapshot = contract.dumps()
    before_descriptors = set(builtin_registry())
    before_tasks = set(BUILTIN_TASKS)

    ma.register_task("synth_fetch", _synth_task)
    ma.register_source(_desc())

    assert contract.dumps() == before_snapshot, "插件注册改变了契约快照！"
    assert set(builtin_registry()) == before_descriptors
    assert set(BUILTIN_TASKS) == before_tasks
    assert not contract.problems()


@pytest.mark.cap("source.contract")
def test_plugin_doc_example_uses_public_api_only():
    """`docs/plugin-api.md` 里出现的 `ma.<名>` 必须都是公开导出。

    真实教训（0.4.0 发布后实测）：文档示例用了 `ma.write_parquet`，但它当时**没有公开**
    （藏在 `myastro.io.core`），于是按文档写的插件在已安装的 wheel 上直接失败：
    `module 'myastro' has no attribute 'write_parquet'`。
    本地测试全绿，因为测试自己走的是内部导入路径——文档与测试各说各话。
    这条守卫把"文档里的公开名"变成机检事实。
    """
    import pathlib
    import re

    text = pathlib.Path("docs/plugin-api.md").read_text()
    used = set(re.findall(r"\bma\.([A-Za-z_][A-Za-z0-9_]*)", text))
    assert used, "文档里没有出现任何 ma.<名>（示例被删了？）"
    missing = sorted(n for n in used if n not in ma.__all__)
    assert not missing, f"docs/plugin-api.md 引用了非公开名: {missing}"

    code = "\n".join(re.findall(r"```python\n(.*?)```", text, re.DOTALL))
    assert "from myastro.io" not in code, "示例代码不得导入内核私有模块（myastro.io.*）"
