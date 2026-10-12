"""门面实现：L3 客户端（TUI/CLI/notebook/第三方）的唯一入口。

内核异常在此映射为 errors.py 体系；内核私有符号不经此门不对外。
"""
from __future__ import annotations

from typing import Any

from . import errors
from .descriptors import REGISTRY, SourceDescriptor
from .io import jobs
from .io.core import write_parquet
from .io.jobs import FetchResult, RunContext

# 插件协议 v1 的对外面：插件任务**必须**返回 FetchResult、接收 RunContext、
# 并用统一落盘（write_parquet 内含原子替换与 pyarrow 线程规避）。
# 这里引用一次既是声明意图，也让 linter 不再把它们当"未使用"。
PLUGIN_EXPORTS = (write_parquet, FetchResult, RunContext)

_NETWORK_ERRORS = {"ConnectionError", "TimeoutError", "HTTPError",
                   "URLError", "SSLError", "ConnectTimeout", "ReadTimeout"}


def _map_job_failure(exc: Exception) -> Exception:
    """把内核 JobFailed 映射到门面错误分类（第三方据此分流处置）。"""
    etype = getattr(exc, "error_type", None)
    if etype in _NETWORK_ERRORS:
        return errors.NetworkError(str(exc))
    return errors.StateError(str(exc))


def _descriptor(name: str) -> SourceDescriptor:
    from .io.plugins import ensure_discovered

    ensure_discovered()          # 惰性：按源名查表前才触发插件发现
    d = REGISTRY.get(name)
    if d is None:
        raise errors.ParamError(f"未知源 {name!r}（可用: {sorted(REGISTRY)}）")
    return d


def fetch(source: str, /, **params) -> FetchResult:
    """获取数据：缓存命中直接返回；否则提交作业并等待完成。"""
    d = _descriptor(source)
    try:
        spec = d.build_spec(params)
    except ValueError as e:
        raise errors.ParamError(str(e)) from e
    try:
        return jobs.fetch(spec)
    except jobs.JobFailed as e:
        raise _map_job_failure(e) from e


def query(source: str, /, **params) -> dict[str, Any]:
    """计划型接口：校验参数并解析出将要执行的作业（不提交）。"""
    d = _descriptor(source)
    try:
        p = d.validate(params)
        spec = d.build_spec(params)
    except ValueError as e:
        raise errors.ParamError(str(e)) from e
    return {"source": source, "params": p,
            "url": spec.url, "dest": spec.dest}


def sources() -> list[dict[str, Any]]:
    """源清单（描述符摘要）。**这里触发一次插件发现**（惰性：不在 import 时做）。"""
    from .io.plugins import ensure_discovered
    from .io.sources import STATUS

    ensure_discovered()
    return [{"name": d.name, "desc": d.desc,
             "status": STATUS[d.status], "product": d.product,
             "orderable": bool(d.task or d.url_key),
             "fields": [{"name": f.name, "type": f.type.__name__,
                         "default": f.default,
                         "choices": f.choices} for f in d.fields]}
            for d in REGISTRY.values()]


def describe(source: str) -> dict[str, Any]:
    """单源详情（含参数表单 schema）。"""
    return next(s for s in sources() if s["name"] == source)


def register_source(descriptor: SourceDescriptor, *,
                    replace: bool = False) -> None:
    """插件协议 v1：注册第三方源（校验 → 冲突检查 → 写入）。

    规则与示例见 `docs/zh/dev/plugin-api.md`；校验失败抛 `ParamError`（错误分类：参数），
    且**不留部分状态**。内置源不可覆盖。
    """
    from .descriptors import register as _register

    try:
        _register(descriptor, replace=replace)
    except ValueError as e:
        raise errors.ParamError(str(e)) from e


def register_task(name: str, fn, *, replace: bool = False) -> None:
    """插件协议 v1：注册第三方任务函数（`fn(ctx) -> FetchResult`）。

    任务按名寻址是硬要求（JobSpec 只存名字，重试与跨进程恢复依赖它）；
    内置任务不可覆盖。校验失败抛 `ParamError`。
    """
    from .tasks import register_task as _register_task

    try:
        _register_task(name, fn, replace=replace)
    except ValueError as e:
        raise errors.ParamError(str(e)) from e


def status(batch_id: str | None = None) -> list[dict[str, Any]]:
    """作业状态列表（可按 batch_id 过滤）。"""
    return jobs.status(batch_id=batch_id)


def batch(source: str, param_rows: list[dict[str, Any]]
          ) -> dict[str, Any]:
    """批量下单：同一源的 N 组参数 → 批次。返回 batch_id 与 job_ids。

    例：batch("legacy", [{"brick": "0001m002"}, {"brick": "0001m005"}])
    """
    d = _descriptor(source)
    specs = []
    for params in param_rows:
        try:
            specs.append(d.build_spec(params))
        except ValueError as e:
            raise errors.ParamError(
                f"参数行 {params} 无效: {e}") from e
    batch_id, job_ids = jobs.submit_batch(specs)
    return {"batch_id": batch_id, "job_ids": job_ids, "n": len(job_ids)}


