"""刷新契约：按需重建 + 同步恢复滚动（用户报告的"闪屏"回归守卫）。

背景（真 pty 与合成器逐帧实测）：
- `clear()` + 重建会让 Textual 重绘整个部件区域：即使内容一字未改，
  每 2s tick 也向终端写 ~3.4KB。
- `clear()` 还会把滚动位置归零，而 `move_cursor` 的滚动要等下一次布局
  才生效 → 多出一帧"列表顶部"。**光标在视口外时 1 次刷新产生 2 帧**
  （0 → 58）＝每 2 秒跳顶一次；光标在视口内时只有 1 帧（滚动本来就是 0），
  所以"闪不闪"取决于选中项是否在可视范围内——用户观察完全正确。

本文件的断言直接数**帧**（钩 Compositor.render_update），这是唯一能
区分"重绘了但内容相同"与"根本没重绘"的判据。
"""
from __future__ import annotations

import json

import pytest

from myastro.io.db import DB


def _seed_jobs(env, n: int = 100):
    db = DB().init()
    for i in range(n):
        db.conn.execute(
            "INSERT INTO jobs(spec_json,executor,status,error)"
            " VALUES(?,?,?,?)",
            (json.dumps({"source": "legacy", "params": {"brick": f"0001m{i:03d}"},
                         "url": f"https://x/{i}.fits"}), "aria2", "done", ""))
    db.conn.commit()


