"""具名任务注册表：python 执行器的任务按名可寻址（替代 fn 闭包）。

JobSpec.task 存名字；执行时 jobs 层按名解析。收益：
- spec 全数据化（name + params 即 JSON），跨进程创建/重试成为可能
- 第三方/CLI/TUI 无需导入函数即可下单 python 源

任务函数签名统一：fn(ctx: RunContext) -> FetchResult（同 python 执行器契约）。
新增任务：实现函数 + 在此登记一行。
"""
from __future__ import annotations

from .io.jobs import FetchResult, RunContext


def _tess_lightcurve(ctx: RunContext) -> FetchResult:
    from .io.sources.tess import _fn
    return _fn(ctx)


def _gaia_cone(ctx: RunContext) -> FetchResult:
    from .io.sources.gaia import _fn
    return _fn(ctx)


def _ztf_metadata(ctx: RunContext) -> FetchResult:
    from .io.sources.ztf import _meta_fn
    return _meta_fn(ctx)


def _mpc_ephemeris(ctx: RunContext) -> FetchResult:
    from .io.sources.mpc import _fn
    return _fn(ctx)


def _unwise_cutout(ctx: RunContext) -> FetchResult:
    from .io.sources.unwise import _fn
    return _fn(ctx)


def _simbad_cone(ctx: RunContext) -> FetchResult:
    from .io.sources.simbad import _fn
    return _fn(ctx)


def _vizier_cone(ctx: RunContext) -> FetchResult:
    from .io.sources.vizier import _fn
    return _fn(ctx)


def _ztf_lightcurve(ctx: RunContext) -> FetchResult:
    from .io.sources.ztf_lc import _fn
    return _fn(ctx)


TASKS: dict[str, callable] = {
    "tess_lightcurve": _tess_lightcurve,
    "gaia_cone": _gaia_cone,
    "ztf_metadata": _ztf_metadata,
    "mpc_ephemeris": _mpc_ephemeris,
    "simbad_cone": _simbad_cone,
    "vizier_cone": _vizier_cone,
    "ztf_lightcurve": _ztf_lightcurve,
    "unwise_cutout": _unwise_cutout,
}


# 内置任务名单：插件**不允许覆盖**；契约快照与守卫只绑这些。
BUILTIN_TASKS: frozenset[str] = frozenset(TASKS)

_TASK_NAME_RE = __import__("re").compile(r"^[a-z][a-z0-9_]{0,63}$")


def register_task(name: str, fn, *, replace: bool = False) -> None:
    """注册第三方任务函数（插件协议 v1）。

    任务必须**按名寻址**（而不是传闭包）：JobSpec 只存名字，重试/跨进程恢复都靠它。
    `fn(ctx: RunContext) -> FetchResult`。校验失败抛 ValueError（facade 转 ParamError）。
    """
    if not _TASK_NAME_RE.fullmatch(name):
        raise ValueError(f"任务名 {name!r} 不合法（须匹配 {_TASK_NAME_RE.pattern}）")
    if not callable(fn):
        # 同样刻意用 ValueError：统一映射为 ParamError（退出码 2）
        raise ValueError(f"任务 {name!r} 的目标必须是可调用对象")  # noqa: TRY004
    if name in BUILTIN_TASKS:
        raise ValueError(f"{name}: 不允许覆盖内置任务（内置任务名保留给 myastro 本体）")
    if name in TASKS and not replace:
        raise ValueError(f"{name}: 任务已注册（要替换请显式 replace=True）")
    TASKS[name] = fn
