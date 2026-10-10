"""SIMBAD 锥形检索（目标认证：坐标→天体名单）。"""
from __future__ import annotations

from ..core import atomic_write, retry
from ..jobs import FetchResult, JobSpec, fetch


def _download_simbad(ra: float, dec: float, radius_deg: float):
    """网络层：SIMBAD query_region。返回 (df, meta)。"""
    from astroquery.simbad import Simbad

    def _attempt():
        from astropy.coordinates import SkyCoord
        c = SkyCoord(ra, dec, unit="deg")
        return Simbad.query_region(c, radius=f"{radius_deg}d")

    table = retry(_attempt)
    df = table.to_pandas() if table is not None and len(table) else None
    meta = {"ra": ra, "dec": dec, "radius_deg": radius_deg,
            "n_rows": 0 if df is None else len(df)}
    return df, meta


def _fn(ctx) -> FetchResult:
    p = ctx.params
    df, meta = _download_simbad(p["ra"], p["dec"], p["radius_deg"])
    dest = (ctx.dest_dir /
            f"cone_{p['ra']:.4f}_{p['dec']:+.4f}_r{p['radius_deg']}.parquet")
    if df is None:
        df_empty = True
    else:
        atomic_write(dest, lambda f: df.to_parquet(f, index=False))
        df_empty = False
    return FetchResult(paths=[] if df_empty else [dest],
                       dataset_id=-1, meta={**meta, "empty": df_empty})


def simbad_cone(ra: float, dec: float, radius_deg: float = 0.1
                ) -> FetchResult:
    """SIMBAD 锥搜：该天区内已认证的天体名单 → parquet。"""
    spec = JobSpec(source="simbad", executor="python",
                   params={"ra": ra, "dec": dec, "radius_deg": radius_deg},
                   task="simbad_cone")
    return fetch(spec)
