"""设计守卫：注册表漂移、文档同步、边界规则、schema/描述符契约。

（测试分层重组迁移；断言未改动。）
"""
import pytest


@pytest.mark.cap("design.guards")
def test_top_imports_not_private():
    """守卫：top 不得导入内核私有符号（下划线开头）。"""
    import ast
    import pathlib

    for f in pathlib.Path("src/myastro/io/top").glob("*.py"):
        tree = ast.parse(f.read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom):
                names = [a.name for a in node.names]
            for n in names:
                assert not n.startswith("_"), f"{f.name} 导入了私有符号 {n}"
