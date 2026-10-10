"""作业契约：JobSpec / 结果 / 异常 / 进程内会话（全部子模块共用）。

python 执行器寄生在调用方进程内，心跳刷 jobs.updated_at；
慢网络语义：有心跳 = 慢（继续等），无心跳超时 = 死（orphaned）。
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import Config

HEARTBEAT_INTERVAL = 5.0          # 秒；测试中可 monkeypatch
ORPHAN_AFTER = "2 minutes"        # SQLite timedelta 语法


HEARTBEAT_INTERVAL = 5.0          # 秒；测试中可 monkeypatch

ORPHAN_AFTER = "2 minutes"        # SQLite timedelta 语法

@dataclass
class FetchResult:
    paths: list[Path]
    dataset_id: int
    meta: dict[str, Any] = field(default_factory=dict)
    cache_hit: bool = False

@dataclass
class RunContext:
    """传给 python 执行器目标函数的上下文。"""
    source: str
    params: dict[str, Any]
    dest_dir: Path
    cfg: Config

@dataclass
class JobSpec:
    source: str
    params: dict[str, Any]
    fn: Callable[[RunContext], FetchResult] | None = None   # python 执行器（进程内）
    task: str | None = None      # python 执行器：具名任务（跨进程可恢复，优先于 fn）
    executor: str = "python"
    dest: str | None = None      # aria2 用
    url: str | None = None       # aria2 用
    size_hint: int | None = None

    def to_json(self) -> str:
        return json.dumps({"source": self.source, "params": self.params,
                           "executor": self.executor, "dest": self.dest,
                           "task": self.task, "size_hint": self.size_hint},
                          ensure_ascii=False, default=str)

class Session:
    def __init__(self) -> None:
        self._registry: dict[int, tuple[JobSpec, dict[str, Any]]] = {}

    def put(self, job_id: int, spec: JobSpec) -> dict[str, Any]:
        slot: dict[str, Any] = {}
        self._registry[job_id] = (spec, slot)
        return slot

    def spec(self, job_id: int) -> JobSpec | None:
        return self._registry.get(job_id, (None, {}))[0]

    def slot(self, job_id: int) -> dict[str, Any]:
        return self._registry.get(job_id, ({}, {}))[1]

    def has(self, job_id: int) -> bool:
        return job_id in self._registry

    def clear(self) -> None:
        self._registry.clear()

_DEFAULT_SESSION = Session()

class JobFailed(RuntimeError):
    """作业失败（保留失败类型，供上层做错误分类）。

    error_type 是原异常类名（如 ConnectionError / HTTPError），
    跨进程也保留（落库在 jobs.error_type），门面据此映射到
    NetworkError / StateError——第三方才能区分"断网"与"任务 bug"。
    """

    def __init__(self, message: str, error_type: str | None = None):
        super().__init__(message)
        self.error_type = error_type
