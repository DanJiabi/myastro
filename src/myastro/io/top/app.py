"""App 框架：面板切换/光标锚定/下钻返回/键位路由，零面板业务。"""
from __future__ import annotations

from typing import ClassVar

from textual.app import App, ComposeResult
from textual.widgets import DataTable, Footer, Header, Static

from .. import aria2, jobs
from .batchscreen import BatchScreen
from .panes import PANE_KEYS, PANES, REFRESH_S, AssetsPane, JobsPane, Pane
from .screens import NewJobScreen

# 列宽上限：超过则按单元格省略号截断（表格横向可滚动，不影响取数）
COL_WIDTH_CAP = 60


def column_widths(cols, rows, cap: int = COL_WIDTH_CAP) -> list[int]:
    """按内容测量列宽（确定性），替代 DataTable 的自动列宽。

    为什么必须自己测：DataTable 的自动列宽在**首次布局（只有列、还没有行）**
    时按表头宽度定下来，之后补行不会再触发一次有效布局——表现为"本地资产
    首屏文件名被截断，排序（重建）后才正常"。这个时机问题与框架内部状态
    有关，实测 refresh(layout=True)/clear_cached_dimensions() 均无效。

    改成确定性宽度后：首屏、排序后、任何重建后的渲染完全一致；顺带消除
    "出现更长的值时整表列宽跳动"。用 Rich 的 cell_len 计宽（CJK 算 2 格）。
    """
    from rich.cells import cell_len

    widths = []
    for i, name in enumerate(cols):
        w = cell_len(str(name))
        for row in rows:
            if i < len(row):
                w = max(w, cell_len(str(row[i])))
        widths.append(min(w + 2, cap))          # +2 留一格内边距
    return widths


def _pkg_version() -> str:
    """版本号：走包元数据（不导入包根——守卫禁止 io/top 导入私有符号）。"""
    from importlib.metadata import PackageNotFoundError, version
    try:
        return version("myastro")
    except PackageNotFoundError:
        return "0.0.0+dev"


