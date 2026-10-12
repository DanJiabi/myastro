"""unWISE 中红外叠加切片（unwise.me cutout 服务）。

2026-10-09 实测澄清了三件事（此前实现全搞错了，导致 job #88 失败）：
1. `bands` 是**整数位掩码**：1=w1，2=w2。传 `w1` 字符串会让服务端
   `int('w')` 崩溃返回 500（错误页原文：invalid literal for int()）
2. 响应是 **tar.gz 压缩包**（content-type: application/x-compressed，
   filename=cutouts-fits_*.tar.gz），内含 4 个 FITS 成员：
   `*-img-m.fits`（图像）、`*-invvar-m.fits.gz`、`*-std-m.fits.gz`、
   `*-n-m.fits.gz`（辅助）
3. `bands=3`（w1+w2 合并）返回 0 字节 → 服务端不支持，故只提供 w1/w2

因此本源是 **python 执行器**：下载 → 解包 → 落 FITS（aria2 型无法解包，
且会把 tar.gz 原样存成 .fits）。
"""
from __future__ import annotations

import io
import tarfile
from pathlib import Path

from ..core import atomic_write, retry
from ..jobs import FetchResult, JobSpec, fetch

_URL = "https://unwise.me/cutout_fits"
BANDS: dict[str, int] = {"w1": 1, "w2": 2}      # 服务端位掩码（非名字）


def cutout_url(ra: float, dec: float, size: int, band: str) -> str:
    """生成 cutout URL；band 必须是 w1/w2（服务端要整数位掩码）。"""
    if band not in BANDS:
        raise ValueError(f"band 须为 {sorted(BANDS)}（服务端不支持合并波段）")
    return (f"{_URL}?version=neo7&ra={ra}&dec={dec}"
            f"&size={int(size)}&bands={BANDS[band]}")


def _download_unwise(ra: float, dec: float, size: int, band: str,
                     dest_dir: Path):
    """网络层：取 tar.gz → 解包 FITS 成员。返回 (paths, meta)。

    保留包内全部成员（图像 + invvar/std/n 辅助），不做信息裁剪。
    """
    import requests

    url = cutout_url(ra, dec, size, band)

    def _attempt() -> bytes:
        r = requests.get(url, timeout=300)
        r.raise_for_status()
        if not r.content:
            raise ConnectionError(f"unWISE 返回空响应（{url}）")
        return r.content

    blob = retry(_attempt)
    dest_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            if not member.name.endswith((".fits", ".fits.gz")):
                continue
            data = tar.extractfile(member)
            if data is None:
                continue
            name = Path(member.name).name
            out = dest_dir / name
            payload = data.read()          # 在闭包外读，避免默认参数里做副作用

            def _write(f, _payload=payload):
                f.write_bytes(_payload)

            atomic_write(out, _write)
            paths.append(out)
    if not paths:
        raise ConnectionError("unWISE 包内无 FITS 成员")
    meta = {"ra": ra, "dec": dec, "size": int(size), "band": band,
            "bands_bitmask": BANDS[band], "n_files": len(paths),
            "members": [p.name for p in paths]}
    return sorted(paths), meta


def _fn(ctx) -> FetchResult:
    p = ctx.params
    slug = f"unwise_{p['ra']}_{p['dec']}_{int(p['size'])}px_{p['band']}"
    paths, meta = _download_unwise(float(p["ra"]), float(p["dec"]),
                                   int(p["size"]), p["band"],
                                   ctx.dest_dir / slug)
    return FetchResult(paths=paths, dataset_id=-1, meta=meta)


def unwise_cutout(ra: float, dec: float, size: int = 300,
                  band: str = "w1") -> FetchResult:
    """unWISE 中红外切片（w1/w2，tar.gz 自动解包为 FITS）。"""
    spec = JobSpec(source="unwise", executor="python",
                   params={"ra": ra, "dec": dec, "size": size, "band": band},
                   task="unwise_cutout")
    return fetch(spec)
