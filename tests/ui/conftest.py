"""UI 测试共享设施。

为什么需要"等到表单构建完成"：新建下载页的字段是在**异步**函数里
`await box.mount(...)` 渲染的（`screens.py`），`Select.value = x` 之后单次
`await pilot.pause()` 只处理一轮消息——在慢机器上（实测 CI 的 macos-3.12）
字段还没挂上就去查询，于是 `NoMatches` / 标记数对不上。固定次数的 pause 是
猜测，正确做法是**等到条件成立**。
"""
from __future__ import annotations

import pytest


@pytest.fixture
def wait_for_fields():
    """`await wait_for_fields(pilot, screen, names)`：等到这些字段名出现在 #fields。

    为什么不用"pause 固定次数"或"行数足够"：这两种都是猜测，且**行数条件会被
    上一个数据源的行满足**（实测因此把 legacy 的 0 个索引标记当成结果）。
    这里等到期望的字段名逐个出现为止；超时即失败并打印实际标签，不静默通过。
    """
    async def _wait(pilot, screen, names, *, tries: int = 120):
        for _ in range(tries):
            labels = [str(lbl.content)
                      for lbl in screen.query("#fields .field-label")]
            if all(any(n in lbl for lbl in labels) for n in names):
                return
            await pilot.pause()
        labels = [str(lbl.content) for lbl in screen.query("#fields .field-label")]
        raise AssertionError(
            f"表单未在预期时间内构建完成：期望字段 {names}，实际标签 {labels}")

    return _wait
