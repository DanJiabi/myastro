"""ASAS-SN Sky Patrol v2（pyasassn 客户端）。

⚠ 网络状况（2026-10 实测）：官方后端 asassn-lb01.ifa.hawaii.edu:9006
DNS NXDOMAIN（8.8.8.8/1.1.1.1 均查无，上游 master 分支仍指向该地址），
疑似服务迁移中。实现保留，服务恢复即可用；变星光变当前以 TESS 替代
（见 notebooks/02）。设计文档网络矩阵已同步标注。

决策（2026-10-09）：**保留为休眠代码**——实现与 tests/test_m4_sources.py
的 TestAsassn 均不删除（防腐烂），服务恢复当天应跑一次真实锥搜验证；
若确认永久弃用，则实现/测试/SOURCES 条目一并删除（不留半截）。
"""
from __future__ import annotations

from ..core import atomic_write, retry
from ..jobs import FetchResult, JobSpec, fetch


def _download_asassn(ra: float, dec: float, radius_arcmin: float):
    """网络层：SkyPatrolClient 锥搜 + 下载光变。返回 (df, meta)。"""
    from pyasassn.client import SkyPatrolClient

    # SkyPatrolClient 的构造函数就会去拉服务端 schema，因此**构造失败**即服务不可达。
    # 直接把 urllib3 的原始异常抛出去，用户看到的是几十行重试栈却看不出结论；
    # 这里收敛成一句可执行的说明（该服务 2026-10 实测拒连，health 也在探）。
    try:
        client = SkyPatrolClient(verbose=False)
    except Exception as exc:
        raise ConnectionError(
            "ASAS-SN Sky Patrol v2 服务不可达"
            "（asassn-lb01.ifa.hawaii.edu:9006 拒绝连接）：上游服务可能已迁移或下线。"
            "用 `myastro health asassn` 查看当前状态；"
            "该源在服务恢复前不可用。") from exc

    def _attempt():
        result = client.cone_search(ra, dec, radius_arcmin,
                                    units="arcmin", catalog="stellar_main",
                                    download=True, threads=1)
        lcs = result.light_curves
        if not len(lcs):
            raise LookupError(f"({ra},{dec}) ±{radius_arcmin}' 无 ASAS-SN 目标")
        # 取离中心最近的一条
        import numpy as np
        s = result.summary
        d2 = ((s["ra_deg"] - ra) ** 2 +
              np.cos(np.deg2rad(dec)) ** 2 * (s["dec_deg"] - dec) ** 2)
        asas_sn_id = s.iloc[int(d2.values.argmin())]["asas_sn_id"]
        return lcs.loc[asas_sn_id] if hasattr(lcs, "loc") else lcs[asas_sn_id]

    lc = retry(_attempt)
    df = lc.reset_index()
    meta = {"ra": ra, "dec": dec, "radius_arcmin": radius_arcmin,
            "n_rows": len(df)}
    return df, meta


def _fn(ctx) -> FetchResult:
    p = ctx.params
    df, meta = _download_asassn(p["ra"], p["dec"], p["radius_arcmin"])
    dest = (ctx.dest_dir /
            f"lc_{p['ra']:.4f}_{p['dec']:+.4f}.parquet")
    atomic_write(dest, lambda f: df.to_parquet(f, index=False))
    return FetchResult(paths=[dest], dataset_id=-1, meta=meta)


def asassn_lightcurve(ra: float, dec: float,
                      radius_arcmin: float = 1.0) -> FetchResult:
    """获取离 (ra, dec) 最近的 ASAS-SN 目标光变曲线。"""
    if not 0 < radius_arcmin <= 60:
        raise ValueError("radius_arcmin 须在 (0, 60]")
    spec = JobSpec(source="asassn", executor="python",
                   params={"ra": ra, "dec": dec,
                           "radius_arcmin": radius_arcmin},
                   fn=_fn)
    return fetch(spec)
