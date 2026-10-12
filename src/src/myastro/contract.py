"""契约快照：把**对外可观察的契约面**固化成一份可比对的生成物。

为什么需要：0.2.0 → 0.3.5 的复盘里，对外契约其实零漂移（门面 33 项、facade 27 个函数、
CLI 24 个子命令、退出码 4 项、schema v1–v8 全未变），但**我是用正则数引号字符串量出来的，
数是错的**。手工统计会错，所以让机器守着：本模块生成快照，`tests/guards/` 里的守卫
逐字节比对，任何契约变化都必须显式重新生成并在 `docs/zh/dev/contract-changelog.md` 里写理由。

覆盖（= 契约面）：
- `facade_api`：`myastro.__all__` 的每一项及其参数（名/种类/默认值/注解字符串）
- `cli`：子命令名 + 每个子命令的选项字符串（**不含** help 文案）
- `exit_codes`：`cli.EXIT_CODES`
- `ledger_schema`：临时库里逐表的列（名/类型/notnull/pk）与 `user_version`
- `registries`：描述符源 → 任务名、URL 源名单、任务表键

不覆盖（进快照就是天天红，等于没有守卫）：docstring、help 文案、日志措辞、
内部私有函数、文件布局、版本号、时间、路径、平台信息。
"""
from __future__ import annotations

import inspect
import json
import re
import tempfile
from pathlib import Path
from typing import Any

# repr 里可能带内存地址（默认值是对象时），跨进程会抖 → 归一化
_ADDR_RE = re.compile(r"0x[0-9a-fA-F]+")

SNAPSHOT_REL = Path("docs") / "contract-snapshot.json"


def snapshot_path() -> Path:
    """快照文件位置：**源码仓库内**（与 test-map/doc-sync 同样只服务开发）。"""
    from .io.core import source_root

    return source_root() / SNAPSHOT_REL


def _norm_default(value: Any) -> str:
    return _ADDR_RE.sub("0xADDR", repr(value))


def _norm_annotation(annotation: Any) -> str:
    """注解 → 稳定字符串。

    我们所有模块都有 `from __future__ import annotations`，因此
    `inspect.signature` 拿到的本来就是字符串；这里再抹掉模块前缀，
    避免同一类型因导入路径不同而抖动。
    """
    if annotation is inspect.Parameter.empty:
        return ""
    text = annotation if isinstance(annotation, str) else (
        getattr(annotation, "__qualname__", None)
        or getattr(annotation, "__name__", None) or str(annotation))
    for prefix in ("myastro.", "typing.", "collections.abc.", "pathlib."):
        text = text.replace(prefix, "")
    return text


def _signature_of(obj: Any) -> dict[str, Any] | None:
    """可调用对象 → {参数名: [种类, 默认值, 注解]}；取不到签名返回 None。"""
    try:
        if inspect.isclass(obj):
            sig = inspect.signature(obj.__init__)
            params = list(sig.parameters.values())[1:]        # 去掉 self
        else:
            params = list(inspect.signature(obj).parameters.values())
    except (TypeError, ValueError):
        return None
    return {
        p.name: [p.kind.name, _norm_default(p.default)
                 if p.default is not inspect.Parameter.empty else None,
                 _norm_annotation(p.annotation)]
        for p in params
    }


def _facade_api() -> dict[str, Any]:
    import myastro as ma

    out: dict[str, Any] = {}
    for name in sorted(ma.__all__):
        obj = getattr(ma, name)
        entry: dict[str, Any] = {"kind": type(obj).__name__}
        if callable(obj):
            sig = _signature_of(obj)
            if sig is not None:
                entry["params"] = sig
        out[name] = entry
    return out


def _exit_codes() -> dict[str, int]:
    from .cli import EXIT_CODES

    return dict(sorted(EXIT_CODES.items()))


def _walk_parser(parser, prefix: str, out: dict[str, list[str]]) -> None:
    """递归收集子命令（`schedule install` 这类嵌套命令同样是契约面）。"""
    for action in parser._actions:
        choices = getattr(action, "choices", None)
        if not choices or not isinstance(choices, dict):
            continue
        for name, sub in sorted(choices.items()):
            path = f"{prefix}{name}"
            out[path] = sorted({opt for a in sub._actions
                                for opt in a.option_strings})
            _walk_parser(sub, f"{path} ", out)


def _cli() -> dict[str, Any]:
    from .cli import _build_parser

    commands: dict[str, list[str]] = {}
    _walk_parser(_build_parser(), "", commands)
    return {"commands": commands}


def _ledger_schema() -> dict[str, Any]:
    from .io.db import DB

    with tempfile.TemporaryDirectory() as tmp:
        db = DB(Path(tmp) / "snapshot.db").init()
        try:
            tables = [r[0] for r in db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
                " AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            schema: dict[str, Any] = {}
            for table in tables:
                cols = db.conn.execute(f"PRAGMA table_info({table})").fetchall()
                schema[table] = [
                    {"name": c[1], "type": c[2], "notnull": bool(c[3]),
                     "pk": bool(c[5])}
                    for c in cols]
            version = db.conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            db.close()
    return {"user_version": version, "tables": schema}


def _registries() -> dict[str, Any]:
    from .descriptors import REGISTRY
    from .io.urls import URL_SOURCES
    from .tasks import TASKS

    return {
        "descriptors": {name: (d.task or "") for name, d in sorted(REGISTRY.items())},
        "url_sources": sorted(URL_SOURCES),
        "tasks": sorted(TASKS),
    }


def snapshot() -> dict[str, Any]:
    """生成契约快照（纯函数；不读仓库里的旧快照）。"""
    return {
        "facade_api": _facade_api(),
        "cli": _cli(),
        "exit_codes": _exit_codes(),
        "ledger_schema": _ledger_schema(),
        "registries": _registries(),
    }


def dumps(data: dict[str, Any] | None = None) -> str:
    """快照 → 稳定文本（排序 + 缩进 + 末尾换行），便于逐字节比对。"""
    return json.dumps(data if data is not None else snapshot(),
                      ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def problems(path: Path | None = None) -> list[str]:
    """与仓库内快照的差异（守卫与 `--check` 共用）。

    只报**逐区块的增删改**，让失败信息能直接指向"改了哪一项"。
    """
    target = Path(path) if path is not None else snapshot_path()
    if not target.exists():
        return [f"缺少契约快照 {target}（生成：myastro contract-snapshot）"]
    try:
        saved = json.loads(target.read_text())
    except json.JSONDecodeError as e:
        return [f"契约快照不是合法 JSON：{e}"]
    current = snapshot()
    out: list[str] = []
    for section in sorted(set(saved) | set(current)):
        old, new = saved.get(section), current.get(section)
        if old == new:
            continue
        if not isinstance(old, dict) or not isinstance(new, dict):
            out.append(f"{section}: 整体不同")
            continue
        for key in sorted(set(old) | set(new)):
            if old.get(key) == new.get(key):
                continue
            if key not in old:
                out.append(f"{section}.{key}: 新增（代码里有、快照里没有 → "
                           f"若是有意的契约变更，重新生成快照并登记到 "
                           f"docs/zh/dev/contract-changelog.md）")
            elif key not in new:
                out.append(f"{section}.{key}: 删除（快照里有、代码里没有 → 同上）")
            else:
                out.append(f"{section}.{key}: 变化\n    旧 {old[key]!r}\n    新 {new[key]!r}")
    return out
