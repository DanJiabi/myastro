"""面板体系：Pane 契约 + 各面板实现（注册表驱动，App 零业务）。"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:                      # 前向引用仅类型检查期导入
    from .app import AstroTop

from datetime import UTC
from pathlib import Path

from .. import aria2
from ..config import Config
from ..db import DB
from ..sources import SOURCES, executor_display, status_display


def _params_summary(params_json: str | None) -> str:
    """params_json → 短摘要：取最有辨识度的 2 个键值。"""
    import json as _json
    try:
        p = _json.loads(params_json or "{}")
    except ValueError:
        return "—"
    for k in ("sector", "radius_deg", "jd_min", "radius_arcmin", "cadence"):
        if k in p:
            v = p[k]
            rest = [f"{k}={v}"]
            for k2 in ("cadence", "filtercode", "sector"):
                if k2 != k and k2 in p:
                    rest.append(f"{k2}={p[k2]}")
                    break
            return " ".join(rest)
    return "—"


def _fmt_time(utc: str | None) -> str:
    """库内 UTC 时间串 → 本地时区显示（存储保持 UTC，显示层转换）。"""
    from datetime import datetime
    if not utc:
        return "—"
    try:
        dt = datetime.strptime(utc, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=UTC)
        return dt.astimezone().strftime("%m-%d %H:%M")
    except ValueError:
        return utc      # 非标准串原样返回


def fmt_size(n: float | None) -> str:
    """自适应体积单位：B → KB → MB → GB → TB。"""
    n = n or 0
    for unit, step in (("B", 1), ("KB", 1e3), ("MB", 1e6),
                       ("GB", 1e9), ("TB", 1e12)):
        if n < step * 1000 or unit == "TB":
            if unit == "B":
                return f"{int(n)} B"
            return f"{n/step:,.1f} {unit}"
    return f"{n/1e12:,.1f} TB"                        # pragma: no cover


# ══════════════════════════ 面板抽象 ══════════════════════════

class Pane:
    """面板契约：App 框架只认这三个方法 + 类属性。"""

    name: str = "?"            # 内部标识（切换/状态显示）
    label: str = "?"           # 键位栏/边框用中文名
    allows_job_actions: bool = False   # r/x 键是否作用于本面板

    def columns(self) -> tuple[str, ...]:
        raise NotImplementedError

    def rows(self) -> list[tuple]:
        raise NotImplementedError

    def detail(self, key) -> str | None:
        """按条目身份（渲染行首列值）返回详情文本；None = 无详情。

        身份寻址（而非行号）：与排序/过滤/刷新后的行位置无关，
        结构上杜绝"行号在两个顺序中指向不同条目"这一类 bug。
        """
        return None

    def drill(self, app: AstroTop, key) -> None:
        """可选：d 键下钻（接收条目身份，默认无）。"""
        return


class JobsPane(Pane):
    name, label, allows_job_actions = "jobs", "作业", True

    FILTERS = ("all", "active", "failed", "done")   # f 键循环

    def __init__(self) -> None:
        self.filter_mode = "all"

    def _data(self, filtered: bool = False) -> list[dict]:
        db = DB().init()
        rows = db.conn.execute(
            "SELECT j.id, j.executor, j.status, j.progress, j.error,"
            " j.updated_at, j.gid, j.dataset_id, j.spec_json,"
            " json_extract(j.spec_json, '$.source') AS src,"
            " d.target AS ds_target,"
            " (SELECT COUNT(*) FROM files f"
            "  WHERE f.dataset_id = j.dataset_id) AS ds_n,"
            " (SELECT SUM(size) FROM files f"
            "  WHERE f.dataset_id = j.dataset_id) AS ds_size,"
            " (SELECT path FROM files f WHERE f.dataset_id = j.dataset_id"
            "  LIMIT 1) AS ds_path"
            " FROM jobs j LEFT JOIN datasets d ON d.id = j.dataset_id"
            " ORDER BY j.id DESC LIMIT 100").fetchall()
        db.close()
        data = [dict(r) for r in rows]
        if filtered and self.filter_mode != "all":
            if self.filter_mode == "active":
                data = [r for r in data
                        if r["status"] in ("running", "queued")]
            else:
                data = [r for r in data if r["status"] == self.filter_mode]
        return data

    def _outcome(self, r) -> str:
        """产出列：文件名（多文件 +N）/总体积/文件状态。

        文件在盘检查取首个文件（多文件 dataset 目前不存在；出现后
        需升级为逐文件核对，enter 详情可看全部路径）。
        """
        if not r["dataset_id"] or not r["ds_n"]:
            return "—"
        mark = ""
        if r["ds_path"] is not None:
            mark = "✓" if Path(r["ds_path"]).exists() else "✗缺失"
        name = Path(r["ds_path"]).name if r["ds_path"] else \
            (r["ds_target"] or "—")
        if r["ds_n"] > 1:
            name = f"{name} +{r['ds_n'] - 1}"
        size = f" {fmt_size(r['ds_size'])}" if r["ds_size"] else ""
        return f"{name}{size} {mark}".strip()

    def cycle_filter(self) -> str:
        i = self.FILTERS.index(self.filter_mode)
        self.filter_mode = self.FILTERS[(i + 1) % len(self.FILTERS)]
        return self.filter_mode

    def columns(self):
        return ("job", "source", "status", "产出", "error", "updated")

    def rows(self, desc: bool = True):
        data = self._data(filtered=True)
        live = {}
        if data and aria2.ping():
            for r in data:
                if r["executor"] == "aria2" and r["gid"] and \
                        r["status"] == "running":
                    try:
                        live[r["id"]] = aria2.status(r["gid"])
                    except Exception:  # noqa: BLE001, S110                   # noqa: BLE001
                        pass
        out = []
        for r in data:
            status = r["status"]
            if r["id"] in live and live[r["id"]]["status"] == "active":
                s = live[r["id"]]
                pct = (float(s["completedLength"])
                       / max(float(s["totalLength"]), 1) * 100)
                status = f"↓ {pct:.0f}% {float(s['downloadSpeed'])/1e3:.0f}KB/s"
            out.append((f"#{r['id']}", r["src"] or "—", status,
                        self._outcome(r), (r["error"] or "")[:36],
                        _fmt_time(r["updated_at"])))
        return out if desc else out[::-1]

    def detail(self, key):
        job = self.selected_job(key)
        if job is None:
            return None
        return (f" job {job['id']} | gid={job['gid']} | "
                f"dataset={job['dataset_id']}"
                f" | 更新 {_fmt_time(job['updated_at'])}\n"
                f" spec: {job['spec_json'][:300]}\n error: {job['error']}")

    def selected_job(self, key) -> dict | None:
        """按 job id 直查（身份寻址，与显示顺序无关）。"""
        try:
            job_id = int(str(key).lstrip("#"))
        except (TypeError, ValueError):
            return None
        db = DB().init()
        row = db.conn.execute(
            "SELECT id, executor, status, progress, error, updated_at, gid,"
            " dataset_id, spec_json FROM jobs WHERE id=?", (job_id,)).fetchone()
        db.close()
        return dict(row) if row else None


class InfoPane(Pane):
    name, label = "info", "数据源"

    def columns(self):
        return ("数据源", "状态", "说明")

    def rows(self, desc: bool = True):                  # desc 未用：注册表固定顺序
        # 执行器列已移除（E1）；新鲜探测结果（<24h）覆盖声明基线
        from ..health import health_view
        fresh = health_view()
        out = []
        for n, s in SOURCES.items():
            status = status_display(s)
            h = fresh.get(n)
            if h and h["status"] != s["status"]:
                mark = {"ok": "✅ 可用", "degraded": "⚠ 服务故障",
                        "unreachable": "❌ 不可达"}.get(h["status"], "?")
                status = f"{mark}（探测）"
            out.append((n, status, s["desc"]))
        return out

    def detail(self, key):
        s = SOURCES.get(str(key))
        if s is None:
            return None
        name = str(key)
        return (f" {name} — {s['desc']}\n 状态: {status_display(s)}"
                f"  执行器: {executor_display(s)}\n"
                " 示例:\n   " + s["example"].replace("\n", "\n   ") +
                f"\n 备注: {s['note']}")


# 磁盘实扫结果缓存：数据根 → (时刻, 字节数)
# 为什么只缓存扫描而不缓存整行：账本部分要实时（下钻/删除后立刻反映），
# 而 rglob 在 NFS 上实测 ~105ms，每 2 秒一次纯属浪费。
_DISK_SCAN_TTL = 10.0
_DISK_SCAN: dict[str, tuple[float, int]] = {}


def _disk_usage(root, ttl: float | None = None) -> int:
    """数据根实际占用（排除 macOS 的 ._* AppleDouble 文件），带 TTL 缓存。

    ttl 缺省取模块级 `_DISK_SCAN_TTL`（运行期解析：便于测试与将来配置化）。
    """
    import time

    ttl = _DISK_SCAN_TTL if ttl is None else ttl
    key = str(root)
    now = time.monotonic()
    cached = _DISK_SCAN.get(key)
    if cached is not None and now - cached[0] < ttl:
        return cached[1]
    usage = sum(f.stat().st_size for f in root.rglob("*")
                if f.is_file() and not f.name.startswith("._"))
    _DISK_SCAN[key] = (now, usage)
    return usage


class StoragePane(Pane):
    name, label = "storage", "存储"

    def columns(self):
        return ("mission", "体积", "文件数", "备注")

    def rows(self, desc: bool = True):                  # desc 未用：物理聚合无方向语义
        db = DB().init()
        files = db.conn.execute("SELECT path, size FROM files").fetchall()
        db.close()
        by_mission: dict[str, list[int]] = {}
        missing = 0
        root = Config().data
        for f in files:
            p = Path(f["path"])
            mission = p.relative_to(root).parts[0] \
                if root in p.parents else p.parts[-3]
            by_mission.setdefault(mission, []).append(f["size"])
            if not p.exists():
                missing += 1
        out = []
        for m, sizes in sorted(by_mission.items(),
                               key=lambda kv: -sum(kv[1])):
            out.append((m, fmt_size(sum(sizes)), len(sizes), ""))
        out.append(("(目录实扫)", fmt_size(_disk_usage(root)), "—",
                    f"库记录缺失 {missing}" if missing else ""))
        return out

    def drill(self, app: AstroTop, key) -> None:
        name = str(key)
        if name.startswith("("):            # 汇总行不可下钻
            return
        app.enter_assets(name)


class AssetsPane(Pane):
    """单源资产视图：不直接切换进入，由 storage 下钻或 data 面板复用渲染。"""

    name, label = "assets", "本地资产"
    source: str | None = None       # None = 全局时间线（data 面板复用）

    def columns(self):
        # source 始终显示：下钻目录名 ≠ source 名（legacy/ vs legacy-surveys）
        return ("dataset", "source", "文件名", "文件", "体积", "参数", "created")

    def rows(self, desc: bool = True):
        db = DB().init()
        if self.source is None:
            rows = db.conn.execute(
                "SELECT d.id, d.source, d.target, d.params_json,"
                " d.created_at, f.path, f.size, f.format FROM datasets d"
                " LEFT JOIN files f ON f.dataset_id = d.id"
                " ORDER BY d.id DESC LIMIT 200").fetchall()
        else:
            # 物理下钻：按 data root 下的目录前缀过滤（目录名不必等于
            # datasets.source——如 legacy/ 目录 vs source=legacy-surveys）
            prefix = str(Config().data / self.source) + "/%"
            rows = db.conn.execute(
                "SELECT d.id, d.source, d.target, d.params_json,"
                " d.created_at, f.path, f.size, f.format FROM datasets d"
                " JOIN files f ON f.dataset_id = d.id"
                " WHERE f.path LIKE ?"
                " ORDER BY d.id DESC LIMIT 200", (prefix,)).fetchall()
        db.close()
        # 每 dataset 聚合：总体积、文件名列表（多文件取首个 +N）
        sizes_total: dict[int, int] = {}
        names: dict[int, list[str]] = {}
        for r in rows:
            if not r["path"]:
                continue
            sizes_total[r["id"]] = sizes_total.get(r["id"], 0) + (r["size"] or 0)
            names.setdefault(r["id"], []).append(Path(r["path"]).name)
        exists_cache: dict[int, bool] = {}

        out = []
        for r in rows:
            path = r["path"]
            if path is None:
                mark, size, name = "（无文件记录）", "—", "—"
            else:
                if r["id"] not in exists_cache:
                    exists_cache[r["id"]] = Path(path).exists()
                mark = "✓" if exists_cache[r["id"]] else "✗ 文件缺失"
                size = fmt_size(sizes_total.get(r["id"]))
                ns = names.get(r["id"], [])
                name = (ns[0] if ns else "—") + \
                    (f" +{len(ns) - 1}" if len(ns) > 1 else "")
            out.append((r["id"], r["source"], name, mark, size,
                        _params_summary(r["params_json"]),
                        _fmt_time(r["created_at"])))
        # JOIN 展开导致同 dataset 多行，去重
        seen, dedup = set(), []
        for row in out:
            if row[0] not in seen:
                seen.add(row[0])
                dedup.append(row)
        return dedup if desc else dedup[::-1]

    def detail(self, key):
        try:
            ds_id = int(key)
        except (TypeError, ValueError):
            return None
        db = DB().init()
        row = db.conn.execute(
            "SELECT params_json, created_at FROM datasets WHERE id=?",
            (ds_id,)).fetchone()
        files = db.conn.execute(
            "SELECT path FROM files WHERE dataset_id=?", (ds_id,)).fetchall()
        frows = db.conn.execute(
            "SELECT format FROM files WHERE dataset_id=?", (ds_id,)).fetchall()
        db.close()
        if not row:
            return None
        from ..types import type_info
        ti = {f: type_info(f) for f in {r["format"] for r in frows} if f}
        type_lines = "\n".join(
            f" {v['label']}（{k}）: {v['desc']}\n   读取: {v['load']}"
            for k, v in ti.items()) or " （无文件）"
        return (f" dataset #{ds_id} | {_fmt_time(row['created_at'])}\n"
                f" params: {row['params_json']}\n"
                " files:\n   " + "\n   ".join(f["path"] for f in files)
                + "\n 类型:\n" + type_lines)


# 注册表：键位顺序即面板顺序。新增面板在此登记。
# data（时间线）面板已裁撤（2026-10）：内容与 jobs 产出列重叠，
# 资产浏览走 storage 下钻（AssetsPane），跨源全集走 CLI/SQL。
PANES: dict[str, Pane] = {
    p.name: p for p in (InfoPane(), JobsPane(), StoragePane())
}
PANE_KEYS = {"0": "info", "1": "jobs", "2": "storage"}


REFRESH_S = 2.0
