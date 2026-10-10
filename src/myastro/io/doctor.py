"""环境自检（`myastro doctor`）：装完第一件事能自证"我这里能不能用"。

设计原则：
- **不抛异常**：每一项独立 try/except，失败也变成一条检查结果——自检工具本身
  崩掉最没用。返回结构给门面/CLI/第三方共用。
- **每条带修复建议**：只报"不 OK"没用处，要说清下一步做什么命令。
- 检查项按"会让人白折腾"的顺序：依赖 → 路径可写 → 账本可用 → 库文件系统
  （SQLite 与 NFS 不兼容）→ 索引 → 平台能力 → 是否在源码仓库。
"""
from __future__ import annotations

import importlib
import importlib.metadata as md
import json
import platform
import re
import sqlite3
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

OK, WARN, FAIL = "ok", "warn", "fail"

# 核心依赖：(import 名, 发行名, 最低版本)。TLS 2.0 起 API 与 1.x 不同，
# 1.x 会让 lc.period_search 直接报错，所以给硬下限。
CORE_DEPS: list[tuple[str, str, str | None]] = [
    ("astropy", "astropy", None),
    ("astroquery", "astroquery", None),
    ("lightkurve", "lightkurve", None),
    ("numpy", "numpy", None),
    ("pandas", "pandas", None),
    ("pyarrow", "pyarrow", None),
    ("yaml", "PyYAML", None),
    ("requests", "requests", None),
    ("textual", "textual", None),
    ("transitleastsquares", "transitleastsquares", "2.0"),
]
OPTIONAL_DEPS: list[tuple[str, str, str]] = [
    ("pyasassn", "pyasassn", "asassn 源"),
    ("ztfquery", "ztfquery", "ztf-fields 索引构建"),
]
NETWORK_FS = {"nfs", "nfs4", "cifs", "smbfs", "afpfs", "fuse.sshfs", "fuse.s3fs"}


@dataclass
class Check:
    name: str
    status: str
    detail: str
    fix: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def _vtuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:4]) or (0,)


def _fs_type(path: Path) -> str | None:
    """尽力判断路径所在文件系统类型（用于拦"账本放在 NFS 上"）。

    平台差异：Linux 读 /proc/mounts；macOS 没有 -T，改用 `mount` 输出解析
    （形如 `/dev/disk3s5 on /System/Volumes/Data (apfs, local, ...)`）。
    注意 `stat -f %T` 在 macOS 上是"文件类型"而非文件系统类型（实测返回空）。
    路径尚不存在时，用最近的已存在祖先。
    """
    import subprocess

    target = path
    while not target.exists() and target != target.parent:
        target = target.parent
    resolved = str(target.resolve())
    try:
        if platform.system() == "Linux":
            candidates = [ln.split() for ln in
                          Path("/proc/mounts").read_text().splitlines()]
            entries = [(m[1], m[2]) for m in candidates if len(m) >= 3]
        elif platform.system() == "Darwin":
            out = subprocess.run(["mount"], capture_output=True, text=True,
                                 timeout=5, check=False).stdout
            entries = []
            for line in out.splitlines():
                m = re.match(r"\S+ on (.+?) \((\w+)", line)
                if m:
                    entries.append((m.group(1), m.group(2)))
        else:
            return None
    except Exception:                                # noqa: BLE001 — 尽力而为
        return None
    best: tuple[str, str] | None = None
    for mountpoint, fstype in entries:
        matched = (resolved == mountpoint
                   or resolved.startswith(mountpoint.rstrip("/") + "/"))
        if matched and (best is None or len(mountpoint) > len(best[0])):
            best = (mountpoint, fstype)      # 取最长的匹配挂载点
    return best[1] if best else None


