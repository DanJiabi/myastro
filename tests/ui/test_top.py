"""TUI：headless textual，真 widget；网络与作业启动打桩。

（测试分层重组迁移；断言未改动。）
"""

import pytest

from myastro.io.db import DB

"""TUI 冒烟测试：headless 渲染三面板，验证数据行进表。"""


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
async def test_top_renders_panels(env_seeded):
    """三个面板各有内容：0 数据源（注册表全量）/ 1 作业 / 2 存储。"""
    from myastro.io.sources import SOURCES
    from myastro.io.top import AstroTop

    app = AstroTop()
    async with app.run_test() as pilot:
        await pilot.pause()
        t = app.query_one("#main")
        assert "面板: 作业" in str(app.sub_title)  # 默认 jobs
        assert t.row_count >= 1

        await pilot.press("2")  # storage
        await pilot.pause()
        assert "面板: 存储" in str(app.sub_title)
        assert t.row_count >= 2  # tess + "(目录实扫)" 行

        await pilot.press("0")  # info：注册表全量
        await pilot.pause()
        assert "面板: 数据源" in str(app.sub_title)
        assert t.row_count == len(SOURCES)

        await pilot.press("1")  # 回 jobs
        await pilot.pause()
        assert "面板: 作业" in str(app.sub_title)


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
async def test_cursor_survives_refresh(env_seeded):
    # 补足行数让光标可移动
    db = DB().init()
    for i in range(4):
        db.conn.execute(
            "INSERT INTO jobs(spec_json,executor,status) VALUES('{}','aria2','done')"
        )
    db.conn.commit()

    from myastro.io.top import AstroTop

    app = AstroTop()
    async with app.run_test() as pilot:
        await pilot.pause()
        t = app.query_one("#main")
        assert t.row_count >= 5
        await pilot.press("down")
        await pilot.press("down")
        before = t.cursor_row
        assert before == 2
        app.refresh_data()  # 模拟 2s 定时刷新
        await pilot.pause()
        assert t.cursor_row == before  # 光标不被重置回 0


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
async def test_info_panel(env_seeded):
    from myastro.io.top import AstroTop

    app = AstroTop()
    async with app.run_test() as pilot:
        await pilot.press("0")
        await pilot.pause()
        from myastro.io.sources import SOURCES

        t = app.query_one("#main")
        assert t.row_count == len(SOURCES)  # 注册表全量，非"至少几条"
        # enter 展开示例
        await pilot.press("enter")
        detail = str(app.query_one("#detail").content)
        assert "示例" in detail and "tess_lightcurve" in detail
        # 光标在 info 面板同样受保护
        await pilot.press("down")
        app.refresh_data()
        await pilot.pause()
        assert t.cursor_row == 1


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
async def test_detail_cleared_on_pane_switch(env_seeded):
    from myastro.io.top import AstroTop

    app = AstroTop()
    async with app.run_test() as pilot:
        await pilot.press("0")
        await pilot.press("enter")
        assert "示例" in str(app.query_one("#detail").content)
        await pilot.press("1")  # 切到 jobs
        assert str(app.query_one("#detail").content) == ""


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
async def test_drill_down_to_assets(env_seeded):
    from myastro.io.top import AstroTop

    app = AstroTop()
    async with app.run_test() as pilot:
        await pilot.press("2")
        await pilot.pause()
        t = app.query_one("#main")
        # 光标到体积最大的 mission 行（env 只有 tess）
        await pilot.press("enter")
        await pilot.pause()
        assert app.pane == "assets" and app.drill_source == "tess"
        t = app.query_one("#main")
        assert t.row_count >= 1  # env 造的 tess dataset
        row = t.get_row_at(0)
        assert row[0] == 1 and row[3] == "✓"  # 文件在盘
        await pilot.press("escape")
        await pilot.pause()
        assert app.pane == "storage" and app.drill_source is None


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
async def test_drill_esc_restores_cursor(env_seeded):
    """下钻再返回：光标回到**下钻时那一行**（非行号 0）。"""
    db = DB().init()
    f = env_seeded / "data" / "gaia" / "cone.parquet"  # 第二个 mission
    f.parent.mkdir(parents=True)
    f.write_bytes(b"DATA")
    cur = db.conn.execute(
        "INSERT INTO datasets(source,target,params_json,cache_key)"
        " VALUES('gaia','G','{}','kg')"
    )
    db.conn.execute(
        "INSERT INTO files(dataset_id,path,size,format) VALUES(?,?,4,'parquet')",
        (cur.lastrowid, str(f)),
    )
    db.conn.commit()

    from myastro.io.top import AstroTop

    app = AstroTop()
    async with app.run_test() as pilot:
        await pilot.press("2")  # storage
        await pilot.pause()
        t = app.query_one("#main")
        assert t.row_count >= 3  # 两个 mission + 实扫行
        await pilot.press("down")  # 移到第 1 行（非 0）
        await pilot.pause()
        origin = t.cursor_row
        assert origin == 1
        mission = t.get_row_at(origin)[0]
        await pilot.press("enter")
        await pilot.pause()
        assert app.pane == "assets"
        await pilot.press("escape")
        await pilot.pause()
        assert app.pane == "storage"
        assert t.cursor_row == origin, "返回后应回到下钻行"
        assert t.get_row_at(t.cursor_row)[0] == mission


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
async def test_assets_view_via_drill(env_seeded):
    """storage enter 下钻资产视图：文件状态 + enter 钻参数（时间线面板已裁撤）。"""
    from myastro.io.top import AstroTop

    app = AstroTop()
    async with app.run_test() as pilot:
        await pilot.press("2")  # storage
        await pilot.pause()
        t = app.query_one("#main")
        target = next(i for i in range(t.row_count) if t.get_row_at(i)[0] == "tess")
        for _ in range(target):
            await pilot.press("down")
        await pilot.press("enter")  # 下钻
        await pilot.pause()
        assert app.pane == "assets"
        row = t.get_row_at(0)
        assert row[0] == 1 and row[3] == "✓"  # assets 列未变
        await pilot.press("enter")  # 钻参数
        detail = str(app.query_one("#detail").content)
        assert "params" in detail


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
async def test_drill_by_path_prefix(env_seeded):
    """storage 下钻按目录前缀（目录名 ≠ source 名也能命中）。"""
    db = DB().init()
    f = env_seeded / "data" / "legacy" / "dr10" / "t.fits"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"FITS")
    cur = db.conn.execute(
        "INSERT INTO datasets(source,target,params_json,cache_key)"
        " VALUES('legacy-surveys','t','{}','k9')"
    )
    db.conn.execute(
        "INSERT INTO files(dataset_id,path,size,format) VALUES(?,?,4,'fits')",
        (cur.lastrowid, str(f)),
    )
    db.conn.commit()

    from myastro.io.top import AstroTop

    app = AstroTop()
    async with app.run_test() as pilot:
        await pilot.press("2")
        await pilot.pause()
        t = app.query_one("#main")
        target = next(i for i in range(t.row_count) if t.get_row_at(i)[0] == "legacy")
        for _ in range(target):
            await pilot.press("down")
        await pilot.press("enter")
        await pilot.pause()
        assert app.pane == "assets" and app.drill_source == "legacy"
        t = app.query_one("#main")
        assert t.row_count >= 1  # source 名不同也能按目录命中
        assert t.get_row_at(0)[0] == cur.lastrowid


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
async def test_sort_toggle(env_seeded):
    # 补两条 jobs 使方向可辨
    db = DB().init()
    cur = db.conn.execute(
        "INSERT INTO jobs(spec_json,executor,status) VALUES('{}','aria2','done')"
    )
    db.conn.commit()
    jobs_row = cur.lastrowid

    from myastro.io.top import AstroTop

    app = AstroTop()
    async with app.run_test() as pilot:
        await pilot.press("1")  # jobs 面板
        await pilot.pause()
        t = app.query_one("#main")
        assert t.row_count == 2
        first_desc = t.get_row_at(0)[0]
        assert first_desc == f"#{jobs_row}"  # 降序：新的在上
        await pilot.press("s")  # 切升序
        await pilot.pause()
        first_asc = t.get_row_at(0)[0]
        assert first_asc < first_desc  # id 变小
        await pilot.press("s")  # 切回
        await pilot.pause()
        assert t.get_row_at(0)[0] == first_desc


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
async def test_sort_keeps_cursor_on_item(env_seeded):
    """s 翻转排序后，光标跟随原条目而非停留在原行号。"""
    db = DB().init()
    db.conn.execute(
        "INSERT INTO jobs(spec_json,executor,status) VALUES('{}','aria2','done')"
    )
    db.conn.commit()
    from myastro.io.top import AstroTop

    app = AstroTop()
    async with app.run_test() as pilot:
        await pilot.press("1")  # jobs（降序：新在上）
        await pilot.pause()
        t = app.query_one("#main")
        assert t.row_count >= 2
        old_id = t.get_row_at(0)[0]
        await pilot.press("s")  # 切升序
        await pilot.pause()
        assert t.get_row_at(0)[0] != old_id  # 首行确实换了
        assert t.get_row_at(t.cursor_row)[0] == old_id  # 光标仍锚定原条目


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
async def test_detail_consistent_after_sort(env_seeded):
    """enter → s → enter：详情必须仍是同一条目（行号在两个顺序中语义一致）。"""
    db = DB().init()
    db.conn.execute(
        "INSERT INTO jobs(spec_json,executor,status) VALUES('{}','aria2','done')"
    )
    db.conn.execute(
        "INSERT INTO jobs(spec_json,executor,status) VALUES('{}','aria2','failed')"
    )
    db.conn.commit()
    from myastro.io.top import AstroTop

    app = AstroTop()
    async with app.run_test() as pilot:
        await pilot.press("1")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        d1 = str(app.query_one("#detail").content)
        await pilot.press("s")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        d2 = str(app.query_one("#detail").content)
        assert d1 == d2


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
async def test_drill_esc_identity_restore(env_seeded):
    """下钻返回按 mission 名找行——下钻期间行序翻转也不落错行。

    场景设计成**能区分三种实现**：
      gaia 体积大 → 首行 gaia；下钻 gaia（第 0 行）；
      期间 gaia 体积缩到最小 → 返回重排后 gaia 落到第 1 行。
    - 按身份恢复 → 第 1 行（gaia）✓
    - 硬编码回第 0 行 → 落在 tess ✗
    - 沿用原行号 0 → 落在 tess ✗
    """
    db = DB().init()
    big = env_seeded / "data" / "gaia" / "big.parquet"
    big.parent.mkdir(parents=True)
    big.write_bytes(b"X" * 1_000_000)
    cur = db.conn.execute(
        "INSERT INTO datasets(source,target,params_json,cache_key)"
        " VALUES('gaia','G','{}','kbig')"
    )
    db.conn.execute(
        "INSERT INTO files(dataset_id,path,size,format) VALUES(?,?,?, 'parquet')",
        (cur.lastrowid, str(big), big.stat().st_size),
    )
    db.conn.commit()

    from myastro.io.top import AstroTop

    app = AstroTop()
    async with app.run_test() as pilot:
        await pilot.press("2")  # storage
        await pilot.pause()
        t = app.query_one("#main")
        assert t.get_row_at(0)[0] == "gaia"  # 体积降序：gaia 在首行
        origin_row = t.cursor_row
        assert origin_row == 0

        await pilot.press("enter")  # 下钻 gaia
        await pilot.pause()
        assert app.pane == "assets" and app.drill_source == "gaia"

        # 下钻期间 gaia 体积缩到最小（返回时重排：gaia 落到 tess 之后）
        db.conn.execute("UPDATE files SET size=1 WHERE path LIKE '%big.parquet'")
        db.conn.commit()

        await pilot.press("escape")
        await pilot.pause()
        assert app.pane == "storage"
        assert t.get_row_at(1)[0] == "gaia", "前提：重排后 gaia 应在第 1 行"
        assert t.get_row_at(t.cursor_row)[0] == "gaia", (
            "返回必须按身份落回 gaia（回第 0 行会落到 tess）"
        )
        assert t.cursor_row == 1


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
async def test_refresh_anchors_cursor_identity(env_seeded):
    """定时刷新遇到行序变化（storage 体积重排）光标仍锚定原条目。"""
    from myastro.io.top import AstroTop

    app = AstroTop()
    async with app.run_test() as pilot:
        await pilot.press("2")  # storage
        await pilot.pause()
        t = app.query_one("#main")
        on_tess = t.get_row_at(t.cursor_row)[0] == "tess"
        if not on_tess:  # 移到 tess 行
            target = next(i for i in range(t.row_count) if t.get_row_at(i)[0] == "tess")
            for _ in range(target):
                await pilot.press("down")
        key = t.get_row_at(t.cursor_row)[0]
        app.refresh_data()  # 模拟 2s 定时刷新
        await pilot.pause()
        assert t.get_row_at(t.cursor_row)[0] == key


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
async def test_jobs_filter_cycle(env_seeded):
    """f 键循环过滤；过滤后身份寻址的 r/x/enter 不受影响。"""
    db = DB().init()
    for st in ("done", "failed", "running"):
        db.conn.execute(
            f"INSERT INTO jobs(spec_json,executor,status) VALUES('{{}}','aria2','{st}')"
        )
    db.conn.commit()
    from myastro.io.top import AstroTop

    app = AstroTop()
    async with app.run_test() as pilot:
        await pilot.press("1")
        await pilot.pause()
        t = app.query_one("#main")
        assert t.row_count == 4  # env 1 done + 3 条
        await pilot.press("f")  # active
        await pilot.pause()
        rows = [t.get_row_at(i)[2] for i in range(t.row_count)]
        assert set(rows) == {"running"}
        assert "过滤: active" in str(app.sub_title)
        await pilot.press("f")  # failed
        await pilot.pause()
        rows = [t.get_row_at(i)[2] for i in range(t.row_count)]
        assert set(rows) == {"failed"}
        await pilot.press("f")  # done
        await pilot.press("f")  # all
        await pilot.pause()
        assert t.row_count == 4


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
async def test_jobs_outcome_columns(env_seeded):
    """产出列显示 dataset 的 target/体积与文件在盘状态。"""
    from myastro.io.top import AstroTop

    app = AstroTop()
    async with app.run_test() as pilot:
        await pilot.press("1")
        await pilot.pause()
        t = app.query_one("#main")
        row = t.get_row_at(0)  # env: done python job 有 dataset
        assert row[3] == "lc.parquet 4 B ✓"


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
async def test_new_job_modal(env, monkeypatch):
    """n → 模态输入 → 提交：aria2 作业入队（daemon 不启动，仅验证链路）。"""
    submitted = []

    def fake_start(db, job_id, spec, key):
        submitted.append(spec.url)

    monkeypatch.setattr("myastro.io.jobs.runner._start_aria2_job", fake_start)
    from textual.widgets import Input

    from myastro.io.top import AstroTop

    app = AstroTop()
    async with app.run_test() as pilot:
        await pilot.press("1")
        await pilot.pause()
        await pilot.press("f1")
        await pilot.pause()
        app.screen.query_one("#url", Input).focus()  # 初始焦点在源下拉
        await pilot.pause()
        app.screen.query_one("#url", Input).value = "https://x/f.fits"
        await pilot.press("enter")  # url → 下一项
        await pilot.pause()
        app.screen.query_one("#name", Input).value = ""
        await pilot.press("enter")  # name → 下一项
        await pilot.pause()
        await pilot.press("enter")  # mission 最后一项回车 = 提交
        await pilot.pause()
        assert submitted == ["https://x/f.fits"]
        from myastro.io.db import DB

        db = DB().init()
        row = db.conn.execute(
            "SELECT executor, dest FROM jobs ORDER BY id DESC"
        ).fetchone()
        assert row["executor"] == "aria2"
        assert row["dest"].endswith("quick/f.fits")

        # ESC 取消路径：打开模态 → 填内容 → ESC → 模态关闭且不产生任何作业
        n_before = db.conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"]
        submitted.clear()
        await pilot.press("f1")
        await pilot.pause()
        assert type(app.screen).__name__ == "NewJobScreen"
        app.screen.query_one("#url", Input).value = "https://x/cancelled.fits"
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert type(app.screen).__name__ != "NewJobScreen", "ESC 应关闭模态"
        n_after = db.conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"]
        assert n_after == n_before, "ESC 取消不应产生作业"
        assert submitted == [], "ESC 取消不应触发下载"


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
async def test_new_job_registry_source(env, monkeypatch):
    """选注册源（legacy）→ 参数派生 URL/文件名，无需手填。"""
    submitted = []

    def fake_start(db, job_id, spec, key):
        submitted.append((spec.url, spec.dest))

    monkeypatch.setattr("myastro.io.jobs.runner._start_aria2_job", fake_start)
    from textual.widgets import Input, Select

    from myastro.io.top import AstroTop

    app = AstroTop()
    async with app.run_test() as pilot:
        await pilot.press("1")
        await pilot.pause()
        await pilot.press("f1")
        await pilot.pause()
        app.screen.query_one("#source", Select).value = "legacy"
        await pilot.pause()
        brick = app.screen.query_one("#f_brick", Input)
        brick.value = "0001m002"
        await pilot.pause()
        preview = str(app.screen.query_one("#preview").content)
        assert "portal.nersc.gov" in preview
        assert "tractor-0001m002.fits" in preview  # 文件名自动派生
        await pilot.press("enter")  # 唯一字段回车 = 提交
        await pilot.pause()
        assert submitted and submitted[0][0].endswith("tractor-0001m002.fits")
        assert submitted[0][1].endswith("legacy/tractor-0001m002.fits")


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
async def test_index_candidates_preview(env):
    """索引字段：候选在预览区实时显示（无需按键）。"""
    from textual.widgets import Input, Select

    import myastro as ma
    from myastro.io.top import AstroTop

    ma.index_update("ztf-fields")                 # builder 型，本地构造
    app = AstroTop()
    async with app.run_test() as pilot:
        await pilot.press("1")
        await pilot.pause()
        await pilot.press("f1")
        await pilot.pause()
        app.screen.query_one("#source", Select).value = "ztf-meta"
        await pilot.pause()
        app.screen.query_one("#f_field", Input).value = "67"
        await pilot.pause()
        preview = str(app.screen.query_one("#preview").content)
        # 编号型键输入即有效：提示写明"无需补全"，候选照旧列出
        assert "有效值" in preview and "670" in preview


@pytest.mark.cap("present.tui")
@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["legacy", "ztf", "ztf-meta"])
async def test_tab_advances_focus_on_indexed_fields(env, source):
    """回归：索引字段上 Tab 必须正常流转（此前被自造的补全吞掉）。

    用户报告：legacy/ztf/ztf-meta 对话框里 Tab 卡在索引字段上。
    现在 Tab 交还框架默认（focus_next），环必须完整。
    """
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

        n_fields = len(list(app.screen.query("#fields Input")))
        start = app.screen.focused.id
        seq = []
        for _ in range(n_fields + 1):             # 字段数 + 1 个控件 = 一整圈
            seq.append(app.screen.focused.id if app.screen.focused else None)
            await pilot.press("tab")
            await pilot.pause()
        assert len(set(seq)) == len(seq), f"焦点重复（卡住）: {seq}"
        assert app.screen.focused.id == start, f"未绕回起点: {seq} → {app.screen.focused.id}"
