"""NASA Exoplanet Archive 查询（量级 KB，直查不建 job）。"""
from __future__ import annotations

from typing import Any

import numpy as np

from ..core import retry

_FIELDS = ("pl_name", "hostname", "pl_orbper", "pl_orbpererr1",
           "pl_trandep", "pl_trandur", "pl_tranmid", "pl_rade",
           "st_teff", "st_rad", "sy_jmag", "tic_id")


def _scalar(v) -> Any:
    """MaskedColumn 元素 → None/float/str（容忍 '1.09 d' 这类带单位串）。"""
    if v is np.ma.masked:
        return None
    try:
        x = float(str(v).split()[0])
        return None if np.isnan(x) else x
    except (TypeError, ValueError, IndexError):
        return str(v)


def exoplanet_params(name: str) -> dict[str, Any]:
    """按行星名查凌星参数（周期、深度、中天时刻等），返回标量 dict。

    ps 表一个行星有多组解（不同文献/拟合），选解规则**必须确定性**——
    早期版本"取第一组周期非空的"随归档行序漂移，同一行星两次调用可能
    给出不同 T0/深度（真实故障：notebook 复跑拿到 pl_trandep=None）。

    现行规则：优先"周期与深度都非空"的解，其中取周期误差最小的（最精确），
    并列时按周期升序；无完整解则退回仅有周期的解。
    """
    from astroquery.ipac.nexsci.nasa_exoplanet_archive import NasaExoplanetArchive

    table = retry(lambda: NasaExoplanetArchive.query_criteria(
        table="ps", select=",".join(_FIELDS),
        where=f"upper(pl_name) LIKE '{name.upper()}'"))
    if len(table) == 0:
        raise LookupError(f"Exoplanet Archive 无 {name}")

    def usable(row) -> bool:
        return _scalar(row["pl_orbper"]) is not None

    def complete(row) -> bool:
        return usable(row) and _scalar(row["pl_trandep"]) is not None

    pool = [r for r in table if complete(r)] or \
        [r for r in table if usable(r)] or list(table)

    def precision(row) -> tuple:
        err = _scalar(row["pl_orbpererr1"])
        return (err if isinstance(err, float) else float("inf"),
                _scalar(row["pl_orbper"]) or float("inf"))

    row = min(pool, key=precision)
    return {f: _scalar(row[f]) for f in _FIELDS}