def _frame_counter(app):
    """钩住合成器，返回 (frames 列表, 还原函数)。"""
    comp = app.screen._compositor
    orig = comp.render_update
    frames: list[int] = []

    def hooked(*a, **k):
        frames.append(app.query_one("#main").scroll_offset.y)
        return orig(*a, **k)

    comp.render_update = hooked
    return frames, lambda: setattr(comp, "render_update", orig)


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
async def test_unchanged_data_produces_no_frames(env):
    """② 内容签名短路：数据未变时刷新不产生任何帧（0 重绘）。"""
    _seed_jobs(env, 30)
    from myastro.io.top import AstroTop
    app = AstroTop()
    async with app.run_test(size=(100, 24)) as pilot:
        await pilot.press("1")
        await pilot.pause()
        frames, restore = _frame_counter(app)
        try:
            for _ in range(3):
                app.refresh_data()
                await pilot.pause()
        finally:
            restore()
        assert frames == [], f"数据未变却重绘了 {len(frames)} 帧"


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
async def test_changed_data_repaints_once(env):
    """有变化时必须刷新（短路不能把新数据挡在外面）。"""
    _seed_jobs(env, 30)
    from myastro.io.top import AstroTop
    app = AstroTop()
    async with app.run_test(size=(100, 24)) as pilot:
        await pilot.press("1")
        await pilot.pause()
        app.refresh_data()
        await pilot.pause()
        frames, restore = _frame_counter(app)
        try:
            db = DB().init()
            db.conn.execute("UPDATE jobs SET status='failed', error='boom'"
                            " WHERE id=(SELECT MAX(id) FROM jobs)")
            db.conn.commit()
            app.refresh_data()
            await pilot.pause()
        finally:
            restore()
        assert len(frames) == 1, f"变化应恰好重绘一次，实际 {len(frames)} 帧"
        row = app.query_one("#main").get_row_at(0)
        assert "failed" in str(row) or "boom" in str(row)


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
async def test_deep_scroll_repaint_keeps_viewport(env):
    """① 光标在视口外时，刷新只出 1 帧且滚动位置不变（不跳顶）。"""
    _seed_jobs(env, 100)
    from textual.widgets import DataTable

    from myastro.io.top import AstroTop
    app = AstroTop()
    async with app.run_test(size=(100, 24)) as pilot:
        await pilot.press("1")
        await pilot.pause()
        t = app.query_one("#main", DataTable)
        t.move_cursor(row=80)
        await pilot.pause()
        before = t.scroll_offset.y
        assert before > 0, "前置条件：需要真的滚起来"

        # 制造一次内容变化，强制走重建路径
        db = DB().init()
        db.conn.execute("UPDATE jobs SET error='x'"
                        " WHERE id=(SELECT MAX(id) FROM jobs)")
        db.conn.commit()
        frames, restore = _frame_counter(app)
        try:
            app.refresh_data()
            await pilot.pause()
        finally:
            restore()
        assert frames == [before], (
            f"重建应只出 1 帧且保持滚动 {before}，实际 {frames}")
        assert t.scroll_offset.y == before


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
async def test_pane_switch_and_sort_still_rebuild(env):
    """短路不能挡住面板切换 / 排序翻转（签名涵盖这些维度）。"""
    _seed_jobs(env, 5)
    from textual.widgets import DataTable

    from myastro.io.top import AstroTop
    app = AstroTop()
    async with app.run_test(size=(100, 24)) as pilot:
        await pilot.press("1")
        await pilot.pause()
        t = app.query_one("#main", DataTable)
        first_desc = t.get_row_at(0)[0]

        await pilot.press("s")                      # 升序
        await pilot.pause()
        assert t.get_row_at(0)[0] != first_desc, "排序未生效（被短路挡住）"

        await pilot.press("2")                      # 存储面板
        await pilot.pause()
        labels = [c.label.plain for c in t.columns.values()]
        assert labels and labels[0] != "job"
        await pilot.press("1")
        await pilot.pause()
        assert next(iter(c.label.plain for c in t.columns.values())) == "job"


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
async def test_storage_scan_is_cached_but_ledger_stays_live(env, monkeypatch):
    """磁盘实扫走 TTL 缓存（NFS 上 ~105ms/次），账本部分必须实时。

    为什么只缓存扫描：缓存整行会让"刚删掉的文件/刚下钻的目录"显示陈旧；
    只缓存 rglob 则在保住正确性的同时去掉每 2 秒的重复 I/O。
    """
    from pathlib import Path

    import myastro.io.top.panes as P
    root = Path(env) / "data"
    (root / "tess").mkdir(parents=True, exist_ok=True)
    (root / "tess" / "a.bin").write_bytes(b"x" * 10)

    from pathlib import Path as _Path

    scans = {"n": 0}
    real_rglob = _Path.rglob

    def counted_rglob(self, pattern):
        scans["n"] += 1                     # 数"真扫了几次"，不是调用了几次
        return real_rglob(self, pattern)

    monkeypatch.setattr(_Path, "rglob", counted_rglob)
    monkeypatch.setattr(P, "_DISK_SCAN", {})

    pane = P.StoragePane()
    pane.rows()
    pane.rows()
    pane.rows()
    assert scans["n"] == 1, f"TTL 内应只扫一次，实际 {scans['n']} 次"

    # TTL 过期后重扫
    monkeypatch.setattr(P, "_DISK_SCAN_TTL", 0.0)
    pane.rows()
    assert scans["n"] == 2

    # 账本部分实时：新增一条库记录（不做磁盘扫描）立刻出现在行里
    from myastro.io.db import DB
    db = DB().init()
    cur = db.conn.execute(
        "INSERT INTO datasets(source,target,params_json,cache_key)"
        " VALUES('gaia','G','{}','klive')")
    f = root / "gaia" / "new.parquet"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"y")
    db.conn.execute("INSERT INTO files(dataset_id,path,size,format)"
                    " VALUES(?,?,1,'parquet')", (cur.lastrowid, str(f)))
    db.conn.commit()
    missions = [r[0] for r in pane.rows()]
    assert "gaia" in missions, f"账本变化未实时反映：{missions}"


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
async def test_first_render_matches_after_rebuild(env):
    """首屏渲染必须与"重建之后"一致（本地资产文件名截断的真实回归）。

    背景：DataTable 的自动列宽在"只有列、还没有行"的首次布局时定下来，
    之后补行不会再触发一次有效布局——表现为首屏文件名截断、排序后才正常。
    此前每 2 秒的无条件重建掩盖了它；加了内容签名短路后变成持续截断
    （用户报告："第一次显示不全，重新排序一下就 OK"）。
    现在列宽在重建时按内容确定性算出，首屏即正确。
    """
    from pathlib import Path

    from textual.widgets import DataTable

    from myastro.io.db import DB
    from myastro.io.top import AstroTop

    root = Path(env) / "data"
    (root / "legacy").mkdir(parents=True, exist_ok=True)
    name = "tractor-0001m002_a_deliberately_long_filename_for_width.fits"
    f = root / "legacy" / name
    f.write_bytes(b"x")
    db = DB().init()
    cur = db.conn.execute(
        "INSERT INTO datasets(source,target,params_json,cache_key,ra,dec)"
        " VALUES('legacy','brick','{}','kw',0.1,-0.2)")
    db.conn.execute("INSERT INTO files(dataset_id,path,size,format)"
                    " VALUES(?,?,1,'fits')", (cur.lastrowid, str(f)))
    db.conn.commit()

    def row_text(t, i=1):
        return "".join(s.text for s in t.render_line(i))

    app = AstroTop()
    async with app.run_test(size=(100, 24)) as pilot:
        await pilot.press("2")
        await pilot.pause()
        await pilot.press("enter")            # 下钻 → 本地资产
        await pilot.pause()
        t = app.query_one("#main", DataTable)
        first = row_text(t)
        assert name in first, f"首屏文件名被截断：{first!r}"

        app.refresh_data()                    # 一次定时刷新
        await pilot.pause()
        assert row_text(t) == first, "刷新后与首屏不一致"

        await pilot.press("s")                # 排序 → 重建
        await pilot.pause()
        assert name in row_text(t), "排序后文件名应完整"


@pytest.mark.cap("present.tui")
def test_column_widths_are_deterministic_and_capped():
    """列宽工具：按内容测量、CJK 计 2 格、超长按上限截断。"""
    from myastro.io.top.app import COL_WIDTH_CAP, column_widths

    widths = column_widths(("a", "文件名"), [("x", "很长的中文名字"), ("yy", "b")])
    assert widths[0] == 4          # max(表头 1, 单元格 2) + 2
    assert widths[1] == 16         # "很长的中文名字" 7 个 CJK = 14 格 + 2
    capped = column_widths(("a",), [("x" * 500,)])
    assert capped == [COL_WIDTH_CAP]