def wait(job_id: int, **kw) -> FetchResult:
    try:
        return jobs.wait(job_id, **kw)
    except jobs.JobFailed as e:            # 子类必须先捕获
        raise _map_job_failure(e) from e
    except LookupError as e:
        raise errors.NotFoundError(str(e)) from e
    except RuntimeError as e:
        raise errors.StateError(str(e)) from e
    except TimeoutError as e:
        raise errors.StateError(str(e)) from e


def retry(job_id: int, force: bool = True) -> int:
    try:
        return jobs.retry(job_id, force=force)
    except LookupError as e:
        raise errors.NotFoundError(str(e)) from e
    except ValueError as e:
        raise errors.StateError(str(e)) from e
    except RuntimeError as e:
        raise errors.StateError(str(e)) from e


def delete(job_ids: list[int]) -> dict:
    return jobs.delete_jobs(job_ids)


def audit() -> dict:
    """完整性巡检：missing/size_mismatch/corrupt + sha 基线建立。"""
    from .io.integrity import audit as _audit
    return _audit()


def search(source=None, target=None, name=None, since=None, until=None,
           near=None, radius_deg=0.1, limit=50) -> list[dict]:
    """本地检索：已入库数据集（"这个天区/目标我取过没有"）。"""
    from .io.search import search as _search
    try:
        return _search(source=source, target=target, name=name, since=since,
                       until=until, near=near, radius_deg=radius_deg,
                       limit=limit)
    except ValueError as e:
        raise errors.ParamError(str(e)) from e


def doctor() -> list[dict]:
    """环境自检：返回 [{name, status, detail, fix}]，status ∈ ok/warn/fail。

    装完第一件事就该能自证"这里能不能用"——依赖、路径可写、账本可用、
    账本文件系统（SQLite 与 NFS 不兼容）、索引、平台能力。
    """
    from .io.doctor import run
    return [c.as_dict() for c in run()]


def init_root() -> dict:
    """创建数据根与账本（幂等）。返回解析后的路径。"""
    from .io.config import Config
    from .io.db import DB

    cfg = Config()
    cfg.init()
    DB(cfg.db).init().close()
    return {"data": str(cfg.data), "db": str(cfg.db), "cache": str(cfg.cache)}


def backup(out_dir=None, *, with_index: bool = False) -> dict:
    """备份账本（SQLite 在线备份）。账本不可再生，这是它唯一的保险。"""
    from .io.backup import create
    try:
        return create(out_dir, with_index=with_index)
    except ValueError as e:
        raise errors.ParamError(str(e)) from e


def restore(source, *, force: bool = False) -> dict:
    """从备份恢复账本；默认拒绝覆盖（force=True 时自动留存安全副本）。"""
    from .io.backup import restore as _restore
    try:
        return _restore(source, force=force)
    except ValueError as e:
        raise errors.ParamError(str(e)) from e


def coverage(index_name: str) -> dict:
    """索引覆盖率：本地已有 / 索引全量。"""
    from .io.search import coverage as _coverage
    try:
        return _coverage(index_name)
    except LookupError as e:
        raise errors.NotFoundError(str(e)) from e


def retry_batch(batch_id: str) -> dict:
    """整批重试（失败半批一键重跑）。"""
    try:
        return jobs.retry_batch(batch_id)
    except LookupError as e:
        raise errors.NotFoundError(str(e)) from e


def schedule_list() -> list[dict]:
    """定时任务清单与安装状态。"""
    from .io.schedule import list_installed
    return list_installed()


def schedule_install(task: str) -> str:
    from .io.schedule import install
    try:
        return str(install(task))
    except LookupError as e:
        raise errors.NotFoundError(str(e)) from e


def health(source: str | None = None) -> list[dict]:
    """源健康探测（实测可达性，结果落库供显示层覆盖声明基线）。"""
    from .io.health import probe
    try:
        return probe(source)
    except LookupError as e:
        raise errors.NotFoundError(str(e)) from e
    except ConnectionError as e:
        raise errors.NetworkError(str(e)) from e


def prefill(job_id: int) -> dict:
    """作业 → 表单预填充（`build_spec` 的逆映射，供各客户端复用）。

    返回 {"mode", "source", "params", "custom", "reason"}；
    mode="none" 表示无法预填充（调用方退回空白表单）。
    """
    from dataclasses import asdict

    from .descriptors import prefill_from_spec
    spec = jobs.stored_spec(job_id)
    if spec is None:
        raise errors.NotFoundError(f"job {job_id} 不存在")
    return asdict(prefill_from_spec(spec))


def index_list() -> list[dict]:
    from .io.index import INDEXES, index_path
    return [{"name": n, "desc": s["desc"],
             "built": index_path(n).exists()} for n, s in INDEXES.items()]


def index_search(name: str, prefix: str, limit: int = 8) -> list[str]:
    from .io.index import search_index
    return search_index(name, prefix, limit)


def index_update(name: str) -> str:
    from .io.index import update_index
    try:
        return str(update_index(name))
    except LookupError as e:
        raise errors.NotFoundError(str(e)) from e
    except ConnectionError as e:
        raise errors.NetworkError(str(e)) from e
