"""TUI：p 键预览选中作业的首个文件。"""
from __future__ import annotations

import pytest


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
async def test_p_key_previews_selected_file(env_seeded):
    """作业面板按 p：详情面板显示该数据集首个文件的预览（parquet 嗅探）。"""
    import pandas as pd
    from textual.widgets import Static

    from myastro.io.db import DB
    from myastro.io.top import AstroTop

    # env_seeded 的文件是 4 字节假 parquet——换成真 parquet 让预览有内容
    db = DB().init()
    path = db.conn.execute("SELECT path FROM files LIMIT 1").fetchone()["path"]
    db.close()
    pd.DataFrame({"x": [1, 2, 3], "y": ["a", "b", "c"]}).to_parquet(path)

    app = AstroTop()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
        detail = str(app.query_one("#detail", Static).render())
        assert "【parquet】" in detail and "行数：3" in detail


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
async def test_p_key_without_file_notifies(env):
    """没有文件的选中项：提示而不是报错。"""
    from myastro.io.top import AstroTop

    app = AstroTop()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()   # 只要求不崩（空账本没有作业行）
