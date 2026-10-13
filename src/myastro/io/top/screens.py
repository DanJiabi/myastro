"""模态屏：新建下载（描述符驱动——执行器对用户不可见，Roadmap E1）。

表单 schema 来自 SourceDescriptor.fields（FieldSpec 声明），与 CLI 参数
生成、门面校验同一份声明。自定义 URL 模式保留（manifest 单条快捷版）。
"""
from __future__ import annotations

from typing import ClassVar

from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Select, Static

from ...descriptors import REGISTRY
from ..index import count_index, load_index, search_index
from ..jobs import JobSpec
from .suggest import IndexSuggester


class NewJobScreen(ModalScreen):
    """新建下载：源下拉（描述符注册表）→ 参数 → 实时预览。

    最后一个输入项回车提交，ESC 取消；Tab 对带索引字段补全。
    """

    CSS = """
    NewJobScreen { align: center middle; }
    #newjob {
        width: 78; height: auto; max-height: 90%;
        border: round $accent; padding: 1 2; background: $surface;
    }
    /* 字段行：左侧固定宽标签 + 右侧自适应控件 */
    #newjob .field-row { height: auto; }
    #newjob .field-label { width: 20; padding-top: 1; color: $text-muted; }
    #newjob .field-row Input, #newjob .field-row Select { width: 1fr; }
    #hint { color: $text-muted; }
    #preview { color: $text-muted; margin-top: 1; }
    """
    # Tab 不做自定义绑定——交还框架默认的焦点流转（Screen 自带
    # Binding("tab", "app.focus_next")）；补全走 Input 的原生 suggester
    BINDINGS: ClassVar[list] = [("escape", "cancel", "取消"),
                ("f2", "fill_example", "填示例")]

    CUSTOM = "__custom__"

    def __init__(self, prefill=None) -> None:
        """prefill: descriptors.Prefill（F2 预填充）；None = 空白新建（F1）。

        预填充只是"初始值来源"，表单渲染/校验/提交路径与 F1 完全一致——
        任何不匹配都会退化成空白表单（由 prefill_from_spec 判级）。
        """
        super().__init__()
        self._prefill = prefill
        self.source_key = (prefill.source
                           if prefill is not None and prefill.mode == "descriptor"
                           else self.CUSTOM)
        self._rendered_key = None
        self._render_token = 0          # latest-wins：见 _render_fields

    def compose(self):
        with Vertical(id="newjob"):
            yield Static(self._title(), id="title")
            yield Static("* = 必填（无可默认值的字段）", id="hint")
            with Horizontal(classes="field-row"):
                yield Label("数据源", classes="field-label")
                yield Select(
                    [("自定义 URL", self.CUSTOM)]
                    + [(f"{d.desc}", k) for k, d in REGISTRY.items()],
                    value=self.source_key, id="source")
            # 选中源的详细中文描述（detail 字段；自定义 URL 给提示）
            yield Static(self._source_detail_text(), id="source-detail")
            yield Vertical(id="fields")
            yield Static("", id="preview")

    @staticmethod
    def _label_text(f) -> str:
        """字段标签：名称 + 必填星号（必填 = 无默认值且非可选）+ 索引标记。

        索引标记的意义：让"这字段有本地索引（可补全/看候选）"在**输入前**
        就可见——此前只能靠记住哪个源带索引。
        """
        name = f.label or f.name
        if f.default is None and not f.optional:
            name += " *"
        if f.index:
            name += "（索引）"
        return name

    @staticmethod
    def _placeholder(d, f) -> str:
        """placeholder 只放示例——名称由左侧标签承担，避免两处重复。"""
        ex = d.example_params.get(f.name)
        return f"例：{ex}" if ex is not None else ""

    def on_mount(self) -> None:
        # 空白新建：焦点在"源"下拉（第一决策点）
        # 预填充：源已定，焦点给首字段（用户多半要改参数）
        self.call_after_refresh(self._render_fields)
        target = ("#fields Input" if self._prefill
                  else "#source")
        self.call_after_refresh(
            lambda: self.query_one(target).focus())

    def _source_detail_text(self) -> str:
        if self.source_key == self.CUSTOM or self.source_key not in REGISTRY:
            return "自定义 URL：直接给下载地址，适合一次性抓取。"
        detail = REGISTRY[self.source_key].detail
        return detail or REGISTRY[self.source_key].desc

    async def on_select_changed(self, event) -> None:
        self.source_key = str(event.value)
        self.query_one("#source-detail", Static).update(
            self._source_detail_text())
        await self._render_fields()

    async def _render_fields(self) -> None:
        """按描述符 FieldSpec 声明重建参数输入区（数据驱动）。

        **并发保护（latest-wins）**：`remove_children` 与 `mount` 都是 await 点，
        交出控制权期间可能到来新的数据源选择。旧实现在 await **之前**就写了
        `_rendered_key`，于是那次新选择被判为"已渲染"直接跳过 → 表单最终停留在
        **上一个源**的字段上（用户在 TUI 里快速切换数据源就能看到错字段），
        并且可能在已被清空的容器上 `query(Input).first()` 抛 NoMatches。
        现在：捕获本次 key → 每个 await 点后校验 token → **挂载完成后**才更新
        `_rendered_key`，focus 也改成防御式取值。
        """
        if self._rendered_key == self.source_key:
            return
        self._render_token += 1
        token = self._render_token
        key = self.source_key                 # 捕获：await 期间可能已变
        box = self.query_one("#fields", Vertical)
        await box.remove_children()
        if token != self._render_token:        # 已有更新的请求在跑 → 让位
            return
        rows: list[tuple[str, Input]] = []
        if key == self.CUSTOM:
            c = (self._prefill.custom
                 if self._prefill and self._prefill.mode == "custom" else {})
            rows = [
                ("URL *", Input(placeholder="例：https://…/f.fits",
                                value=c.get("url", ""), id="url")),
                ("文件名", Input(placeholder="例：f.fits（默认取 URL 末段）",
                                 value=c.get("name", ""), id="name")),
                ("mission", Input(placeholder="例：quick",
                                  value=c.get("mission", ""), id="mission")),
            ]
        else:
            d = REGISTRY[key]
            pre = (self._prefill.params
                   if self._prefill and self._prefill.mode == "descriptor"
                   and self._prefill.source == key else {})
            rows = [(self._label_text(f),
                     Input(placeholder=self._placeholder(d, f),
                           value=self._value_of(f, pre),
                           suggester=(IndexSuggester(f.index)
                                      if f.index else None),
                           id=f"f_{f.name}"))
                    for f in d.fields]
        # 左标签列 + 右控件（标签不可聚焦，不进入 Tab 环）
        await box.mount(*[
            Horizontal(Label(label, classes="field-label"), widget,
                       classes="field-row")
            for label, widget in rows])
        if token != self._render_token:        # 本轮已过时：不标记、不抢焦点
            return
        self._rendered_key = key               # 挂载成功后才是"已渲染"
        first = next(iter(box.query(Input)), None)
        if first is not None:
            first.focus()

    def _title(self) -> str:
        if not self._prefill or not self._prefill:
            return "新建下载"
        note = f"（{self._prefill.reason}）" if self._prefill.reason else ""
        src = self._prefill.source or "自定义 URL"
        return f"新建下载 · 预填充自 {src}{note}"

    @staticmethod
    def _value_of(f, prefill_params: dict) -> str:
        """字段初值：预填充值优先，其次描述符默认值。"""
        if f.name in prefill_params:
            return str(prefill_params[f.name])
        return "" if f.default is None else str(f.default)

    def action_fill_example(self) -> None:
        """Ctrl+E：按 example_params 填入全部字段（合法起点，改完即用）。"""
        if self.source_key == self.CUSTOM:
            return
        d = REGISTRY[self.source_key]
        for f in d.fields:
            ex = d.example_params.get(f.name)
            if ex is not None:
                self.query_one(f"#f_{f.name}", Input).value = str(ex)
        self._update_preview()
        self.notify("已填入示例参数")

    @staticmethod
    def _params(box) -> dict:
        return {w.id[2:]: str(w.value).strip()
                for w in box.query(Input)}

    def _derive(self):
        """(提交载荷, 预览文本)。描述符源走 validate+build_spec（执行器隐身）；
        自定义源手拼 aria2 spec。"""
        box = self.query_one("#fields", Vertical)
        if self.source_key == self.CUSTOM:
            url = str(self.query_one("#url", Input).value).strip()
            name = str(self.query_one("#name", Input).value).strip() \
                or url.rsplit("/", 1)[-1].split("?")[0] or "download"
            mission = str(self.query_one("#mission", Input).value).strip() \
                or "quick"
            spec = JobSpec(source=mission, executor="aria2",
                           params={"name": name, "url": url},
                           url=url, dest=f"{mission}/{name}")
            return spec, f" URL: {url}\n 文件: {mission}/{name}"
        d = REGISTRY[self.source_key]
        raw = self._params(box)
        params = {}
        for f in d.fields:
            v = raw.get(f.name, "")
            if v == "":
                if f.optional:
                    params[f.name] = None
                elif f.default is None:
                    raise ValueError(f"缺少必填参数 {f.label or f.name}")
                else:
                    params[f.name] = f.default
            else:
                params[f.name] = f.type(v)
            if f.choices and str(params[f.name]) not in f.choices:
                raise ValueError(f"{f.name} 须为 {f.choices}")
        spec = d.build_spec(params)
        if spec.url:
            preview = f" URL: {spec.url}\n 文件: {spec.dest}"
        else:
            preview = (f" 任务: {spec.task}（{d.product}）"
                       f"\n 参数: {params}")
        return spec, preview

    def _update_preview(self) -> None:
        preview = self.query_one("#preview", Static)
        try:
            _, text = self._derive()
        except Exception:                            # noqa: BLE001 参数不全
            text = " （参数不全或无效）"
        # 带索引字段的提示行：让"能不能补全、为什么不能"都看得见
        # （编号型键如 field 号，输入本身往往就是合法键 → 无需补全，
        #   此时必须说明，否则用户以为 → 坏了）
        if self.source_key != self.CUSTOM:
            for f in REGISTRY[self.source_key].fields:
                if not f.index:
                    continue
                v = self._params(self.query_one("#fields", Vertical))\
                    .get(f.name, "")
                if not v:
                    # 空值也要说明该字段带索引（输入前即可见用法）
                    text += (f"\n {f.name}（索引 {f.index}）：输入后列出同前缀"
                             f"候选，可补全时用 → 接受")
                    continue
                text += "\n " + self._index_hint(f, v)
        preview.update(text)

    @staticmethod
    def _index_hint(f, value: str) -> str:
        """单个索引字段的状态行：可补全 / 已是有效值 / 无匹配 / 索引未构建。"""
        if load_index(f.index) is None:
            return (f"{f.name}: 索引未构建"
                    f"（myastro index update {f.index}）")
        hits = search_index(f.index, value, limit=8)
        total = count_index(f.index, value)
        listed = " ".join(hits) + (" …" if total > len(hits) else "")
        if total == 0:
            return f"{f.name} {value!r} 无匹配（索引 {f.index}，共 {total}）"
        if hits and hits[0] == value:
            # 输入已是完整键：编号型字段的常态——没有可补的内容
            tail = f"，同前缀另有 {total - 1} 个" if total > 1 else ""
            return (f"{f.name} {value} = 有效值{tail}"
                    f"（无需补全；同前缀候选：{listed}）")
        return (f"{f.name} {value} → {hits[0]}（→ 接受）"
                f"  匹配 {total}: {listed}")

    def on_input_changed(self, event) -> None:
        self._update_preview()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        inputs = list(self.query("#fields Input"))
        if event.input is not inputs[-1]:
            inputs[inputs.index(event.input) + 1].focus()
            return
        try:
            spec, _ = self._derive()
        except Exception as e:                        # noqa: BLE001
            self.notify(f"参数无效: {e}")
            return
        self.dismiss(spec)
