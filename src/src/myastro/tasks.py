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