def _check_deps() -> list[Check]:
    out = []
    for mod, dist, minimum in CORE_DEPS:
        try:
            importlib.import_module(mod)
            ver = md.version(dist)
        except Exception as e:                       # noqa: BLE001
            out.append(Check(f"依赖 {dist}", FAIL,
                             f"不可用：{type(e).__name__}: {e}",
                             "pip install myastro（或 pip install -c constraints.txt myastro）"))
            continue
        if minimum and _vtuple(ver) < _vtuple(minimum):
            out.append(Check(f"依赖 {dist}", FAIL,
                             f"版本 {ver} 低于要求的 {minimum}",
                             f"pip install -U '{dist}>={minimum}'"))
        else:
            out.append(Check(f"依赖 {dist}", OK, ver))
    for mod, dist, why in OPTIONAL_DEPS:
        try:
            importlib.import_module(mod)
            out.append(Check(f"可选 {dist}", OK, f"{md.version(dist)}（{why}）"))
        except Exception:                            # noqa: BLE001
            out.append(Check(f"可选 {dist}", WARN, f"未安装（{why} 不可用）",
                             f"pip install 'myastro[{dist if dist != 'ztfquery' else 'ztfquery'}]'"))
    return out


def _check_paths(cfg) -> list[Check]:
    import os

    out = []
    if not os.environ.get("MYASTRO_DATA"):
        out.append(Check(
            "数据根来源", WARN,
            f"未设置 MYASTRO_DATA，使用内置默认 {cfg.data}",
            "数据放在别处（NAS/多盘）建议显式设置：export MYASTRO_DATA=/你的/数据根"))
    for label, path in (("数据根", cfg.data), ("账本父目录", cfg.db.parent)):
        try:
            path.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=path, prefix=".myastro-doctor-",
                                             delete=True):
                pass
            out.append(Check(f"{label}可写", OK, str(path)))
        except Exception as e:                       # noqa: BLE001
            out.append(Check(f"{label}可写", FAIL,
                             f"{path}：{type(e).__name__}: {e}",
                             "设置 MYASTRO_DATA / MYASTRO_DB 到可写位置"))
    fs = _fs_type(cfg.db)
    if fs is None:
        out.append(Check("账本文件系统", WARN, "无法判断（跳过）",
                         "确认 astro.db 在本地磁盘（SQLite WAL 与 NFS 不兼容）"))
    elif fs.lower() in NETWORK_FS:
        out.append(Check("账本文件系统", FAIL,
                         f"{fs}：{cfg.db}",
                         "把 MYASTRO_DB 指到本地磁盘（网络盘只适合放数据根）"))
    else:
        out.append(Check("账本文件系统", OK, f"{fs}（本地）"))
    return out


def _check_ledger(cfg, sample: int) -> list[Check]:
    from .db import DB, SCHEMA_VERSION

    out: list[Check] = []
    if not cfg.db.exists():
        out.append(Check("账本", WARN, f"尚未创建（{cfg.db}）",
                         "myastro init（或直接跑任意命令自动建库）"))
        return out
    try:
        conn = sqlite3.connect(f"file:{cfg.db}?mode=ro", uri=True)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
        counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("datasets", "files", "jobs", "health")}
        rows = conn.execute("SELECT path FROM files LIMIT ?", (sample,)).fetchall()
        conn.close()
    except Exception as e:                           # noqa: BLE001
        out.append(Check("账本可读", FAIL, f"{type(e).__name__}: {e}",
                         "从备份恢复：myastro restore --from <备份目录> --force"))
        return out

    if version > SCHEMA_VERSION:
        out.append(Check("schema 版本", FAIL,
                         f"库 {version} 比代码 {SCHEMA_VERSION} 新",
                         "升级 myastro：pip install -U myastro"))
    elif version < SCHEMA_VERSION:
        out.append(Check("schema 版本", WARN,
                         f"库 {version} → 代码 {SCHEMA_VERSION}（下次写入自动迁移）"))
    else:
        out.append(Check("schema 版本", OK, str(version)))
    out.append(Check("日志模式", OK if journal.lower() == "wal" else WARN,
                     journal, "" if journal.lower() == "wal" else "预期 WAL"))
    out.append(Check("账本计数", OK,
                     f"datasets {counts['datasets']} / files {counts['files']}"
                     f" / jobs {counts['jobs']}"))
    missing = [p for (p,) in rows if not Path(p).exists()]
    if missing:
        out.append(Check("文件抽查", WARN,
                         f"抽样 {len(rows)} 条中 {len(missing)} 条不在盘上"
                         f"（例：{Path(missing[0]).name}）",
                         "myastro audit 看全量报告（可能是清理过数据）"))
    else:
        out.append(Check("文件抽查", OK, f"抽样 {len(rows)} 条均在盘上"))
    out.append(Check("DB 连接可用", OK, ""))
    try:                                             # 真的能打开（含迁移路径）
        DB(cfg.db).init().close()
    except Exception as e:                           # noqa: BLE001
        out[-1] = Check("DB 连接可用", FAIL, f"{type(e).__name__}: {e}", "")
    return out


