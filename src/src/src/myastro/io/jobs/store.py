"""落库与缓存：缓存命中判定、成功登记（datasets/files/meta/坐标）。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core import cache_key
from ..db import DB
from .spec import FetchResult, JobSpec


def _lookup_cached(db: DB, key: str) -> FetchResult | None:
    row = db.conn.execute(
        "SELECT id, meta_json FROM datasets WHERE cache_key=?", (key,)
    ).fetchone()
    if row is None:
        return None
    files = db.conn.execute(
        "SELECT path FROM files WHERE dataset_id=?", (row["id"],)).fetchall()
    paths = [Path(f["path"]) for f in files]
    if not paths or not all(p.exists() for p in paths):
        return None          # 文件缺失视为缓存失效
    meta: dict[str, Any] = {}
    if row["meta_json"]:
        try:
            meta = json.loads(row["meta_json"])
        except ValueError:                       # 历史脏数据不致命
            meta = {}
    return FetchResult(paths=paths, dataset_id=row["id"], cache_hit=True,
                       meta=meta)

def _assert_paths_inside_data_root(paths, source: str) -> None:
    """落盘路径必须在数据根内（机制型兜底，覆盖未来源）。

    第一道防线是 FieldSpec 的 name_like/pattern（输入即拒）；这一道防的是
    "新源忘了标注"——任务自己拼出的路径若逃出数据根（如 `..` 穿越），
    在这里以 ValueError 显式失败，而不是默默写到别处。
    校验发生在任何写库动作之前，失败不会留下半条记录。
    """
    from ..config import Config
    root = Config().data.resolve()
    for p in paths:
        resolved = Path(p).resolve()
        if root not in resolved.parents:           # 严格：必须在数据根之下
            raise ValueError(
                f"{source} 的产物路径逃出数据根：{resolved}（数据根 {root}）")


def _register_success(db: DB, spec: JobSpec, key: str, job_id: int,
                      result: FetchResult) -> int:
    _assert_paths_inside_data_root(result.paths, spec.source)
    # 注意：INSERT OR IGNORE 被忽略时 lastrowid 是陈旧值，不可用——
    # 一律按 cache_key 回查（唯一索引保证命中）
    db.conn.execute(
        "INSERT OR IGNORE INTO datasets(source, target, params_json, cache_key)"
        " VALUES(?, ?, ?, ?)",
        (spec.source, str(spec.params.get("target", "")),
         json.dumps(spec.params, ensure_ascii=False, default=str), key))
    dataset_id = db.conn.execute(
        "SELECT id FROM datasets WHERE cache_key=?", (key,)
    ).fetchone()["id"]
    if result.meta:            # meta 是溯源信息：写入账本，缓存命中时可回读
        db.conn.execute(
            "UPDATE datasets SET meta_json=? WHERE id=?",
            (json.dumps(result.meta, ensure_ascii=False, default=str),
             dataset_id))
    # 坐标在入库时解析一次（params/meta/索引/文件名兜底）→ 账本存 ra/dec，
    # 查询时零解析成本，SQL 也能做包围盒粗筛
    from ..coords import resolve_coords
    coord = resolve_coords(spec.source, spec.params, result.meta,
                           [str(p) for p in result.paths])
    if coord is not None:
        db.conn.execute("UPDATE datasets SET ra=?, dec=? WHERE id=?",
                        (coord[0], coord[1], dataset_id))
    for p in result.paths:
        db.conn.execute(
            "INSERT OR REPLACE INTO files(dataset_id, path, size, format)"
            " VALUES(?, ?, ?, ?)", (dataset_id, str(p), p.stat().st_size,
                                    p.suffix.lstrip(".")))
    db.conn.commit()
    return dataset_id

def check_cache(spec: JobSpec, db: DB | None = None) -> FetchResult | None:
    """缓存查询（fetch 的短路条件，独立可复用）：命中返回结果，否则 None。

    异步提交方（TUI）应在 submit 前调用，避免重复下单已有数据。
    """
    own = db is None
    db = db or DB().init()
    try:
        return _lookup_cached(db, cache_key(spec.source, spec.params))
    finally:
        if own:
            db.close()
