"""MPC 星历（astroquery.mpc，JPL Horizons 的可达替代）。"""
from __future__ import annotations

from ..core import retry, write_parquet
from ..jobs import FetchResult, JobSpec, fetch


def _download_mpc(target: str, number: int, step_days: float):
    """网络层：MPC 星历表。返回 (df, meta)。"""
    from astroquery.mpc import MPC

    step = f"{step_days or 1.0}d"
    table = retry(lambda: MPC.get_ephemeris(
        target, number=number, step=step))
    df = table.to_pandas()
    meta = {"target": target, "n_rows": len(df),
            "step_days": step_days or 1.0}
    return df, meta


def _fn(ctx) -> FetchResult:
    p = ctx.params
    df, meta = _download_mpc(p["target"], p["number"],
                             p.get("step_days") or 1.0)
    name = p["target"].replace(" ", "_")
    step = p.get("step_days") or 1.0
    # 文件名必须编码**所有**影响内容的参数（number/step_days）——真实事故：
    # number=5 与 number=10 曾共用 `eph_Ceres.parquet`，后到者覆盖先到者的内容，
    # 账本上先到者就变成"有 dataset 无文件"的幽灵（#19/#39）。
    dest = ctx.dest_dir / f"eph_{name}_n{p['number']}_s{step}d.parquet"
    write_parquet(df, dest)
    return FetchResult(paths=[dest], dataset_id=-1, meta=meta)


def mpc_ephemeris(target: str, number: int = 10,
                  step_days: float = 1.0) -> FetchResult:
    """获取小行星/彗星在 MPC 的星历表 → parquet。"""
    spec = JobSpec(source="mpc", executor="python",
                   params={"target": target, "number": number,
                           "step_days": step_days},
                   task="mpc_ephemeris")
    return fetch(spec)