def _check_indexes() -> list[Check]:
    from . import index as idx

    out = []
    for name in idx.INDEXES:
        p = idx.index_path(name)
        if p.exists():
            out.append(Check(f"索引 {name}", OK,
                             f"{p.stat().st_size / 1e6:.1f} MB"))
        else:
            out.append(Check(f"索引 {name}", WARN, "未构建",
                             f"myastro index update {name}"))
    return out


def _check_platform() -> list[Check]:
    out = [Check("平台", OK, f"{platform.system()} {platform.release()} / "
                             f"Python {platform.python_version()}")]
    system = platform.system()
    if system == "Darwin":
        out.append(Check("定时任务", OK, "launchd 可用"))
    elif system == "Linux":
        import shutil
        tool = "systemctl --user" if shutil.which("systemctl") else (
            "crontab" if shutil.which("crontab") else None)
        out.append(Check("定时任务", OK if tool else WARN,
                         tool or "未发现 systemctl/crontab",
                         "" if tool else "定时任务不可用（其余功能不受影响）"))
    else:
        out.append(Check("定时任务", WARN, f"{system} 未支持",
                         "调度功能仅 macOS/Linux 可用"))
    try:
        from .core import source_root
        root = source_root()
        out.append(Check("源码仓库", OK, f"{root}（test-map/doc-sync 可用）"))
    except ValueError:
        out.append(Check("源码仓库", OK, "已安装包（开发向命令不可用，属正常）"))
    return out


def run(cfg=None, *, sample: int = 200) -> list[Check]:
    """跑全部检查。任何单项异常都会变成一条 FAIL，不向外抛。"""
    from ..io.config import Config

    cfg = cfg or Config()
    groups = []
    # 分组用**稳定标签**（而非函数名）：单项检查崩了也要能报出"是哪一组坏了"，
    # 且测试打桩后标签不变。
    plan = (("依赖", _check_deps, {}),
            ("路径", _check_paths, {"cfg": cfg}),
            ("账本", _check_ledger, {"cfg": cfg, "sample": sample}),
            ("索引", _check_indexes, {}),
            ("平台", _check_platform, {}))
    for label, fn, kwargs in plan:
        try:
            groups.append(fn(**kwargs))
        except Exception as e:                       # noqa: BLE001
            groups.append([Check(f"{label}检查", FAIL,
                                 f"{type(e).__name__}: {e}",
                                 "这是 myastro 的缺陷，请反馈该输出")])
    return [c for group in groups for c in group]


def summary(checks: list[Check]) -> dict:
    """计数摘要（CLI 与门面用）。"""
    return {s: sum(1 for c in checks if c.status == s) for s in (OK, WARN, FAIL)}


def dumps(checks: list[Check]) -> str:
    return json.dumps([c.as_dict() for c in checks], ensure_ascii=False, indent=2)
