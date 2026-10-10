"""能力地图守卫：测试 ↔ 设计（capabilities.md）的机器化绑定。

这些守卫是"测试对应真实需求"的可验证形式：
- 每个测试必须挂且只挂一个能力标记
- 标记 id 必须在注册表中（拼错即红，配合 pytest --strict-markers）
- 每个注册能力必须有测试（禁止无人证明的能力声明）
- capabilities.md 必须标注每个能力 id
- docs/test-map.md 必须与生成器一致（手改即红）
- 门面每个导出都必须被测试引用（第三方 API 无死角）
- 分层导入边界：facade/ 不得碰内核内部；unit/ 不得碰 db/网络/TUI
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from myastro.io import testmap

TESTS_DIR = pathlib.Path("tests")


@pytest.mark.cap("design.guards")
def test_every_test_has_exactly_one_capability():
    counts = testmap.all_markers()
    bad = {n: c for n, c in counts.items() if c != 1}
    assert not bad, f"cap 标记数不为 1 的测试：{bad}"


@pytest.mark.cap("design.guards")
def test_marker_ids_are_registered():
    used = set(testmap.collect())
    unknown = used - set(testmap.CAPABILITIES)
    assert not unknown, f"未注册的能力 id：{sorted(unknown)}"


@pytest.mark.cap("design.guards")
def test_every_capability_has_tests():
    missing = set(testmap.CAPABILITIES) - set(testmap.collect())
    assert not missing, f"没有测试的能力：{sorted(missing)}"


@pytest.mark.cap("design.guards")
def test_capabilities_doc_mentions_every_id():
    text = testmap.CAP_FILE.read_text()
    missing = [c for c in testmap.CAPABILITIES if f"cap:{c}" not in text]
    assert not missing, f"capabilities.md 缺标记：{missing}"


@pytest.mark.cap("design.guards")
def test_test_map_doc_is_generated():
    """docs/test-map.md 与生成器逐字一致（防手改/防漏更新）。"""
    assert testmap.DOC.exists(), "test-map.md 不存在：跑 myastro test-map"
    assert testmap.DOC.read_text() == testmap.render(), \
        "test-map.md 与生成器不一致：跑 myastro test-map"


@pytest.mark.cap("design.guards")
def test_facade_exports_all_referenced_by_tests():
    """门面 __all__ 的每个导出都至少被一个测试引用（第三方 API 无死角）。"""
    import myastro as ma

    referenced: set[str] = set()
    for f in TESTS_DIR.rglob("test_*.py"):
        tree = ast.parse(f.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and \
                    isinstance(node.value, ast.Name) and \
                    node.value.id == "ma":
                referenced.add(node.attr)
            # from myastro import X 形式
            if isinstance(node, ast.ImportFrom) and node.module == "myastro":
                referenced.update(a.name for a in node.names)
    exports = {n for n in ma.__all__ if not n.startswith("_")}
    uncovered = exports - referenced - {"__version__", "SCHEMA_VERSION"}
    assert not uncovered, f"门面导出无测试引用：{sorted(uncovered)}"


@pytest.mark.cap("design.guards")
def test_layer_import_boundaries():
    """facade 测试只碰公开 API；unit 测试不碰 db/网络/TUI。"""
    violations = []
    for f in (TESTS_DIR / "facade").rglob("test_*.py"):
        for node in ast.walk(ast.parse(f.read_text())):
            if isinstance(node, ast.ImportFrom) and \
                    (node.module or "").startswith("myastro."):
                violations.append(f"{f}: 门面测试导入了 {node.module}")
    for f in (TESTS_DIR / "unit").rglob("test_*.py"):
        for node in ast.walk(ast.parse(f.read_text())):
            mod = ""
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
            elif isinstance(node, ast.Import):
                mod = node.names[0].name
            if mod in ("sqlite3", "textual", "requests") or \
                    mod.startswith(("myastro.io.db", "myastro.io.jobs",
                                    "myastro.io.sources")):
                violations.append(f"{f}: 单元测试导入了 {mod}")
    assert not violations, "\n".join(violations)
