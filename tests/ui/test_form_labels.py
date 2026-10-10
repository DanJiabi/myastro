"""表单字段标签：每个输入控件左侧必须有字段名（placeholder 会随输入消失）。

用户报告：placeholder 身兼"字段名 + 示例"，一旦填写（或 F2 预填充/填示例
让值非空）就看不出这是什么字段。修法：左侧固定宽标签列 + 右侧控件；
placeholder 只留示例；必填字段标 `*`，模态顶部给出 `* = 必填` 说明。
"""
from __future__ import annotations

import pytest

from myastro.descriptors import REGISTRY

SOURCES = sorted(REGISTRY)


def _expected_labels(d) -> list[str]:
    """标签规范（独立于实现复述）：名称 + 必填星号 + 索引标记。

    必填 = 无默认值且非可选（与 FieldSpec.coerce 一致）；
    带 index 的字段必须标出"（索引）"——用户要在**输入前**看出哪些字段
    能补全/看候选，而不是靠记住哪个源带索引。
    """
    out = []
    for f in d.fields:
        name = f.label or f.name
        if f.default is None and not f.optional:
            name += " *"
        if f.index:
            name += "（索引）"
        out.append(name)
    return out


def _labels(screen) -> list[str]:
    return [str(lbl.content) for lbl in screen.query("#fields .field-label")]


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
@pytest.mark.parametrize("source", SOURCES)
async def test_every_field_has_a_label(env, source):
    """描述符声明的每个字段都必须有对应标签（防漏，参数化覆盖全部源）。"""
    from textual.widgets import Select

    from myastro.io.top import AstroTop

    app = AstroTop()
    async with app.run_test() as pilot:
        await pilot.press("1")
        await pilot.pause()
        await pilot.press("f1")
        await pilot.pause()
        app.screen.query_one("#source", Select).value = source
        await pilot.pause()
        assert _labels(app.screen) == _expected_labels(REGISTRY[source])


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
async def test_required_marker_matches_descriptor(env):
    """必填标记只加在真正的必填字段上（有默认值/可选的都不加）。"""
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
        labels = _labels(app.screen)
        assert any(x.startswith("目标名") and x.endswith("*") for x in labels)
        assert not any("扇区" in x and x.endswith("*") for x in labels)

        app.screen.query_one("#source", Select).value = "ztf"
        await pilot.pause()
        labels = _labels(app.screen)
        assert any(x.endswith("*") for x in labels)          # ffd 必填
        assert not any("ccdid" in x and x.endswith("*") for x in labels)


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
async def test_placeholder_holds_only_example(env):
    """placeholder 只放示例，不再重复字段名（避免与标签重复）。"""
    from textual.widgets import Input, Select

    from myastro.io.top import AstroTop

    app = AstroTop()
    async with app.run_test() as pilot:
        await pilot.press("1")
        await pilot.pause()
        await pilot.press("f1")
        await pilot.pause()
        app.screen.query_one("#source", Select).value = "ztf"
        await pilot.pause()
        ffd = app.screen.query_one("#f_ffd", Input).placeholder
        assert "20200219403889" in ffd
        assert "filefracday" not in ffd
        assert ffd.startswith("例：")


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
async def test_labels_survive_filled_values(env):
    """核心场景：值非空（F2 填示例/预填充）时字段名仍可读。"""
    from textual.widgets import Input, Select

    from myastro.io.top import AstroTop

    app = AstroTop()
    async with app.run_test() as pilot:
        await pilot.press("1")
        await pilot.pause()
        await pilot.press("f1")
        await pilot.pause()
        app.screen.query_one("#source", Select).value = "ztf"
        await pilot.pause()
        await pilot.press("f2")                       # 填示例 → 值全非空
        await pilot.pause()
        assert all(str(app.screen.query_one(f"#f_{f.name}", Input).value)
                   for f in REGISTRY["ztf"].fields if f.default is None)
        assert _labels(app.screen) == _expected_labels(REGISTRY["ztf"])


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
async def test_source_and_custom_fields_are_labelled(env):
    """源下拉与自定义模式（URL/文件名/mission）同样有标签。"""
    from textual.widgets import Select

    from myastro.io.top import AstroTop

    app = AstroTop()
    async with app.run_test() as pilot:
        await pilot.press("1")
        await pilot.pause()
        await pilot.press("f1")
        await pilot.pause()
        assert app.screen.query_one("#source", Select) is not None
        assert any(str(lbl.content) == "数据源"
                   for lbl in app.screen.query(".field-label"))
        assert str(app.screen.query_one("#hint").content).startswith("* = 必填")
        # 自定义模式（默认）
        assert _labels(app.screen) == ["URL *", "文件名", "mission"]
