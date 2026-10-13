"""Gaia DR3 锥形检索（ADQL → parquet，python 执行器）。"""
from __future__ import annotations

from ..core import retry, write_parquet
from ..jobs import FetchResult, JobSpec, fetch

_DEFAULT_COLS = ("source_id", "ra", "dec", "parallax", "parallax_error",
                 "pmra", "pmdec", "phot_g_mean_mag",
                 "phot_bp_mean_mag", "phot_rp_mean_mag")


def _download_gaia(ra: float, dec: float, radius: float, columns=None):
    """网络层：Gaia TAP 同步 ADQL。返回 (df, meta)。columns 缺省用默认列。"""
    from astroquery.gaia import Gaia

    cols = ",".join(columns if columns is not None else _DEFAULT_COLS)
    adql = (f"SELECT {cols} FROM gaiadr3.gaia_source "
            f"WHERE 1=CONTAINS(POINT('ICRS', ra, dec), "
            f"CIRCLE('ICRS', {ra}, {dec}, {radius}))")
    table = retry(lambda: Gaia.launch_job(adql).get_results())
    df = table.to_pandas()
    meta = {"ra": ra, "dec": dec, "radius_deg": radius, "n_rows": len(df)}
    return df, meta


def _fn(ctx) -> FetchResult:
    p = ctx.params
    cols = p.get("columns")
    df, meta = _download_gaia(p["ra"], p["dec"], p["radius_deg"], cols)
    # 文件名必须编码影响内容的参数：columns 不同 = 内容不同。
    # 真实事故（账本 #3）：同坐标同半径、不同 columns 的两次查询共用一个文件名，
    # 后到者把文件据为己有，先到者成了"有 dataset 无文件"的幽灵。
    # 默认列保持旧文件名（向后兼容既有缓存）。
    suffix = ""
    if cols is not None and tuple(cols) != _DEFAULT_COLS:
        import hashlib
        import json
        suffix = "_c" + hashlib.sha1(
            json.dumps(list(cols)).encode()).hexdigest()[:6]
    dest = (ctx.dest_dir /
            f"cone_{p['ra']:.4f}_{p['dec']:+.4f}_r{p['radius_deg']}{suffix}.parquet")
    write_parquet(df, dest)
    return FetchResult(paths=[dest], dataset_id=-1, meta=meta)


def gaia_cone(ra: float, dec: float, radius_deg: float = 0.05,
              columns: tuple[str, ...] | list[str] = _DEFAULT_COLS
              ) -> FetchResult:
    """获取天区 Gaia DR3 星表切片，落 parquet 并入库。"""
    if not 0 < radius_deg <= 5:
        raise ValueError("radius_deg 须在 (0, 5]")
    spec = JobSpec(source="gaia", executor="python",
                   params={"ra": ra, "dec": dec, "radius_deg": radius_deg,
                           "columns": list(columns)},
                   fn=_fn)
    return fetch(spec)
