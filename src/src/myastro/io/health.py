"""源健康监测：定期探测后端可达性，结果落库（capabilities §1）。

两层状态模型：
- SOURCES.status     声明基线（代码里的人工判断，如 asassn=unreachable）
- health 表          运行时探测覆盖（probe 实测，TUI 显示时新鲜则覆盖）

探测判级：连接/DNS 失败 → unreachable；HTTP 5xx/4xx → degraded（服务在但
异常）；2xx/3xx → ok。

⚠ 探测深度：PROBES 的 URL 决定"探到哪一层"。只探域名根会**说谎**——
unwise 的根路径恒为 200，而真正的 `/cutout_fits` 因参数错误返 500
（job #88 的真实教训）。因此凡能给出"合法最小请求"的源，都应填该请求；
本探针只验证可达性与 HTTP 层，不做业务级校验（数据正确性归 tests/ 管）。
"""
from __future__ import annotations

from datetime import UTC, datetime

import requests

from .db import DB

# 源 → 探测端点（基础设施可达性；None = 不可探测，如 manifest）
PROBES: dict[str, str | None] = {
    "tess": "https://archive.stsci.edu",
    "gaia": "https://gea.esac.esa.int",
    "ztf": "https://irsa.ipac.caltech.edu",
    "ztf-meta": "https://irsa.ipac.caltech.edu",
    "ztf-lc": "https://irsa.ipac.caltech.edu",
    "exoplanet": "https://exoplanetarchive.ipac.caltech.edu",
    "mpc": "https://minorplanetcenter.net",
    "simbad": "https://simbad.cds.unistra.fr",
    "vizier": "https://vizier.cds.unistra.fr",
    "legacy": "https://portal.nersc.gov",
    # 端到端可用的最小请求（域名根 200 ≠ API 可用：曾因 bands 传字符串
    # 让 /cutout_fits 返 500，而根路径仍是 200 —— 探测必须打到服务端点）
    "unwise": ("https://unwise.me/cutout_fits?version=neo7"
               "&ra=180&dec=0&size=8&bands=1"),
    "asassn": "http://asassn-lb01.ifa.hawaii.edu:9006",
    "horizons": "https://ssd.jpl.nasa.gov",
    "manifest": None,
}


def _probe_one(url: str, timeout: float = 10.0) -> tuple[str, str]:
    try:
        r = requests.head(url, timeout=timeout, allow_redirects=True)
        if r.status_code < 400:
            return "ok", f"HTTP {r.status_code}"
        return "degraded", f"HTTP {r.status_code}"
    except requests.ConnectionError as e:
        return "unreachable", str(e)[:80]
    except requests.Timeout:
        return "unreachable", "timeout"
    except requests.RequestException as e:
        return "degraded", str(e)[:80]


def probe(source: str | None = None, db: DB | None = None) -> list[dict]:
    """探测（单源或全部），结果 upsert 到 health 表并返回。"""
    own = db is None
    db = db or DB().init()
    try:
        targets = ([source] if source else
                   [s for s, url in PROBES.items() if url])
        if source and PROBES.get(source) is None:
            raise LookupError(f"{source} 不可探测（无端点）")
        out = []
        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        for s in targets:
            status, detail = _probe_one(PROBES[s])
            db.conn.execute(
                "INSERT INTO health(source, status, detail, checked_at)"
                " VALUES(?, ?, ?, ?)"
                " ON CONFLICT(source) DO UPDATE SET status=excluded.status,"
                " detail=excluded.detail, checked_at=excluded.checked_at",
                (s, status, detail, now))
            out.append({"source": s, "status": status, "detail": detail,
                        "checked_at": now})
        db.conn.commit()
        return out
    finally:
        if own:
            db.close()


def health_view(db: DB | None = None, max_age_h: float = 24.0) -> dict[str, dict]:
    """新鲜探测结果（< max_age_h），供显示层覆盖声明基线。"""
    db = db or DB().init()
    rows = db.conn.execute(
        "SELECT source, status, detail, checked_at FROM health"
        " WHERE checked_at > datetime('now', ?)",
        (f"-{int(max_age_h * 3600)} seconds",)).fetchall()
    db.close()
    return {r["source"]: dict(r) for r in rows}
