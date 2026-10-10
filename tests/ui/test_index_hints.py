"""索引字段的预览提示：把"能不能补全、为什么不能"显式说出来。

用户报告"→ 好像没啥作用"——原因是编号型键（field 号 1–1776 密集整数）
输入本身就是合法键，没有可补的内容。修法不是改输入语义，而是让提示自解释：
可补全 / 已是有效值 / 无匹配 / 索引未构建，四种状态各有一句话。
"""
from __future__ import annotations

import pandas as pd
import pytest


@pytest.fixture
def legacy_index(env):
    """合成 brick 索引（名字型键，可演示"可补全"状态；不走 104MB 下载）。"""
    from myastro.io import index as idx

    path = idx.index_path("legacy-bricks")
    pd.DataFrame({"brickname": ["0001m002", "0001m005", "0002p010"],
                  "ra": [0.1, 0.2, 0.3], "dec": [0.0, 0.0, 0.0]}).to_parquet(
        path, index=False)
    yield path
    path.unlink(missing_ok=True)


async def _preview_for(source: str, field_id: str, value: str):
    from textual.widgets import Input, Select

    from myastro.io.top import AstroTop

    app = AstroTop()
    async with app.run_test() as pilot:
        await pilot.press("1")
        await pilot.pause()
        await pilot.press("f1")
        await pilot.pause()
        app.screen.query_one("#source", Select).value = source
        await pilot.pause()
        app.screen.query_one(f"#{field_id}", Input).value = value
        await pilot.pause()
        return str(app.screen.query_one("#preview").content)


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
async def test_hint_shows_completion_target(legacy_index):
    """可补全：明确写出补全目标与接受键。"""
    text = await _preview_for("legacy", "f_brick", "0001m0")
    assert "0001m0 → 0001m002" in text
    assert "→ 接受" in text
    assert "匹配 2" in text


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
async def test_hint_says_already_valid_for_numeric_key(env):
    """编号型键已是有效值：说明"无需补全"，并列出同前缀候选。

    这正是 ztf / ztf-meta 的常态——用户看到这句话就不会以为 → 坏了。
    """
    import myastro as ma

    ma.index_update("ztf-fields")
    text = await _preview_for("ztf-meta", "f_field", "67")
    assert "field 67 = 有效值" in text
    assert "无需补全" in text
    assert "→ 接受" not in text                  # 没有可接受的目标
    assert "670" in text and "673" in text       # 同前缀候选照旧列出


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
async def test_hint_reports_no_match(env):
    import myastro as ma

    ma.index_update("ztf-fields")
    text = await _preview_for("ztf-meta", "f_field", "9999")
    assert "无匹配" in text


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
async def test_hint_reports_missing_index(env):
    """索引未构建时给出确切命令，而不是静默无提示。"""
    text = await _preview_for("legacy", "f_brick", "0001")
    assert "索引未构建" in text and "index update legacy-bricks" in text


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
async def test_hint_unique_exact_value_has_no_extra_note(legacy_index):
    """唯一完整键：只说"有效值"，不再啰嗦"同前缀另有 N 个"。"""
    text = await _preview_for("legacy", "f_brick", "0002p010")
    assert "0002p010 = 有效值" in text
    assert "同前缀另有" not in text


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["legacy", "ztf", "ztf-meta", "tess"])
async def test_index_marker_only_on_indexed_fields(env, source):
    """标签上的「（索引）」只出现在真正带索引的字段上。"""
    from textual.widgets import Select

    from myastro.descriptors import REGISTRY
    from myastro.io.top import AstroTop

    app = AstroTop()
    async with app.run_test() as pilot:
        await pilot.press("1")
        await pilot.pause()
        await pilot.press("f1")
        await pilot.pause()
        app.screen.query_one("#source", Select).value = source
        await pilot.pause()
        labels = [str(lbl.content)
                  for lbl in app.screen.query(".field-label")][1:]  # 跳过数据源
        marked = [x for x in labels if "（索引）" in x]
        expected = [f.label or f.name for f in REGISTRY[source].fields
                    if f.index]
        assert len(marked) == len(expected), (
            f"{source}: 标记数 {len(marked)} ≠ 索引字段数 {len(expected)}")


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
async def test_index_usage_hint_shown_before_typing(env):
    """未输入时也要说明索引字段的用法（输入前即可见）。"""
    from textual.widgets import Select

    from myastro.io.top import AstroTop

    app = AstroTop()
    async with app.run_test() as pilot:
        await pilot.press("1")
        await pilot.pause()
        await pilot.press("f1")
        await pilot.pause()
        app.screen.query_one("#source", Select).value = "ztf-meta"
        await pilot.pause()
        text = str(app.screen.query_one("#preview").content)
        assert "field（索引 ztf-fields）" in text
        assert "→ 接受" in text


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
async def test_no_index_hint_for_sources_without_index(env):
    from textual.widgets import Select

    from myastro.io.top import AstroTop

    app = AstroTop()
    async with app.run_test() as pilot:
        await pilot.press("1")
        await pilot.pause()
        await pilot.press("f1")
        await pilot.pause()
        app.screen.query_one("#source", Select).value = "tess"
        await pilot.pause()
        assert "索引" not in str(app.screen.query_one("#preview").content)
        assert not [x for x in
                    (str(lbl.content) for lbl in app.screen.query(".field-label"))
                    if "（索引）" in x]