class AstroTop(App):
    TITLE = "myastro top"
    DEFAULT_CSS = """
    #main { height: 1fr; }
    #detail-wrap {
        height: auto; max-height: 14;
        border: round $accent;
        margin: 0 1 1 1;
    }
    #detail { padding: 0 1; }
    """
    BINDINGS: ClassVar[list] = [
        ("f4", "quit", "退出"),
        ("f5", "retry", "重试"),
        ("x", "cancel", "取消(aria2)"),
        ("s", "sort", "排序"),
        ("f", "filter", "过滤"),
        ("p", "preview", "预览"),
        ("f1", "new_job", "新建下载"),
        ("f2", "new_job_prefill", "预填充下载"),
        ("f12", "batch", "批量下单"),
        ("delete,backspace", "delete_job", "删除选中"),  # Mac 键盘无独立 Del，delete 键即 backspace
        ("shift+d", "delete_shown", "删过滤集"),
        ("escape", "back", "返回"),
        *[(k, f"pane('{v}')", PANES[v].label) for k, v in PANE_KEYS.items()],
    ]

    def __init__(self) -> None:
        super().__init__()
        self._pane_name = "jobs"
        self._assets = AssetsPane()         # 下钻专用实例（带 source）
        self._drill_origin_key = None       # 下钻起点的条目身份（mission 名）
        self._sort_desc = {"jobs": True, "assets": True}
        self._frame_sig = None          # 上一帧的内容签名（刷新短路用）

    # ── 面板状态 ──
    @property
    def pane(self) -> str:                  # 兼容既有测试/文档
        return self._pane_name

    @property
    def drill_source(self) -> str | None:
        return self._assets.source

    def _pane(self) -> Pane:
        return self._assets if self._pane_name == "assets" \
            else PANES[self._pane_name]

    def enter_assets(self, source: str) -> None:
        """由 StoragePane.drill 调用：进入单源资产视图。

        记住的是条目身份（mission 名）而非行号——storage 按体积动态
        重排，行号在返回时可能已指向别的 mission。
        """
        self._drill_origin_key = source
        self._assets.source = source
        self._pane_name = "assets"
        self._clear_detail()
        self.refresh_data()

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="main", cursor_type="row", zebra_stripes=True)
        from textual.containers import VerticalScroll
        with VerticalScroll(id="detail-wrap"):
            yield Static("", id="detail")
        yield Footer()

    def on_mount(self) -> None:
        self._try_english_ime()
        t = self.query_one("#main", DataTable)
        t.focus()
        self.query_one("#detail", Static).border_title = \
            "详情（enter 展开 / esc 关闭）"
        self.set_interval(REFRESH_S, self.refresh_data)
        self.refresh_data()

    @staticmethod
    def _try_english_ime() -> None:
        """尽力把输入法切到英文（macOS 需 macism；终端应用无系统 API）。

        未安装 macism 时静默跳过——这是 best-effort 便利，不是功能依赖。
        """
        import shutil
        import subprocess
        if shutil.which("macism"):
            try:
                subprocess.run(
                    ["macism", "com.apple.keylayout.ABC"],
                    capture_output=True, timeout=3, check=False)
            except Exception:                  # noqa: BLE001, S110
                pass        # 尽力而为：切输入法是便利，不是功能依赖


    # ── 渲染 ──
    def refresh_data(self) -> None:
        """按需重建表格：内容未变则完全不碰（不产生任何帧）。

        两条来自实测的规则（见 design-top §2 的刷新契约）：
        1. **内容签名短路**：行内容/列/面板/排序/过滤都没变 → 直接返回。
           否则 `clear()` + 重建会使 Textual 重绘整个部件区域
           （实测每 tick ~3.4KB 终端写入，即使一个字符都没变）。
        2. **同步恢复滚动**：`clear()` 会把滚动位置归零，而 `move_cursor`
           的滚动要等下一次布局才生效——中间会多出一帧"列表顶部"。
           实测：光标在视口外时 1 次刷新产生 **2 帧**（0 → 58），每 2 秒
           跳顶一次＝闪屏；光标在视口内时只有 1 帧（滚动本来就是 0），
           所以"闪不闪"取决于选中项是否在可视范围内。重建后立刻
           `scroll_to` 同步写回位置，帧数回到 1。
        """
        jobs.reconcile_aria2()      # 收账闭环：终态（done/failed）回写库
        t = self.query_one("#main", DataTable)
        pane = self._pane()
        desc = self._sort_desc.get(self._pane_name, True)
        cols = tuple(pane.columns())
        rows = list(pane.rows(desc))          # 显示用原值（保持 int/str 类型）
        jobs_pane = PANES.get("jobs")
        filt = jobs_pane.filter_mode if self._pane_name == "jobs" else None
        # 签名用字符串副本：类型无关地比较"内容是否变化"
        sig = (self._pane_name, getattr(self._assets, "source", None),
               desc, filt, cols,
               tuple(tuple(str(v) for v in r) for r in rows))

        if sig == self._frame_sig and t.row_count == len(rows):
            self._update_subtitle()
            return                      # 无变化：不 clear、不重建、不产生帧

        # 身份锚定：记住当前条目（首列），重建后跟随——排序/过滤/
        # storage 体积重排都不跟丢。首列唯一是该契约的前置不变量。
        try:
            anchor = t.get_row_at(t.cursor_row)[0]
        except Exception:                               # noqa: BLE001
            anchor = None
        saved_row = t.cursor_row if t.row_count else 0
        saved_scroll = t.scroll_offset.y

        t.clear(columns=True)
        for c, w in zip(cols, column_widths(cols, rows)):
            t.add_column(c, width=w)
        for row in rows:
            t.add_row(*row)
        if t.row_count:
            row = saved_row                            # 兜底：原行号钳制
            if anchor is not None:
                row = next((i for i in range(t.row_count)
                            if t.get_row_at(i)[0] == anchor), row)
            t.move_cursor(row=min(row, t.row_count - 1))
        # 同步写回滚动位置：消除"布局前多出的那一帧"
        t.scroll_to(y=min(saved_scroll, t.max_scroll_y), animate=False)

        self._frame_sig = sig
        self._update_subtitle()

    def _update_subtitle(self) -> None:
        """副标题只在内容变化时赋值（避免无谓的头部重绘）。"""
        pane = self._pane()
        extra = ""
        jobs_pane = PANES.get("jobs")
        if self._pane_name == "jobs" and jobs_pane.filter_mode != "all":
            extra = f" | 过滤: {jobs_pane.filter_mode}"
        text = (f"v{_pkg_version()} | 面板: {pane.label}{extra} | "
                f"aria2 daemon: {'在线' if aria2.ping() else '离线'}")
        if text != self.sub_title:
            self.sub_title = text

    # ── 键位动作 ──
    def on_data_table_row_selected(self, event) -> None:
        """DataTable 吞 enter 键后发 RowSelected——详情走这里。"""
        self.action_detail()

    def action_pane(self, name: str) -> None:
        self._pane_name = name
        self._clear_detail()
        self.refresh_data()

    def action_new_job(self) -> None:
        """n 键：jobs 面板新建 aria2 下载（模态输入）。"""
        if self._pane_name != "jobs":
            return
        self.push_screen(NewJobScreen(), self._submit_quick_download)

    def action_new_job_prefill(self) -> None:
        """F2：用选中作业的 spec 预填充新建对话框（不可预填充则退化）。

        映射逻辑在描述符层（prefill_from_spec），这里只做
        "取选中行 → 调映射 → 开模态"三件事。
        """
        if self._pane_name != "jobs":
            self.notify("F2 预填充仅在作业面板可用")
            return
        key = self._selected_key()
        pane = PANES.get("jobs")
        job = pane.selected_job(key) if (pane and key) else None
        if job is None:
            self.notify("未选中作业")
            return
        from ...descriptors import prefill_from_spec

        try:
            spec = jobs.stored_spec(int(str(key).lstrip("#")))
        except ValueError:
            spec = None
        if not spec:
            self.notify(f"作业 {key} 无 spec 记录，已打开空白表单")
            self.push_screen(NewJobScreen(), self._submit_quick_download)
            return

        prefill = prefill_from_spec(spec)
        if not prefill:
            self.notify(f"无法预填充（{prefill.reason}），已打开空白表单")
        self.push_screen(NewJobScreen(prefill), self._submit_quick_download)

    def _submit_quick_download(self, result) -> None:
        """模态返回 JobSpec（描述符 build_spec 或自定义手拼）。"""
        if not result:
            return
        try:
            # 相对 dest 落到 data root（自定义源的 mission 相对路径）
            if result.dest and not str(result.dest).startswith("/"):
                from ..config import Config
                abs_dest = Config().data / result.dest
                abs_dest.parent.mkdir(parents=True, exist_ok=True)
                result.dest = str(abs_dest)
            hit = jobs.check_cache(result)          # 缓存短路：已有数据不重下
            if hit is not None:
                self.notify(f"缓存命中（{result.source}），无需下载："
                            f"{hit.paths[0].name}")
            else:
                job_id = jobs.submit(result)
                self.notify(f"job {job_id} 已提交（{result.source}）")
        except Exception as e:                          # noqa: BLE001
            self.notify(f"提交失败: {e}")
        self.refresh_data()

    def action_delete_job(self) -> None:
        """Del：删除选中作业记录（资产保留）。"""
        if self._pane_name != "jobs":
            return
        key = self._selected_key()
        pane = self._pane()
        job = pane.selected_job(key) if pane.allows_job_actions else None
        if not job:
            return
        out = jobs.delete_jobs([job["id"]])
        if out["deleted"]:
            self.notify(f"job {job['id']} 已删（资产保留）")
        for jid, reason in out["refused"]:
            self.notify(f"job {jid} 拒删: {reason}")
        self.refresh_data()

    def action_delete_shown(self) -> None:
        """Shift+D：删除当前过滤态下显示的全部作业（二次确认）。"""
        if self._pane_name != "jobs":
            return
        pane = self._pane()
        if pane.filter_mode == "all":
            self.notify("全量删除请在 CLI: myastro delete id...")
            return
        if not getattr(self, "_del_shown_armed", False):
            self._del_shown_armed = True
            self.notify(f"再按一次 Shift+D 确认删除全部显示的"
                        f" {self.query_one('#main', DataTable).row_count} 条")
            return
        self._del_shown_armed = False
        t = self.query_one("#main", DataTable)
        ids = [int(str(t.get_row_at(i)[0]).lstrip("#"))
               for i in range(t.row_count)]
        out = jobs.delete_jobs(ids)
        self.notify(f"删除 {len(out['deleted'])}，拒 {len(out['refused'])}"
                    f"（资产保留）")
        self.refresh_data()

    def action_batch(self) -> None:
        """b：批量下单（索引浏览 + 多选 + 批次提交）。"""
        self.push_screen(BatchScreen(), self._submit_batch)

    def _submit_batch(self, result) -> None:
        if not result:
            return
        self.notify(f"批次 {result['batch_id']} 已提交（{result['n']} 个作业）")
        self.refresh_data()

    def action_filter(self) -> None:
        """f 键：jobs 面板循环过滤 all→active→failed→done。"""
        pane = self._pane()
        if isinstance(pane, JobsPane):
            pane.cycle_filter()
            self.refresh_data()

    def action_sort(self) -> None:
        """s 键：jobs/assets/data 面板切换升降序（各自记忆）。

        光标锚定当前条目（首列 id）：翻转后跟随原条目到新位置，
        而不是停留在原行号——否则条目关联完全错位。
        """
        if self._pane_name not in self._sort_desc:
            return
        self._sort_desc[self._pane_name] = \
            not self._sort_desc[self._pane_name]
        self.refresh_data()          # 光标保持由 refresh 的身份锚定负责

    def action_back(self) -> None:
        if self._pane_name == "assets":
            self._pane_name = "storage"
            self._assets.source = None
            self._clear_detail()
            self.refresh_data()
            # 光标回到下钻时的 mission（身份寻址：按名字找行；
            # storage 按体积动态重排，行号会漂移）
            t = self.query_one("#main", DataTable)
            row = next((i for i in range(t.row_count)
                        if t.get_row_at(i)[0] == self._drill_origin_key),
                       t.row_count - 1)
            if t.row_count:
                t.move_cursor(row=max(row, 0))
        else:
            self._clear_detail()

    def action_detail(self) -> None:
        """enter：打开条目——有详情显示详情，无详情则下钻（如有）。

        storage 行无详情 → enter 即进入资产视图（文件管理器直觉）；
        info/assets/jobs 行有详情 → enter 展示。框架级规则，无 per-pane 特判。
        """
        key = self._selected_key()
        if key is None:
            return
        pane = self._pane()
        content = pane.detail(key)
        if content is not None:
            self.query_one("#detail", Static).update(content)
            return
        if type(pane).drill is not Pane.drill:    # 子类实现了下钻
            pane.drill(self, key)

    def action_preview(self) -> None:
        """p：预览选中作业/数据集的首个文件（parquet/FITS/文本嗅探）。"""
        if self._pane_name != "jobs":
            self.notify("预览仅在作业面板可用")
            return
        key = self._selected_key()
        pane = PANES.get("jobs")
        job = pane.selected_job(key) if (pane and key) else None
        path = None
        if job and job.get("dataset_id"):
            from ..db import DB
            db = DB().init()
            row = db.conn.execute(
                "SELECT path FROM files WHERE dataset_id=? LIMIT 1",
                (job["dataset_id"],)).fetchone()
            db.close()
            path = row["path"] if row else None
        if not path:
            self.notify("选中项没有文件可预览")
            return
        try:
            from ..preview import preview as _preview
            from ..preview import render_text
            doc = _preview(path)
        except Exception as e:                      # noqa: BLE001
            self.notify(f"预览失败: {e}", severity="error")
            return
        self.query_one("#detail", Static).update(render_text(doc))

    def action_retry(self) -> None:
        pane = self._pane()
        if pane.allows_job_actions:
            job = pane.selected_job(self._selected_key())
            if job:
                try:
                    jobs.retry(job["id"])
                    self.notify(f"job {job['id']} 已重新提交")
                except Exception as e:                  # noqa: BLE001
                    self.notify(f"retry 失败: {e}")
        self.refresh_data()

    def action_cancel(self) -> None:
        pane = self._pane()
        if pane.allows_job_actions:
            job = pane.selected_job(self._selected_key())
            if job and job["executor"] == "aria2" and job["gid"]:
                aria2.remove(job["gid"])
                self.notify(f"aria2 gid {job['gid'][:8]}… 已请求取消")
        self.refresh_data()

    def _selected_key(self):
        """选中条目的身份：渲染行首列值。排序/过滤/刷新后仍然有效。"""
        t = self.query_one("#main", DataTable)
        try:
            return t.get_row_at(t.cursor_row)[0]
        except Exception:                               # noqa: BLE001
            return None

    def _clear_detail(self) -> None:
        self.query_one("#detail", Static).update("")


def main() -> None:
    AstroTop().run()


if __name__ == "__main__":
    main()
