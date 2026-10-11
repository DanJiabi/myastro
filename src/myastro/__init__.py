"""myastro — 天文数据获取与管理库（公开门面）。

第三方唯一应导入的模块。io/ 以下为内核私有，重构不另行通知。

用法：
    import myastro as ma
    r = ma.fetch("tess", target="WASP-12", sector=20)   # 首次下载，此后缓存命中
    df = pd.read_parquet(r.paths[0])
    ma.status(); ma.wait(id); ma.retry(id); ma.delete([id])

稳定性承诺：
- __all__ 中的符号按语义化版本演进（破坏性改动走 deprecation）
- 产物 schema（如光变 parquet 的 time/flux/flux_err/quality 列）是契约，
  变更走 schema_version 字段（当前 SCHEMA_VERSION = 1）
- 异常体系见 errors.py：ParamError / NetworkError / NotFoundError / StateError
"""
from __future__ import annotations


def _detect_version() -> str:
    """版本单一来源：以 pyproject.toml 为唯一手写处。

    已安装时读包元数据（importlib.metadata）；直接从源码树运行时元数据可能缺失，
    回退到 "0.3.1+source"，避免出现第二个手写版本号（此前 pyproject 0.1.0 与
    这里 0.2.0 已经漂移过）。
    """
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("myastro")
    except PackageNotFoundError:                    # 源码直跑（未安装）
        return "0.3.1+source"


__version__ = _detect_version()
SCHEMA_VERSION = 1

from .descriptors import FieldSpec, SourceDescriptor
from .errors import NetworkError, NotFoundError, ParamError, StateError
from .facade import (
    audit,
    backup,
    batch,
    coverage,
    delete,
    describe,
    doctor,
    fetch,
    health,
    index_list,
    index_search,
    index_update,
    init_root,
    prefill,
    query,
    register_source,
    restore,
    retry,
    retry_batch,
    schedule_install,
    schedule_list,
    search,
    sources,
    status,
    wait,
)

__all__ = [
    "SCHEMA_VERSION",
    "FieldSpec",
    "NetworkError",
    "NotFoundError",
    "ParamError",
    "SourceDescriptor",
    "StateError",
    "__version__",
    "audit",
    "backup",
    "batch",
    "coverage",
    "delete",
    "describe",
    "doctor",
    "fetch",
    "health",
    "index_list",
    "index_search",
    "index_update",
    "init_root",
    "prefill",
    "query",
    "register_source",
    "restore",
    "retry",
    "retry_batch",
    "schedule_install",
    "schedule_list",
    "search",
    "sources",
    "status",
    "wait",
]
