"""设计守卫：注册表漂移、文档同步、边界规则、schema/描述符契约。

（测试分层重组迁移；断言未改动。）
"""
import pytest


class TestDescriptorContract:
    # 其余成员已拆分至：sources/test_gaia.py

    @pytest.mark.cap("source.registry")
    def test_descriptor_fields_cover_task_params(self):
        """描述符字段 ∪ example_params ∪ 可选缺省 = 任务可执行参数集。
        每个 task 源的 example_params 必须能过 validate（契约自洽）。"""
        from myastro.descriptors import REGISTRY

        for d in REGISTRY.values():
            if d.example_params:
                norm = d.validate(d.example_params)  # 不抛即自洽
                assert isinstance(norm, dict)


@pytest.mark.cap("source.registry")
def test_descriptors_cover_sources():
    from myastro.descriptors import REGISTRY
    from myastro.io.sources import SOURCES

    orderable = {
        n
        for n, s in SOURCES.items()
        if s["status"] == "ok" and n not in ("exoplanet", "manifest", "horizons")
    }
    assert orderable <= set(REGISTRY), f"缺描述符: {orderable - set(REGISTRY)}"

@pytest.mark.cap("source.registry")
def test_register_source_extension_point(env):
    """第三方扩展点必须可用：类型可构造、注册后立即可见、可撤销。

    放在守卫层的原因：清理需要写回 REGISTRY（内部对象），
    门面层禁止导入内部；而"扩展点是否真的能用"是设计要求，
    正是守卫要盯的东西。
    """
    import myastro as ma
    from myastro.descriptors import REGISTRY

    custom = ma.SourceDescriptor(
        name="my-test-src", desc="测试源", product="parquet", status="ok",
        fields=[ma.FieldSpec("x", int)], example_params={"x": 1})
    ma.register_source(custom)
    try:
        assert "my-test-src" in {r["name"] for r in ma.sources()}
        assert ma.describe("my-test-src")["desc"] == "测试源"
        # 描述符自洽：示例参数能过自身校验
        assert REGISTRY["my-test-src"].validate({"x": 1})["x"] == 1
    finally:
        REGISTRY.pop("my-test-src", None)

    with pytest.raises(ma.ParamError):
        ma.register_source("not-a-descriptor")     # 类型检查生效


@pytest.mark.cap("design.guards")
def test_task_registry_and_descriptors_agree():
    """TASKS ↔ 描述符的 task 必须双向一致（缺一边都是运行时才炸的隐患）。

    真实教训：gaia 的描述符没声明 `columns`，而实现硬取 `p["columns"]`
    —— 声明与实现的契约错位。任务名比参数更硬：写错就是"作业跑起来
    才报 KeyError"。URL_SOURCES 早就有这类守卫，TASKS 一直缺。
    """
    from myastro.descriptors import REGISTRY
    from myastro.tasks import TASKS

    referenced = {d.task for d in REGISTRY.values() if d.task}
    missing_impl = referenced - set(TASKS)
    assert not missing_impl, f"描述符引用了不存在的 task：{sorted(missing_impl)}"

    unreferenced = set(TASKS) - referenced
    assert not unreferenced, (
        f"TASKS 里定义了但没有任何描述符引用：{sorted(unreferenced)}"
        "（要么删掉，要么补描述符字段声明）")


@pytest.mark.cap("design.guards")
def test_every_task_source_is_orderable_in_sources_registry():
    """带 task 的源必须在 SOURCES 里登记为 python 执行器（面板/文档同源）。"""
    from myastro.descriptors import REGISTRY
    from myastro.io.sources import SOURCES

    bad = []
    for d in REGISTRY.values():
        if not d.task:
            continue
        entry = SOURCES.get(d.name)
        if entry is None or entry.get("executor_type") != "python":
            bad.append((d.name, entry and entry.get("executor_type")))
    assert not bad, f"描述符有 task 但 SOURCES 未登记为 python：{bad}"


@pytest.mark.cap("design.guards")
def test_path_feeding_fields_are_declared_safe():
    """会把参数拼进文件名/目录名的字段，必须声明 name_like 或 pattern。

    这张表是"契约不是事实描述"：新增源若引入新的名字型字段，必须
    在这里登记并标注——否则只能靠运行时兜底
    （tests/kernel/test_path_containment.py）在落盘时拦下。
    背景：`brick="../../x"` 曾能把产物写出数据根（实测已证）。
    """
    from myastro.descriptors import REGISTRY

    PATH_FEEDING = {
        # 源: (字段名, 依据)
        "legacy": [("brick", "文件名 tractor-<brick>.fits + dest_dir/legacy")],
        "ztf": [("ffd", "文件名 ztf_<ffd>_..._sciimg.fits")],
        "tess": [("target", "目录名 _slug(target)")],
        "mpc": [("target", "文件名 eph_<target>.parquet")],
    }
    missing = []
    for source, entries in PATH_FEEDING.items():
        d = REGISTRY.get(source)
        assert d is not None, f"{source} 不在 REGISTRY"
        by_name = {f.name: f for f in d.fields}
        for field, why in entries:
            f = by_name.get(field)
            assert f is not None, f"{source}.{field} 不存在（{why}）"
            if not (f.name_like or f.pattern):
                missing.append(f"{source}.{field}（{why}）")
    assert not missing, "以下会进路径的字段未声明 name_like/pattern：\n" + \
        "\n".join(missing)


@pytest.mark.cap("design.guards")
def test_marked_fields_actually_reject_traversal():
    """标注必须真的生效（防止标了但校验没接上）。"""
    from myastro.descriptors import REGISTRY

    for d in REGISTRY.values():
        for f in d.fields:
            if not (f.name_like or f.pattern):
                continue
            params = {x.name: (x.default if x.default is not None else 1)
                      for x in d.fields}
            params[f.name] = "../EVIL"
            with pytest.raises(ValueError):
                d.build_spec(params)
