"""TESS/Kepler/K2 光变曲线获取（lightkurve，python 执行器）。"""
from __future__ import annotations

import re
from pathlib import Path

from ..core import retry, write_parquet
from ..jobs import FetchResult, JobSpec, fetch

_CADENCE_EXP = {"2m": 120, "20s": 20, "10m": 600, "30m": 1800}


def _slug(name: str) -> str:
    """目标名 → 安全目录名。"""
    return re.sub(r"[^\w.-]+", "_", name).strip("_") or "unnamed"


# lightkurve 在 import 时会检查可选依赖 oktopus（TPF 像素建模 tpfmodel 用），
# 没装就打一条 UserWarning。我们从不使用 tpfmodel，这条提示对新用户只是噪音
# （它出现在 `myastro doctor` 与首次 TESS 取数的输出里），故按消息精确抑制；
# 安装 oktopus 不是选项：它停留在 2018 年（0.1.2）且需要 autograd。
LIGHTKURVE_OKTOPUS_NOISE = r".*tpfmodel submodule is not available.*"


def _import_lightkurve():
    """导入 lightkurve（抑制上述已知无害提示）。抽成函数便于测试。"""
    from ..core import quiet_warnings

    with quiet_warnings(LIGHTKURVE_OKTOPUS_NOISE):
        import lightkurve as lk

    return lk


def _download_lc(target: str, sector: int | None, cadence: str,
                 cache_dir: Path):
    """网络层：lightkurve 检索 + 下载（带重试）。返回 (df, meta)。"""
    lk = _import_lightkurve()

    result = lk.search_lightcurve(target, mission="TESS", cadence=cadence)
    if len(result) == 0:
        raise LookupError(f"{target}: TESS 无 {cadence} 光变数据")
    if sector is not None:
        mask = [f"Sector {sector}" in str(m) for m in result.table["mission"]]
        if not any(mask):
            sectors = sorted({int(re.search(r"Sector (\\d+)", str(m)).group(1))
                              for m in result.table["mission"]})
            raise LookupError(f"{target}: 无 sector {sector}（可用: {sectors}）")
        result = result[mask]

    def _attempt():
        try:
            return result[0].download(download_dir=str(cache_dir))
        except Exception as exc:
            import shutil
            shutil.rmtree(cache_dir / "mastDownload", ignore_errors=True)
            raise ConnectionError(f"lightkurve 下载/读取失败: {exc}") from exc

    lc = retry(_attempt)
    df = lc.to_pandas().reset_index()          # time, flux, flux_err, quality
    meta = {"target": target,
            "mission": str(lc.meta.get("MISSION", "TESS")),
            "sector": int(lc.meta.get("SECTOR", -1)),
            "cadence": cadence,
            "ra": float(lc.meta.get("RA_OBJ", float("nan"))),
            "dec": float(lc.meta.get("DEC_OBJ", float("nan")))}
    return df, meta


def _fn(ctx) -> FetchResult:
    df, meta = _download_lc(ctx.params["target"], ctx.params.get("sector"),
                            ctx.params["cadence"],
                            ctx.cfg.cache / "lightkurve")
    name = _slug(ctx.params["target"])
    dest = ctx.dest_dir / name / f"lc_s{meta['sector']}_{ctx.params['cadence']}.parquet"
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_parquet(df, dest)
    return FetchResult(paths=[dest], dataset_id=-1, meta=meta)


def tess_lightcurve(target: str, sector: int | None = None,
                    cadence: str = "2m") -> FetchResult:
    """获取目标的 TESS PDCSAP 光变曲线，落 parquet 并入库。

    cadence: '2m' | '20s' | '10m' | '30m'；sector 为空取检索结果第一条。
    """
    if cadence not in _CADENCE_EXP:
        raise ValueError(f"cadence 须为 {list(_CADENCE_EXP)}")
    spec = JobSpec(source="tess", executor="python",
                   params={"target": target, "sector": sector,
                           "cadence": cadence},
                   fn=_fn)
    return fetch(spec)
