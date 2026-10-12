"""本地检索：按源/目标/文件名/时间/坐标查已有数据（capabilities §3）。

回答"这个天区/目标我取过没有"。坐标检索自 2026-10-09 起为**精确圆锥**：
账本存 ra/dec（入库时解析，见 coords.py）→ SQL 包围盒粗筛 → haversine 精判，
结果按角距升序并带 sep_deg。坐标未知的数据集不参与坐标检索。
"""
from __future__ import annotations

from pathlib import Path

from .coords import angular_separation
from .db import DB


def _validate_query(near, radius_deg, limit, since, until) -> None:
    """参数边界校验：越界/格式错一律显式报错，不做静默空结果。

    早期版本静默接受这些输入，后果是"看起来查过了其实什么也没查"：
      radius_deg=-1 → 0 条；near=(x, 95)（dec 越界）→ 0 条；
      limit=-1 → 返回"除最后 1 条外的全部"（切片语义，最隐蔽）；
      since="乱码" → 0 条。
    """
    import math
    import re

    if limit < 1:
        raise ValueError(f"limit 必须 ≥ 1（收到 {limit}）")
    if not (0 < radius_deg <= 180):
        raise ValueError(f"radius_deg 必须在 (0, 180] 内（收到 {radius_deg}）")
    if near is not None:
        if len(tuple(near)) != 2:
            raise ValueError(f"near 需要 (ra, dec) 两个值（收到 {near!r}）")
        ra, dec = float(near[0]), float(near[1])
        if not (math.isfinite(ra) and math.isfinite(dec)):
            raise ValueError(f"near 必须是有限数（收到 {near!r}）")
        if not -90.0 <= dec <= 90.0:
            raise ValueError(f"dec 必须在 [-90, 90] 内（收到 {dec}）")
    for label, value in (("since", since), ("until", until)):
        if value is None:
            continue
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}( \d{2}:\d{2}:\d{2})?", str(value)):
            raise ValueError(
                f"{label} 格式应为 YYYY-MM-DD[ HH:MM:SS]（收到 {value!r}）")


def search(source: str | None = None, target: str | None = None,
           name: str | None = None, since: str | None = None,
           until: str | None = None, near: tuple[float, float] | None = None,
           radius_deg: float = 0.1, limit: int = 50) -> list[dict]:
    """检索已入库数据集。

    target: 目标名（params 里 target 键的子串，如 WASP）
    name:   文件名子串
    since/until: created_at 范围（'YYYY-MM-DD'）
    near:   (ra, dec) **精确圆锥检索**（度）：SQL 包围盒粗筛 + haversine 精判，
            结果带 sep_deg 并按角距升序；坐标未知的数据集不参与
            （坐标在入库时解析并存入 datasets.ra/dec，见 io/coords.py）
    """
    import math

    _validate_query(near, radius_deg, limit, since, until)

    db = DB().init()
    q = ("SELECT d.id, d.source, d.target, d.params_json, d.created_at,"
         " d.ra, d.dec,"
         " (SELECT path FROM files f WHERE f.dataset_id=d.id LIMIT 1)"
         " AS path FROM datasets d WHERE 1=1")
    args: list = []
    if source:
        q += " AND d.source=?"
        args.append(source)
    if target:
        q += " AND d.params_json LIKE ?"
        args.append(f'%"{target}%')
    if since:
        q += " AND d.created_at >= ?"
        args.append(f"{since} 00:00:00")
    if until:
        q += " AND d.created_at <= ?"
        args.append(f"{until} 23:59:59")
    if near is not None:
        ra0 = float(near[0]) % 360.0
        dec0 = float(near[1])
        # 包围盒粗筛（SQL 端）：赤纬直接开窗；赤经按 cos(dec) 放大，
        # 并处理跨 0° 的情况（359° 与 1° 不能当成相距 358°）
        ra_half = radius_deg / max(math.cos(math.radians(dec0)), 1e-6)
        q += (" AND d.ra IS NOT NULL AND d.dec IS NOT NULL"
              " AND d.dec BETWEEN ? AND ?")
        args += [dec0 - radius_deg, dec0 + radius_deg]
        lo, hi = ra0 - ra_half, ra0 + ra_half
        if lo < 0.0 or hi >= 360.0:
            q += " AND (d.ra >= ? OR d.ra <= ?)"
            args += [lo % 360.0, hi % 360.0]
        else:
            q += " AND d.ra BETWEEN ? AND ?"
            args += [lo, hi]
    q += " ORDER BY d.id DESC"
    rows = db.conn.execute(q, args).fetchall()
    db.close()

    out = []
    for r in rows:
        if name and (not r["path"] or name not in Path(r["path"]).name):
            continue
        row = {"id": r["id"], "source": r["source"],
               "target": r["target"], "created": r["created_at"],
               "path": r["path"]}
        if near is not None:
            sep = angular_separation(ra0, dec0, float(r["ra"]),
                                     float(r["dec"]))
            if sep > radius_deg:
                continue                      # 盒角上的点在这里被剔除
            row["sep_deg"] = round(sep, 6)
        out.append(row)
    if near is not None:
        out.sort(key=lambda x: x["sep_deg"])   # 由近及远
    return out[:limit]


def coverage(index_name: str) -> dict:
    """索引覆盖率：本地已有 / 索引全量（capabilities §3 覆盖率统计）。"""
    from .index import INDEXES, load_index
    df = load_index(index_name)
    if df is None:
        raise LookupError(f"索引 {index_name} 未构建（myastro index update）")
    key = INDEXES[index_name].get("key_col", "brickname")
    total = len(df)
    index_values = set(df[key].astype(str))
    db = DB().init()
    local_names = {Path(r["path"]).name
                   for r in db.conn.execute(
                       "SELECT path FROM files").fetchall()}
    db.close()
    # 本地文件名 × 索引值子串判定：O(本地数 × 索引数)
    # （本地通常几十个，36 万索引值下秒级；量级反转时需前缀索引）
    hits = sum(1 for name in local_names
               if any(v in name for v in index_values))
    return {"index": index_name, "total": total, "local": hits,
            "pct": round(hits / total * 100, 2) if total else 0.0}
