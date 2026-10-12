"""把本地索引接进 Textual 原生补全（`Suggester`）。

设计原则：**用框架能力，不自造补全交互**。
幽灵文本渲染、显示时机、接受键（→）、按键触发、LRU 缓存全部由
`textual.widgets.Input` + `textual.suggester.Suggester` 提供；
本模块只回答框架问的那一个问题：*给定当前输入，补全成什么*。

因此：Tab 归还框架默认（焦点流转），索引查询在 worker 线程里做，
索引缺失时静默降级（返回 None → 普通输入框，不打断输入）。
"""
from __future__ import annotations

import asyncio

from textual.suggester import Suggester

from ..index import search_index


class IndexSuggester(Suggester):
    """本地索引前缀补全。

    契约（见 textual/suggester.py）：`get_suggestion(value)` 返回
    **补全后的完整值**（不是剩余部分）；框架负责与当前值比较、
    只在更长时显示幽灵文本，并在光标位于末尾时由 → 接受。
    """

    def __init__(self, index_name: str) -> None:
        # 大小写敏感：brick 名与 field 号都是小写数字，精确前缀更可预期
        super().__init__(case_sensitive=True)
        self.index_name = index_name

    async def get_suggestion(self, value: str) -> str | None:
        if not value:
            return None
        try:
            # 索引查询是阻塞 I/O（首次载入 ~100ms，之后二分 µs 级）；
            # 放到线程里，避免卡住事件循环
            hits = await asyncio.to_thread(
                search_index, self.index_name, value, 1)
        except Exception:                       # noqa: BLE001
            return None                          # 降级：不打断输入
        if not hits:
            return None
        candidate = str(hits[0])
        return None if candidate == value else candidate
