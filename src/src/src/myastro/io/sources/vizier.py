"""VizieR 星表锥检（任意发表星表按天区切片）。"""
from __future__ import annotations

from ..core import retry, write_parquet
from ..jobs import FetchResult, JobSpec, fetch


def _download_vizier(catalog: str, ra: float, dec: float, radius_deg: float):
    """网络层：VizieR query_region(catalog)。返回 (df|None, meta)。"""
    from astroquery.vizier import Vizier

    def _attempt():
        import astropy.units as u
        from astropy.coordinates import SkyCoord
        c = SkyCoord(ra, dec, unit="deg")
        r = Vizier.query_region(c, radius=radius_deg * u.deg,
                                catalog=catalog)
        return r[0] if len(r) else None

    table = retry(_attempt)
    df = table.to_pandas() if table is not None and len(table) else None
    meta = {"catalog": catalog, "ra": ra, "dec": dec,
            "radius_deg": radius_deg,
            "n_rows": 0 if df is None else len(df)}
    return df, meta


def _fn(ctx) -> FetchResult:
    p = ctx.params
    df, meta = _download_vizier(p["catalog"], p["ra"], p["dec"],
                                 p["radius_deg"])
    dest = (ctx.dest_dir /
            f"{p['catalog'].replace('/', '_')}_"
            f"{p['ra']:.4f}_{p['dec']:+.4f}_r{p['radius_deg']}.parquet")
    empty = df is None
    if not empty:
        write_parquet(df, dest)
    return FetchResult(paths=[] if empty else [dest], dataset_id=-1,
                       meta={**meta, "empty": empty})


def vizier_cone(catalog: str, ra: float, dec: float,
                radius_deg: float = 0.1) -> FetchResult:
    """VizieR 指定星表的锥形切片 → parquet（如 II/246=2MASS）。"""
    spec = JobSpec(source="vizier", executor="python",
                   params={"catalog": catalog, "ra": ra, "dec": dec,
                           "radius_deg": radius_deg},
                   task="vizier_cone")
    return fetch(spec)
