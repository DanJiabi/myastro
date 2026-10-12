"""坐标解析：把数据集的参数/元数据还原成天球坐标 (ra, dec)。

为什么要它：账本里大量数据集的参数**不含坐标**——
- legacy / legacy-surveys：只有 brick 名 → 查 legacy-bricks 索引得砖块中心
- ztf / ztf-meta：只有 field 号 → 查 ztf-fields 索引得场中心
- tess：坐标在 meta（FITS 头 RA_OBJ/DEC_OBJ，随 meta_json 落库）
只有 gaia/simbad/vizier/ztf-lc/unwise 的参数里直接带 ra/dec。

设计：**注册表 + 解析顺序**（可扩展，新源加一条 resolver 即可）
    1) 参数直取 params.ra/params.dec
    2) 元数据 meta.ra/meta.dec
    3) 源专属 resolver（编号 → 索引 → 坐标）
解析在**入库时**做一次，结果存 datasets.ra/dec（query 时零解析成本，
也让 SQL 能做包围盒粗筛）。
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .index import lookup_index

Coord = tuple[float, float]
Resolver = Callable[[dict, dict], Coord | None]


def _from_index(params: dict, meta: dict, field: str, index: str,
                key: str) -> Coord | None:
    """通用：参数里的编号 → 索引精确查询 → (ra, dec)。"""
    value = params.get(key)
    if value is None:
        return None
    row = lookup_index(index, value)
    if not row:
        return None
    try:
        return float(row["ra"]), float(row["dec"])
    except (KeyError, TypeError, ValueError):
        return None


def _ztf_field(params: dict, meta: dict) -> Coord | None:
    return _from_index(params, meta, "field", "ztf-fields", "field")


def _legacy_brick(params: dict, meta: dict) -> Coord | None:
    return _from_index(params, meta, "brick", "legacy-bricks", "brick")


# 源 → (文件名模式, 索引)：参数/元数据都拿不到坐标时的兜底
# （TUI 快速下载与清单进来的 legacy 数据只有 name/url，但文件名带 brick）
import re as _re

FILENAME_PATTERNS: dict[str, tuple[_re.Pattern, str]] = {
    "legacy": (_re.compile(r"tractor-([0-9a-z]{8})\.fits"), "legacy-bricks"),
    "legacy-surveys": (_re.compile(r"tractor-([0-9a-z]{8})\.fits"),
                       "legacy-bricks"),
}

# 源 → 专属解析器（编号型参数）
RESOLVERS: dict[str, Resolver] = {
    "ztf": _ztf_field,
    "ztf-meta": _ztf_field,
    "legacy": _legacy_brick,
    "legacy-surveys": _legacy_brick,
}


def _norm_ra(ra: float) -> float:
    return ra % 360.0


def _from_filename(source: str, paths) -> Coord | None:
    """兜底：从文件名提取编号（如 tractor-<brick>.fits）再查索引。"""
    pattern = FILENAME_PATTERNS.get(source or "")
    if pattern is None or not paths:
        return None
    regex, index = pattern
    for path in paths:
        m = regex.search(str(path))
        if not m:
            continue
        row = lookup_index(index, m.group(1))
        if row:
            try:
                return float(row["ra"]), float(row["dec"])
            except (KeyError, TypeError, ValueError):
                continue
    return None


def resolve_coords(source: str | None, params: dict[str, Any] | None,
                   meta: dict[str, Any] | None = None,
                   paths=None) -> Coord | None:
    """尽力解析坐标；解析不出返回 None（不抛错——坐标缺失不是错误）。

    顺序：params.ra/dec → meta.ra/dec → 源专属 resolver（编号→索引）
          → 文件名兜底（tractor-<brick>.fits）
    """
    params = params or {}
    meta = meta or {}

    for src in (params, meta):
        try:
            ra, dec = float(src["ra"]), float(src["dec"])
        except (KeyError, TypeError, ValueError):
            continue
        if -90.0 <= dec <= 90.0:
            return _norm_ra(ra), dec

    resolver = RESOLVERS.get(source or "")
    if resolver is not None:
        coord = resolver(params, meta)
        if coord is not None and -90.0 <= coord[1] <= 90.0:
            return _norm_ra(coord[0]), coord[1]

    coord = _from_filename(source or "", paths)
    if coord is not None and -90.0 <= coord[1] <= 90.0:
        return _norm_ra(coord[0]), coord[1]
    return None


def angular_separation(ra1: float, dec1: float, ra2: float, dec2: float
                       ) -> float:
    """两天球点的角距（度），haversine 公式（数值稳定，无需 astropy）。"""
    import math

    p1, p2 = math.radians(dec1), math.radians(dec2)
    dphi = math.radians(ra2 - ra1)
    dlambda = p2 - p1
    a = (math.sin(dlambda / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dphi / 2) ** 2)
    return math.degrees(2 * math.asin(min(1.0, math.sqrt(a))))
