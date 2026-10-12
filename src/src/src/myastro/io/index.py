"""本地索引：枚举类数据的一次性预取/构造（TUI 候选列表的数据源）。

设计：枚举 = 数据集，不是实时查询。两种来源：
- url+parse：远端目录（如 Legacy brick 表），走 aria2 管线下载后解析
- builder：本地已打包的数据（如 ZTF field 表），直接构造无下载
均落为紧凑 parquet 存 data/index/；手动强制更新（CLI 或 API）。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import Config
from .core import write_parquet


def _parse_survey_bricks(src: Path) -> pd.DataFrame:
    from astropy.table import Table
    t = Table.read(src)
    df = t.to_pandas()
    cols = [c for c in ("brickname", "ra", "dec") if c in df.columns]
    out = df[cols].copy()
    # fits 字符串列常为 bytes，统一解码
    for c in out.columns:
        if out[c].dtype == object:
            out[c] = out[c].map(
                lambda v: v.decode() if isinstance(v, bytes) else v)
    return out


# 进程内缓存：索引 DataFrame 与排序键表（按文件 mtime 失效）
_CACHE: dict[str, tuple[tuple[int, int], pd.DataFrame]] = {}
_KEYS: dict[str, tuple[pd.DataFrame, list[str]]] = {}
_HIGH = "\U0010ffff"          # bisect 前缀上界哨兵（大于任何合法键）


def _build_ztf_fields() -> pd.DataFrame:
    """ZTF 观测场索引：ztfquery 包内置 field 表（1776 场，纯本地无下载）。"""
    from ztfquery.fields import FIELD_DATAFRAME
    df = FIELD_DATAFRAME.reset_index()
    df = df.rename(columns={"ID": "field", "RA": "ra", "Dec": "dec"})
    return df[["field", "ra", "dec"]].copy()


# ── 索引注册表：加新索引登记一条 ──
# 两种来源：url+parse（远端下载，走 aria2 管线）/ builder（本地构造，无下载）
INDEXES: dict[str, dict] = {
    "legacy-bricks": {
        "url": ("https://portal.nersc.gov/cfs/cosmo/data/legacysurvey/"
                "dr10/south/survey-bricks-dr10-south.fits.gz"),
        "desc": "Legacy Surveys DR10 south 砖块索引（brickname/ra/dec）",
        "source_size": "104 MB（解析后仅留紧凑索引）",
        "parse": _parse_survey_bricks,
    },
    "ztf-fields": {
        "builder": _build_ztf_fields,
        "desc": "ZTF 观测场索引（field/ra/dec，1776 场）",
        "source_size": "本地包内置（无下载）",
        "key_col": "field",
    },
}


def _index_dir() -> Path:
    d = Config().data / "index"
    d.mkdir(parents=True, exist_ok=True)
    return d


def index_path(name: str) -> Path:
    return _index_dir() / f"{name}.parquet"


def load_index(name: str) -> pd.DataFrame | None:
    """读本地索引；未构建返回 None（调用方提示 update）。

    进程内缓存（按文件 mtime+size 失效）：TUI 每敲一个键都会查索引，
    36 万行 parquet 每次重读 ≈100ms，缓存后前缀查询是二分（µs 级）。
    返回的是**共享对象**，调用方不得就地修改。
    """
    p = index_path(name)
    if not p.exists():
        _CACHE.pop(name, None)
        return None
    st = p.stat()
    stamp = (st.st_mtime_ns, st.st_size)
    cached = _CACHE.get(name)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    df = pd.read_parquet(p)
    _CACHE[name] = (stamp, df)
    _KEYS.pop(name, None)                    # 前缀结构随之失效
    return df


def _sorted_keys(name: str) -> list[str]:
    """索引键的**排序字符串表**（前缀查询用 bisect，O(log n)）。"""
    df = load_index(name)
    if df is None:
        return []
    key = INDEXES[name].get("key_col", "brickname")
    cached = _KEYS.get(name)
    if cached is not None and cached[0] is df:
        return cached[1]
    keys = sorted(str(v) for v in df[key].tolist())
    _KEYS[name] = (df, keys)
    return keys


def _save(name: str, df: pd.DataFrame) -> Path:
    out = index_path(name)
    write_parquet(df, out)
    _CACHE.pop(name, None)                   # 立刻失效，下次读新文件
    _KEYS.pop(name, None)
    return out


def update_index(name: str, keep_source: bool = False) -> Path:
    """强制更新索引。

    builder 型：本地构造（无下载）；url+parse 型：下载源文件（aria2 管线）
    → 解析存索引 → 删源文件。"""
    from . import jobs as _jobs
    if name not in INDEXES:
        raise LookupError(f"未知索引 {name}（可用: {list(INDEXES)}）")
    spec = INDEXES[name]
    if builder := spec.get("builder"):
        return _save(name, builder())
    src = _index_dir() / f"{name}.src"
    job_spec = _jobs.JobSpec(
        source="index", executor="aria2",
        params={"name": name, "url": spec["url"]},
        url=spec["url"], dest=str(src))
    _jobs.fetch(job_spec)                    # 缓存命中则直接返回
    out = _save(name, spec["parse"](src))
    if not keep_source:
        src.unlink(missing_ok=True)
    return out


def search_index(name: str, prefix: str, limit: int = 8) -> list[str]:
    """前缀匹配候选（TUI 补全/批量过滤用）。索引缺失返回空。

    实现：排序表 + bisect 取前缀区间（不再全表 startswith 扫描）。
    """
    import bisect

    prefix = str(prefix)
    keys = _sorted_keys(name)
    if not keys:
        return []
    lo = bisect.bisect_left(keys, prefix)
    hi = bisect.bisect_left(keys, prefix + _HIGH, lo)
    return keys[lo:min(hi, lo + limit)]


def count_index(name: str, prefix: str) -> int:
    """前缀匹配总数（同样走 bisect 区间）。"""
    import bisect

    prefix = str(prefix)
    keys = _sorted_keys(name)
    if not keys:
        return 0
    lo = bisect.bisect_left(keys, prefix)
    hi = bisect.bisect_left(keys, prefix + _HIGH, lo)
    return hi - lo


def lookup_index(name: str, key) -> dict | None:
    """精确键查询：返回该行 dict（含 ra/dec 等列）；未命中或索引缺失返回 None。

    用途：把参数里的编号解析成坐标（如 field 号 → 场中心、brick 名 → 砖块中心）。
    走缓存的 DataFrame + bisect 存在性检查，不做全表扫描。
    """
    import bisect

    df = load_index(name)
    if df is None:
        return None
    key_col = INDEXES[name].get("key_col", "brickname")
    target = str(key)
    keys = _sorted_keys(name)
    i = bisect.bisect_left(keys, target)
    if i >= len(keys) or keys[i] != target:
        return None
    # 键→行：用排序位置对应的原行（同值键极少，取首个匹配即可）
    hit = df[df[key_col].astype(str) == target]
    if hit.empty:
        return None
    return hit.iloc[0].to_dict()
