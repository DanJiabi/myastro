"""批量下单模态：索引浏览 + 多选 + 批量提交（Roadmap E3/E4）。

流程：选源（有索引的字段）→ 前缀过滤（OptionList 虚拟化，36 万行可扛）
→ 空格勾选（SelectionList）→ 回车整批提交。
选项标签带 E4 共管标记：✓ 已在本地 / ☁ 仅云端。
"""
from __future__ import annotations

from typing import ClassVar

from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Select, SelectionList, Static

from ...descriptors import REGISTRY
from .. import jobs
from ..index import count_index, search_index


def _indexed_sources() -> list[tuple[str, str]]:
    """(source_key, field_name)：可用于**批量**下单的索引字段。

    资格规则：索引字段必须能单独标识一次获取——即除它之外，其余字段
    都有默认值或可空。反例：ztf 帧下载还需 ffd（无默认），单靠 field
    构不出 spec；ztf-meta（其余全有默认）与 legacy（唯一字段）合格。
    """
    out = []
    for key, d in REGISTRY.items():
        if not (d.task or d.url_key):
            continue
        others_ok = all(f.default is not None or f.optional
                        for f in d.fields if not f.index)
        if not others_ok:
            continue
        for f in d.fields:
            if f.index:
                out.append((key, f.name))
                break
    return out


def _local_names() -> set[str]:
    """本地已有的文件名集合（✓/☁ 判定用）。"""
    from pathlib import Path

    from ..db import DB
    db = DB().init()
    rows = db.conn.execute("SELECT path FROM files").fetchall()
    db.close()
    return {Path(r["path"]).name for r in rows}


class BatchScreen(ModalScreen):
    CSS = """
    BatchScreen { align: center middle; }
    #batchbox {
        width: 84; height: 80%; border: round $accent;
        padding: 1 2; background: $surface;
    }
    #batchbox Input, #batchbox Select { width: 1fr; }
    #opts { height: 1fr; border: round $panel; }
    """
    BINDINGS: ClassVar[list] = [("escape", "cancel", "取消"),
                ("ctrl+s", "submit", "提交批次")]

    MAX_OPTS = 300          # 前缀匹配的渲染上限（虚拟化之上再截断）

    def __init__(self) -> None:
        super().__init__()
        self._field = None          # (source_key, field_name, index_name)
        self._params_field = None
        self._local = set()

    def compose(self):
        with Vertical(id="batchbox"):
            yield Static("批量下单：选源 → 前缀过滤 → 空格勾选 → Ctrl+S 提交")
            yield Select(
                [(f"{REGISTRY[k].desc}", k) for k, _ in _indexed_sources()],
                id="src")
            yield Input(placeholder="前缀过滤（如 0001m）", id="prefix")
            yield SelectionList(id="opts")
            yield Static("", id="bstatus")

    def on_mount(self) -> None:
        self._local = _local_names()
        self._refresh_options()

    def on_select_changed(self, event) -> None:
        self._refresh_options()

    def on_input_changed(self, event) -> None:
        self._refresh_options()

    def _field_info(self):
        src = str(self.query_one("#src", Select).value)
        for k, fname in _indexed_sources():
            if k == src:
                for f in REGISTRY[k].fields:
                    if f.index:
                        return k, fname, f.index
        return None

    def _refresh_options(self) -> None:
        info = self._field_info()
        if not info:
            return
        self._field = info
        prefix = str(self.query_one("#prefix", Input).value).strip()
        opts = self.query_one("#opts", SelectionList)
        if not prefix:
            opts.clear_options()
            self.query_one("#bstatus", Static).update(" 输入前缀开始过滤")
            return
        hits = search_index(info[2], prefix, limit=self.MAX_OPTS)
        total = count_index(info[2], prefix)
        opts.clear_options()
        def _mark(h: str) -> str:
            return "✓" if (h in self._local
                           or (h + ".fits") in self._local) else "☁"

        opts.add_options([(f"{h} {_mark(h)}", h) for h in hits])
        self.query_one("#bstatus", Static).update(
            f" 匹配 {total}，显示前 {len(hits)}（✓本地 ☁云端）")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_submit(self) -> None:
        if not self._field:
            return
        opts = self.query_one("#opts", SelectionList)
        picked = [v for v in opts.selected]
        if not picked:
            self.notify("未勾选任何条目")
            return
        src_key, fname, _ = self._field
        d = REGISTRY[src_key]
        specs = []
        for v in picked:
            try:
                specs.append(d.build_spec({fname: v}))
            except Exception as e:                  # noqa: BLE001
                self.notify(f"{v} 构建失败: {e}")
                return
        batch_id, job_ids = jobs.submit_batch(specs)
        self.dismiss({"batch_id": batch_id, "n": len(job_ids)})
