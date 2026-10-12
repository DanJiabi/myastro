"""`examples/myastro-source-example/` 必须真的能用（CI 与本机同一套断言）。

为什么单列一个测试文件：示例是**协议的门面**——文档说"照着抄就能跑"，
那就得有机器证明。此前 0.4.0 的教训正是"文档与测试各说各话"。
"""
from __future__ import annotations

import importlib
import pathlib
import sys

import pytest

import myastro as ma

EXAMPLE_SRC = (pathlib.Path(__file__).resolve().parents[2]
               / "examples" / "myastro-source-example" / "src")


@pytest.fixture
def example_plugin(monkeypatch):
    """把示例包挂到 sys.path 上导入（等价于 `pip install -e examples/...`）。"""
    monkeypatch.syspath_prepend(str(EXAMPLE_SRC))
    from myastro.descriptors import REGISTRY
    from myastro.tasks import TASKS

    reg, tasks = dict(REGISTRY), dict(TASKS)
    for name in ("myastro_example_source",):
        sys.modules.pop(name, None)
    module = importlib.import_module("myastro_example_source")   # 导入即注册
    yield module
    REGISTRY.clear(); REGISTRY.update(reg)
    TASKS.clear(); TASKS.update(tasks)
    sys.modules.pop("myastro_example_source", None)


@pytest.mark.cap("source.contract")
class TestExamplePlugin:
    def test_registers_source_and_task(self, example_plugin):
        assert example_plugin.SOURCE_NAME == "demo"
        assert "demo" in {s["name"] for s in ma.sources()}
        assert ma.describe("demo")["desc"].startswith("示例合成光变")

    def test_fetches_offline_and_lands_in_ledger(self, env, example_plugin):
        result = ma.fetch("demo", target="M31")
        assert result.paths[0].name == "M31.parquet"
        assert result.paths[0].exists()
        assert result.dataset_id > 0
        assert result.meta["n_points"] == 200

        frame = __import__("pandas").read_parquet(result.paths[0])
        assert list(frame.columns) == ["target", "phase", "flux", "source"]
        assert len(frame) == 200
        assert bool(ma.search(source="demo")), "示例源的数据必须能被本地检索到"

    def test_example_only_uses_public_api(self):
        """示例**代码**不得导入 `myastro.io.*`（协议禁止插件碰内核）。

        用 AST 看真实导入，而不是搜字符串：初版搜字符串时，示例文档里那句
        "不碰 `myastro.io.*`" 把测试自己弄红了（注释不是代码）。
        """
        import ast

        path = EXAMPLE_SRC / "myastro_example_source" / "__init__.py"
        tree = ast.parse(path.read_text())
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
        bad = [m for m in imported if m.startswith("myastro.io")]
        assert not bad, f"示例导入了内核私有模块：{bad}"
        assert any(m == "myastro" for m in imported), "示例应只依赖公开包 myastro"

    def test_example_declares_entry_point_for_batch2(self):
        """批次 2 的自动发现组名必须已在示例里声明（现在不生效，但别写错）。"""
        import tomllib

        pyproject = (EXAMPLE_SRC.parent / "pyproject.toml").read_text()
        data = tomllib.loads(pyproject)
        eps = data["project"]["entry-points"]["myastro.sources"]
        assert eps == {"demo": "myastro_example_source"}
