"""补全走 Textual 原生 suggester 的测试（不自造交互）。

分层原则：本文件验证"我们把索引接进框架"这件事——
补全值由 `IndexSuggester` 提供，幽灵文本与接受键（→）由框架实现，
故这里既测适配器的规则，也测一次真实的 Input 端到端路径。
"""
from __future__ import annotations

import pytest

from myastro.io.top.suggest import IndexSuggester

KEYS = ["alpha-001", "alpha-002", "beta-1"]


@pytest.fixture
def synth_index(env):
    """合成索引（不依赖真实索引文件，避免 104MB 下载/环境差异）。"""
    import pandas as pd

    from myastro.io import index as idx

    idx.INDEXES["test-keys"] = {"desc": "合成测试索引", "key_col": "key"}
    try:
        pd.DataFrame({"key": KEYS}).to_parquet(
            idx.index_path("test-keys"), index=False)
        yield "test-keys"
    finally:
        idx.INDEXES.pop("test-keys", None)
        idx.index_path("test-keys").unlink(missing_ok=True)


@pytest.mark.cap("present.tui")
class TestIndexSuggester:
    @pytest.mark.asyncio
    async def test_partial_prefix_completes_to_first_key(self, synth_index):
        s = IndexSuggester(synth_index)
        assert await s.get_suggestion("alph") == "alpha-001"
        assert await s.get_suggestion("beta") == "beta-1"

    @pytest.mark.asyncio
    async def test_exact_key_yields_none(self, synth_index):
        """已经是完整键：不返回建议（框架只在更长时显示幽灵文本）。"""
        s = IndexSuggester(synth_index)
        assert await s.get_suggestion("alpha-001") is None

    @pytest.mark.asyncio
    async def test_no_match_yields_none(self, synth_index):
        s = IndexSuggester(synth_index)
        assert await s.get_suggestion("zzz") is None

    @pytest.mark.asyncio
    async def test_empty_value_yields_none(self, synth_index):
        s = IndexSuggester(synth_index)
        assert await s.get_suggestion("") is None

    @pytest.mark.asyncio
    async def test_missing_index_degrades_silently(self, env):
        """索引未构建：返回 None（普通输入框），不抛错、不打断输入。"""
        s = IndexSuggester("never-built")
        assert await s.get_suggestion("alph") is None


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
async def test_native_input_ghost_text_and_right_arrow(synth_index):
    """端到端：Textual Input 显示幽灵文本，→ 接受成完整值。

    这两步全部由框架完成——测试存在即证明我们没有自造补全 UI。
    """
    from textual.app import App, ComposeResult
    from textual.widgets import Input

    class _App(App):
        def compose(self) -> ComposeResult:
            yield Input(suggester=IndexSuggester(synth_index), id="f")

    app = _App()
    async with app.run_test() as pilot:
        fld = app.query_one("#f", Input)
        fld.focus()
        await pilot.pause()
        fld.value = "alph"
        await pilot.pause()
        await pilot.pause()                    # 等 suggester worker
        assert fld._suggestion == "alpha-001"  # 框架的幽灵文本状态
        await pilot.press("right")             # 框架的接受键
        await pilot.pause()
        assert fld.value == "alpha-001"
        assert fld._suggestion == ""


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
async def test_modal_indexed_fields_have_suggester(env):
    """模态里只有索引字段挂 suggester，其余字段不受影响。"""
    from textual.widgets import Input, Select

    from myastro.io.top import AstroTop

    app = AstroTop()
    async with app.run_test() as pilot:
        await pilot.press("1")
        await pilot.pause()
        await pilot.press("f1")
        await pilot.pause()
        app.screen.query_one("#source", Select).value = "ztf-meta"
        await pilot.pause()
        assert isinstance(app.screen.query_one("#f_field", Input).suggester,
                          IndexSuggester)
        assert app.screen.query_one("#f_ccdid", Input).suggester is None
