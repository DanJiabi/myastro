"""示例插件：给 myastro 加一个**完全离线**的数据源。

它不是玩具——它演示协议 v1 的全部要点：
1. `register_task` 注册一个**按名寻址**的任务函数（`fn(ctx) -> FetchResult`）；
2. `register_source` 注册描述符（表单/校验/路由都由它驱动）；
3. 只用公开 API（`import myastro as ma`），不碰 `myastro.io.*` 内核；
4. 落盘走 `ma.write_parquet`（原子替换 + pyarrow 线程规避），且写在 `ctx.dest_dir` 内；
5. 数据照常进账本，可用 `myastro search` / TUI / `myastro audit` 检索与巡检。

安装（开发用）：
    pip install -e examples/myastro-source-example

使用（自动发现机制见 docs/plugin-api.md §8，批次 2）：
    import myastro_example_source          # 触发注册
    myastro fetch demo --target M31        # CLI 也可用（需先 import）
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import myastro as ma

TASK_NAME = "demo_lightcurve"
SOURCE_NAME = "demo"

# 目标名允许字母/数字/空格/下划线/连字符——注意：这是**进文件名**的字段，
# 因此必须声明 pattern（协议会强制这一点，防路径穿越）。
_TARGET_PATTERN = r"^[A-Za-z0-9 _-]{1,32}$"


def demo_lightcurve(ctx: ma.RunContext) -> ma.FetchResult:
    """合成一条正弦光变并落盘（完全离线，便于 CI 与本机试跑）。"""
    target = ctx.params["target"]
    n = int(ctx.params.get("points") or 200)

    phase = np.linspace(0.0, 1.0, n)
    flux = 1.0 + 0.05 * np.sin(2.0 * np.pi * phase)
    frame = pd.DataFrame({
        "target": [target] * n,
        "phase": phase,
        "flux": flux,
        "source": [SOURCE_NAME] * n,
    })

    dest = ctx.dest_dir / f"{target}.parquet"
    ma.write_parquet(frame, dest)
    return ma.FetchResult(paths=[dest], dataset_id=0,
                          meta={"target": target, "n_points": n,
                                "amplitude": 0.05})


ma.register_task(TASK_NAME, demo_lightcurve)
ma.register_source(ma.SourceDescriptor(
    name=SOURCE_NAME,
    desc="示例合成光变（离线，演示插件协议）",
    product="parquet",
    status="ok",
    fields=[
        ma.FieldSpec("target", label="目标名", pattern=_TARGET_PATTERN),
        ma.FieldSpec("points", int, default=200, label="采样点数", optional=True),
    ],
    task=TASK_NAME,
    example_params={"target": "M31", "points": 200},
))
