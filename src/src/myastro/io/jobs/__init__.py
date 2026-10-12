"""统一作业基底（包化后的门面）：fetch/submit/wait/retry/delete 等。

为什么拆包：单文件 635 行、8 组职责（契约 / 落库 / 两个执行器 / 提交 / 查询 /
生命周期），改一处要在互不相关的段落间跳转。现在每个子模块 60~165 行：

    spec.py        契约（JobSpec/FetchResult/异常/会话）与常量
    store.py       缓存命中判定与成功登记（datasets/files/meta/坐标）
    aria2_exec.py  aria2 执行器：提交、轮询、收账
    runner.py      python 执行器、提交分发、fetch、批次
    lifecycle.py   僵尸/重试准入/跨进程重建/删除/批次重试
    query.py       状态列表与阻塞等待

导入约定：使用者继续 `from myastro.io import jobs; jobs.fetch(...)`。

**打桩要打在"使用处"**：例如 `myastro.io.jobs.runner._start_aria2_job`。
本模块故意**不**重导出可打桩的私有函数——否则 `jobs._start_aria2_job = fake`
会静默失效（打在了包名上，而不是调用者查表的地方），比报错更难查。
`_DEFAULT_SESSION` / `_dest_dir_cache` 是**原地可变**的状态对象，重导出安全。
"""
from __future__ import annotations

from .aria2_exec import reconcile_aria2
from .lifecycle import (
    delete_jobs,
    find_orphans,
    retry,
    retry_batch,
)
from .query import status, wait
from .rebuild import stored_spec
from .runner import (
    _dest_dir_cache,
    fetch,
    submit,
    submit_batch,
)
from .spec import (
    _DEFAULT_SESSION,
    HEARTBEAT_INTERVAL,
    ORPHAN_AFTER,
    FetchResult,
    JobFailed,
    JobSpec,
    RunContext,
    Session,
)
from .store import check_cache

__all__ = [
    "HEARTBEAT_INTERVAL",
    "ORPHAN_AFTER",
    "_DEFAULT_SESSION",
    "FetchResult",
    "JobFailed",
    "JobSpec",
    "RunContext",
    "Session",
    "_dest_dir_cache",
    "check_cache",
    "delete_jobs",
    "fetch",
    "find_orphans",
    "reconcile_aria2",
    "retry",
    "retry_batch",
    "status",
    "stored_spec",
    "submit",
    "submit_batch",
    "wait",
]
