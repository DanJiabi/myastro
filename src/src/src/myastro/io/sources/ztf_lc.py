"""ZTF 光变曲线（IRSA nph_light_curves 原生 API，公开数据）。

⚠ ztfquery 1.28 的 from_position 对当前服务端静默返回空——绕开包装层
直连原生 API（实测 5 角秒锥 316KB/16s）。公开数据无需凭据。
响应量随锥半径平方增长：单源建议 ≤5 角秒；大锥排夜间。
"""
from __future__ import annotations

import io as _io

from ..core import retry, write_parquet
from ..jobs import FetchResult, JobSpec, fetch

_LC_URL = "https://irsa.ipac.caltech.edu/cgi-bin/ZTF/nph_light_curves"


def _download_ztflc(ra: float, dec: float, radius_arcsec: float):
    """网络层：原生 LC API（CSV）→ DataFrame。"""
    import pandas as pd
    import requests

    def _attempt():
        r = requests.get(_LC_URL, params={
            "POS": f"CIRCLE {ra} {dec} {radius_arcsec / 3600.0:.6f}",
            "FORMAT": "CSV"}, timeout=300)
        r.raise_for_status()
        return r.text

    text = retry(_attempt)
    df = pd.read_csv(_io.StringIO(text))
    meta = {"ra": ra, "dec": dec, "radius_arcsec": radius_arcsec,
            "n_rows": len(df),
            "n_sources": int(df.oid.nunique()) if len(df) else 0}
    return df, meta


def _fn(ctx) -> FetchResult:
    p = ctx.params
    df, meta = _download_ztflc(p["ra"], p["dec"], p["radius_arcsec"])
    dest = (ctx.dest_dir /
            f"lc_{p['ra']:.4f}_{p['dec']:+.4f}_r{p['radius_arcsec']}as.parquet")
    if df is None or not len(df):
        return FetchResult(paths=[], dataset_id=-1,
                           meta={**meta, "empty": True})
    write_parquet(df, dest)
    return FetchResult(paths=[dest], dataset_id=-1,
                       meta={**meta, "empty": False})


def ztf_lightcurve(ra: float, dec: float, radius_arcsec: float = 5.0
                   ) -> FetchResult:
    """ZTF 光变：锥内全部源的全部历史测光点 → 单 parquet。"""
    spec = JobSpec(source="ztf-lc", executor="python",
                   params={"ra": ra, "dec": dec,
                           "radius_arcsec": radius_arcsec},
                   task="ztf_lightcurve")
    return fetch(spec)
