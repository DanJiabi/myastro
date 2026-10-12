"""作业 spec 重建：库里的历史行 → 可再次执行的 JobSpec。

被 aria2 收账（轮询旧作业）与重试（跨进程恢复）共用，故独立成模块：
放在 aria2_exec 或 lifecycle 任一侧都会与另一侧形成循环依赖。

descriptors/tasks 在**函数内**导入——顶层导入会与
io.sources → io.jobs 形成初始化环（历史坑，务必保持函数内）。
"""
from __future__ import annotations

import json

from ..db import DB
from .spec import JobSpec


def stored_spec(job_id: int, db: DB | None = None) -> dict | None:
    """按 job id 取已存 spec（dict 形态；不存在返回 None）。

    与 _resolve_retry_spec 的区别：那要能**重跑**（需 task/url 完整），
    这只要**回填表单**（老作业缺 task 也能用）。
    """
    db = db or DB().init()
    row = db.conn.execute("SELECT spec_json FROM jobs WHERE id=?",
                          (job_id,)).fetchone()
    if row is None:
        return None
    try:
        return json.loads(row["spec_json"] or "{}")
    except ValueError:
        return {}

def _infer_task(source: str | None) -> str | None:
    """源名 → 描述符的具名任务名（救 E0 前无 task 字段的旧作业）。"""
    if not source:
        return None
    # 注意相对深度：本模块在 myastro/io/jobs/ 下，`...descriptors` 才是
    # myastro.descriptors（`..` 只会找到 myastro.io）。
    # 这里**不吞 ImportError**——早期版本 except ImportError: return None
    # 把"导入坏了"伪装成"该源没有任务"，让重试静默降级（真实踩坑）。
    from ...descriptors import REGISTRY
    d = REGISTRY.get(source)
    return d.task if d else None

def _rebuild_spec(row) -> JobSpec:
    """从 jobs 表行重建 aria2 作业的 spec（url/dest/params 已持久化）。"""
    meta = json.loads(row["spec_json"] or "{}")
    return JobSpec(source=meta.get("source", "aria2"),
                   params=meta.get("params", {}),
                   executor="aria2", url=row["url"], dest=row["dest"])
