"""ZTF 数据获取（IRSA ibe API：元数据 python 执行器 / 图像 aria2 执行器）。

⚠ ztfquery 1.28 走 IRSA token 认证，此处直接用匿名 ibe HTTP API
（2026-10 实测可用；IRSA 偶发 504，重试兜底）。
"""
from __future__ import annotations

from ..core import atomic_write, retry
from ..jobs import FetchResult, JobSpec, fetch

IBE_SEARCH = "https://irsa.ipac.caltech.edu/ibe/search/ztf/products/sci"
IBE_DATA = "https://irsa.ipac.caltech.edu/ibe/data/ztf/products/sci"


def ztf_sci_url(ffd: str, field: int, filtercode: str, ccdid: int, qid: int,
                imgtypecode: str = "o") -> str:
    """sci 主图像下载 URL。ffd = filefracday，如 '20191214561238'。"""
    return (f"{IBE_DATA}/{ffd[:4]}/{ffd[4:8]}/{ffd[8:]}/"
            f"ztf_{ffd}_{field:06d}_{filtercode}_c{ccdid:02d}_{imgtypecode}"
            f"_q{qid}_sciimg.fits")


def frame_name(ffd: str, field: int, filtercode: str, ccdid: int, qid: int,
               imgtypecode: str = "o") -> str:
    return (f"ztf_{ffd}_{field:06d}_{filtercode}_c{ccdid:02d}_{imgtypecode}"
            f"_q{qid}_sciimg.fits")


def _query_ibe(field: int, filtercode: str, ccdid: int, qid: int,
               jd_min: float, jd_max: float):
    """网络层：ibe 查询 → astropy IPAC 表解析。返回 (df, meta)。"""
    import requests
    from astropy.io import ascii as ascii_io

    where = (f"field={field} AND filtercode='{filtercode}' AND ccdid={ccdid}"
             f" AND qid={qid} AND obsjd BETWEEN {jd_min} AND {jd_max}"
             f" AND imgtypecode='o' AND infobits=0")

    def _attempt():
        r = requests.get(IBE_SEARCH, params={"where": where}, timeout=120)
        if r.status_code != 200:
            raise ConnectionError(f"ibe {r.status_code}")
        if "QUERY_STATUS = 'ERROR'" in r.text[:2000]:
            raise ConnectionError(f"ibe: {r.text[:300]}")
        return r.text

    text = retry(_attempt)
    table = ascii_io.read(text.splitlines(), format="ipac")
    df = table.to_pandas()
    meta = {"field": field, "filtercode": filtercode, "ccdid": ccdid,
            "qid": qid, "jd_min": jd_min, "jd_max": jd_max,
            "n_frames": len(df)}
    return df, meta


def _meta_fn(ctx) -> FetchResult:
    p = ctx.params
    df, meta = _query_ibe(p["field"], p["filtercode"], p["ccdid"], p["qid"],
                          p["jd_min"], p["jd_max"])
    dest = (ctx.dest_dir /
            f"meta_f{p['field']:06d}_{p['filtercode']}_c{p['ccdid']:02d}"
            f"_q{p['qid']}_jd{p['jd_min']:.0f}-{p['jd_max']:.0f}.parquet")
    atomic_write(dest, lambda f: df.to_parquet(f, index=False))
    return FetchResult(paths=[dest], dataset_id=-1, meta=meta)


def ztf_metadata(field: int, filtercode: str = "zg", ccdid: int = 1,
                 qid: int = 1, jd_min: float = 2458100, jd_max: float = 2461000
                 ) -> FetchResult:
    """获取某 field/quadrant 的 sci 帧元数据（视宁度/历元/文件号）。"""
    spec = JobSpec(source="ztf-meta", executor="python",
                   params={"field": field, "filtercode": filtercode,
                           "ccdid": ccdid, "qid": qid,
                           "jd_min": jd_min, "jd_max": jd_max},
                   fn=_meta_fn)
    return fetch(spec)


def ztf_frame(ffd: str, field: int, filtercode: str, ccdid: int, qid: int,
              imgtypecode: str = "o", cfg=None) -> FetchResult:
    """下载单帧 sci 主图像（aria2 执行器，断点续传）。

    走 fetch 通道：缓存短路（命中不建 job）与收账语义由 jobs 层统一提供。
    """
    from ..config import Config
    cfg = cfg or Config()
    name = frame_name(ffd, field, filtercode, ccdid, qid, imgtypecode)
    dest = cfg.source_dir("ztf") / f"f{field:06d}" / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    spec = JobSpec(source="ztf", executor="aria2",
                   params={"name": name, "field": field,
                           "filtercode": filtercode},
                   url=ztf_sci_url(ffd, field, filtercode, ccdid, qid,
                                   imgtypecode),
                   dest=str(dest))
    return fetch(spec, poll=2.0)


def ztf_stack(field: int, filtercode: str = "zg", ccdid: int = 1, qid: int = 1,
              jd_min: float = 2458100, jd_max: float = 2461000,
              n: int = 3, dt_h_max: float = 4.0, cfg=None) -> list[FetchResult]:
    """取 n 帧时间上相近的 sci 图像（差异法找移动目标的数据准备）。"""
    import pandas as pd

    meta_res = ztf_metadata(field, filtercode, ccdid, qid, jd_min, jd_max)
    df = pd.read_parquet(meta_res.paths[0]).sort_values("obsjd").reset_index(drop=True)
    if len(df) < n:
        raise LookupError(f"仅 {len(df)} 帧可用，不足 {n}")
    # 选 seeing 最好且时间跨度最短的连续 n 帧
    best_i, best_span = 0, float("inf")
    for i in range(len(df) - n + 1):
        span = df.obsjd[i + n - 1] - df.obsjd[i]
        if span <= dt_h_max / 24 and span < best_span:
            best_i, best_span = i, span
    if best_span == float("inf"):
        raise LookupError(f"窗口 {dt_h_max}h 内无连续 {n} 帧")
    rows = df.iloc[best_i:best_i + n]
    return [ztf_frame(r.filefracday, field, filtercode, ccdid, qid,
                      r.imgtypecode, cfg=cfg)
            for r in rows.itertuples()]
