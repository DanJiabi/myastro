"""manifest 批量提交（yaml → aria2 job 列表）。"""
from __future__ import annotations

from pathlib import Path

import yaml

from .config import Config
from .jobs import JobSpec, submit

_KEYS = {"source", "dest_dir", "files"}


def parse_manifest(path: str | Path, cfg: Config | None = None) -> list[JobSpec]:
    """manifest 结构：
    source: legacy-surveys
    dest_dir: legacy/dr10/w44/     # 相对 data root
    files:
      - https://.../tractor-4442p000.fits
      - url: https://...
        out: 重命名.fits
    """
    cfg = cfg or Config()
    doc = yaml.safe_load(Path(path).read_text())
    unknown = set(doc) - _KEYS
    if unknown:
        raise ValueError(f"manifest 未知字段: {unknown}")
    dest_dir = cfg.data / doc.get("dest_dir", "manifest")
    dest_dir.mkdir(parents=True, exist_ok=True)
    specs = []
    for entry in doc["files"]:
        if isinstance(entry, str):
            url, out = entry, None
        else:
            url, out = entry["url"], entry.get("out")
        name = out or url.rsplit("/", 1)[-1]
        specs.append(JobSpec(
            source=doc.get("source", "manifest"),
            params={"url": url},
            executor="aria2", url=url,
            dest=str(dest_dir / name)))
    return specs


def submit_manifest(path: str | Path, cfg: Config | None = None) -> list[int]:
    """解析并批量提交，返回 job_id 列表（用 jobs.wait 逐个收）。"""
    return [submit(spec) for spec in parse_manifest(path, cfg)]
