"""契约快照生成器（`src/myastro/io/contract.py`）。

守卫（`tests/guards/test_contract_snapshot.py`）负责"代码与仓库快照一致"；
这里测生成器本身：确定性、覆盖面、归一化、以及差异信息是否**指得出是哪一项**。
"""
from __future__ import annotations

import json

import pytest

from myastro import contract


@pytest.mark.cap("design.contract")
class TestSnapshot:
    def test_is_deterministic(self):
        """两次生成必须字节一致（否则守卫会假红）。"""
        assert contract.dumps() == contract.dumps()

    def test_covers_every_facade_export(self):
        import myastro as ma

        snap = contract.snapshot()
        assert sorted(snap["facade_api"]) == sorted(ma.__all__)
        for name, entry in snap["facade_api"].items():
            assert entry["kind"], name
        # 有参数的函数必须记下参数（契约的核心）
        assert snap["facade_api"]["fetch"].get("params")

    def test_cli_covers_nested_commands(self):
        """嵌套子命令（`fetch tess`、`schedule install`）同样是契约面。"""
        cmds = contract.snapshot()["cli"]["commands"]
        assert "fetch" in cmds and "test-map" in cmds
        assert "fetch tess" in cmds and "index update" in cmds
        assert "--check" in cmds["test-map"]

    def test_ledger_schema_matches_scene_version(self):
        from myastro.io.db import SCHEMA_VERSION

        snap = contract.snapshot()["ledger_schema"]
        assert snap["user_version"] == SCHEMA_VERSION
        assert {"datasets", "files", "jobs"} <= set(snap["tables"])
        cols = {c["name"] for c in snap["tables"]["jobs"]}
        assert {"id", "status", "dataset_id", "error_type"} <= cols

    def test_exit_codes_are_snapshotted(self):
        from myastro.cli import EXIT_CODES

        assert contract.snapshot()["exit_codes"] == dict(sorted(EXIT_CODES.items()))


@pytest.mark.cap("design.contract")
class TestNormalization:
    def test_memory_addresses_are_normalized(self):
        """默认值里的对象地址跨进程会变——不归一化守卫就会假红。"""
        assert "0xADDR" in contract._norm_default(object())
        assert "0x" not in contract._norm_default(object()).replace("0xADDR", "")

    def test_annotations_drop_module_prefixes(self):
        assert contract._norm_annotation("myastro.io.types.FetchResult") == "io.types.FetchResult"
        assert contract._norm_annotation("pathlib.Path") == "Path"
        assert contract._norm_annotation("") == ""


@pytest.mark.cap("design.contract")
class TestProblems:
    def _write(self, tmp_path, data):
        p = tmp_path / "snap.json"
        p.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True))
        return p

    def test_missing_file_is_reported(self, tmp_path):
        issues = contract.problems(tmp_path / "nope.json")
        assert issues and "缺少契约快照" in issues[0]

    def test_invalid_json_is_reported(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{ not json")
        assert "不是合法 JSON" in contract.problems(p)[0]

    def test_reports_added_removed_and_changed_items(self, tmp_path):
        """失败信息必须指得出**哪一项**变了、且方向正确，否则守卫等于没用。"""
        saved = contract.snapshot()
        # 代码里有、快照里没有 → 新增（开发者加了导出但忘了重新生成）
        shortened = dict(saved["facade_api"])
        missing = min(shortened)
        shortened.pop(missing)
        saved["facade_api"] = shortened
        # 快照里有、代码里没有 → 删除
        saved["exit_codes"] = {**saved["exit_codes"], "老错误": 9}
        # 双方都有但内容不同 → 变化
        saved["registries"] = dict(saved["registries"])
        saved["registries"]["url_sources"] = saved["registries"]["url_sources"][:1]

        text = "\n".join(contract.problems(self._write(tmp_path, saved)))
        assert f"facade_api.{missing}: 新增" in text
        assert "exit_codes.老错误: 删除" in text
        assert "registries.url_sources: 变化" in text
        assert "docs/contract-changelog.md" in text          # 给出下一步动作
