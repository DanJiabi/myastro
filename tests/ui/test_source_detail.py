"""TUI：选源详情面板 + Header 版本号。"""
from __future__ import annotations

import pytest


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
async def test_header_shows_version(env):
    """Header 副标题必须在**运行时**带版本号。

    初版实现把它放在 `SUB_TITLE` 类属性上，并配了一条只断言类属性的测试——
    测试全绿，但运行时 `refresh_data` 每次都用动态状态文本覆盖 sub_title，
    版本根本显示不出来（用户肉眼发现）。所以这条必须断言**运行后的实际值**。
    """
    from myastro import __version__
    from myastro.io.top import AstroTop

    app = AstroTop()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert __version__ in app.sub_title, (
            f"运行时 sub_title 里没有版本: {app.sub_title!r}")


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
async def test_source_detail_panel_follows_selection(env):
    """切换数据源时，详情面板必须同步显示该源的 detail 文本。"""
    from textual.widgets import Select, Static

    from myastro.io.top import AstroTop

    app = AstroTop()
    async with app.run_test() as pilot:
        await pilot.press("f1")
        await pilot.pause()

        def detail_text():
            return str(app.screen.query_one("#source-detail", Static).render())

        app.screen.query_one("#source", Select).value = "gaia"
        await pilot.pause()
        assert "Gaia DR3" in detail_text()

        app.screen.query_one("#source", Select).value = "mpc"
        await pilot.pause()
        assert "星历" in detail_text() and "Gaia DR3" not in detail_text()

        # 自定义 URL 给提示而不是报错
        app.screen.query_one("#source", Select).value = app.screen.CUSTOM
        await pilot.pause()
        assert "自定义 URL" in detail_text()
