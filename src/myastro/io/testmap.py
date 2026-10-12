"""测试能力地图：能力 → 证明它的测试（生成 docs/zh/dev/test-map.md）。

用途：把"能力声明"与"证据"机器化绑定——
capabilities.md 声明能力处于 L?，test-map.md 列出证明它的测试，
守卫测试保证两边不漂移（手改文档即红）。

能力 id 是唯一事实来源：本模块 CAPABILITIES。
测试侧用 @pytest.mark.cap("<id>") 声明（pytest --strict-markers 保证拼错即红）。
"""
from __future__ import annotations

import ast
from pathlib import Path

# 相对路径在**运行期**挂到源码仓库根（见 core.source_root）；绝对路径原样使用
# （测试用 monkeypatch 指到临时路径）。
DOC = Path("docs/zh/dev/test-map.md")
TESTS_DIR = Path("tests")
CAP_FILE = Path("docs/zh/dev/capabilities.md")


def _resolve(path: Path) -> Path:
    if path.is_absolute():
        return path
    from .core import source_root
    return source_root() / path

# ── 能力注册表（id → 中文说明）──
CAPABILITIES: dict[str, str] = {
    "source.registry": "源注册表与描述符：接入声明、示例参数、漂移守卫",
    "source.contract": "单源实现契约：参数校验、落盘、入库、空结果",
    "source.health": "源健康探测与状态覆盖（ok/degraded/unreachable）",
    "source.dormant": "休眠源防腐烂（asassn：后端失联期间保持正确）",
    "acquire.fetch": "单件获取：缓存短路、原子落盘、入库、aria2 对账",
    "acquire.query": "计划型查询：解析出 URL/文件名但不提交",
    "acquire.batch": "批量下单与批次资格（构不出 spec 的源不得入选）",
    "acquire.retry": "重试：僵尸判定、跨进程重提、task 推断、强制重下",
    "acquire.cancel": "取消与作业记录删除（资产保留）",
    "acquire.manifest": "清单（YAML）批量获取",
    "acquire.schedule": "定时任务（launchd 代理的生成与装卸）",
    "manage.ledger": "账本：schema/迁移、缓存身份、meta 溯源、原子写",
    "manage.integrity": "完整性巡检：sha 基线、损坏与缺失检测",
    "manage.search": "本地检索（目标/坐标/时间）",
    "manage.coverage": "索引覆盖率统计",
    "manage.index": "索引构建与浏览（builder/url 两类来源）",
    "process.lc": "时序处理工具：归一化、折叠、周期搜索、凌星搜索",
    "present.tui": "TUI 行为：面板、键位、身份寻址、格式化",
    "present.cli": "CLI 行为：子命令参数接线、输出与退出码",
    "ci.config": "CI 工作流配置（可解析性/结构）",
    "manage.doctor": "环境自检：依赖/路径可写/账本/文件系统/索引/平台",
    "manage.backup": "账本备份与恢复：在线备份、默认拒绝覆盖、安全副本",
    "facade.api": "门面契约：错误分类、参数校验、执行器隐身",
    "design.contract": "契约快照（门面 API/CLI/退出码/schema/注册表）",
    "design.guards": "设计守卫：文档同步、边界规则、能力覆盖",
}


def collect(root: Path | None = None) -> dict[str, list[str]]:
    """扫描测试源码：cap id → ["相对路径::类::测试名", ...]（按路径排序）。"""
    root = _resolve(root or TESTS_DIR)
    out: dict[str, list[str]] = {}
    for f in sorted(root.rglob("test_*.py")):
        text = f.read_text()
        rel = str(f.relative_to(root.parent))
        tree = ast.parse(text)
        for node in tree.body:
            classes = ([node] if isinstance(node, ast.ClassDef) else [None])
            for cls in classes:
                cls_caps = ([c for c in (_cap_of(d)
                                         for d in cls.decorator_list) if c]
                            if cls else [])
                members = (cls.body if cls else tree.body)
                for m in members:
                    if not isinstance(m, (ast.FunctionDef,
                                          ast.AsyncFunctionDef)):
                        continue
                    caps = [c for c in (_cap_of(d)
                                        for d in m.decorator_list) if c]
                    caps = caps or cls_caps          # 类级标记对成员生效
                    for cap in caps:
                        prefix = f"{cls.name}::" if cls else ""
                        out.setdefault(cap, []).append(
                            f"{rel}::{prefix}{m.name}")
    return {k: sorted(v) for k, v in sorted(out.items())}


def _cap_of(dec: ast.AST) -> str | None:
    """从装饰器 @pytest.mark.cap("x") 提取 x。"""
    if not isinstance(dec, ast.Call):
        return None
    fn = dec.func
    if not (isinstance(fn, ast.Attribute) and fn.attr == "cap"):
        return None
    if dec.args and isinstance(dec.args[0], ast.Constant):
        return str(dec.args[0].value)
    return None


def _class_of(text: str, target: ast.AST) -> str:
    """目标测试所属类名（模块级返回空串）。"""
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.ClassDef):
            for m in node.body:
                if m is target:
                    return f"{node.name}::"
    return ""


def all_markers(root: Path | None = None) -> dict[str, int]:
    """每个测试的 cap 标记数（用于"恰好一个"守卫）。"""
    root = _resolve(root or TESTS_DIR)
    counts: dict[str, int] = {}
    for f in sorted(root.rglob("test_*.py")):
        text = f.read_text()
        tree = ast.parse(text)
        for node in tree.body:
            cls = node if isinstance(node, ast.ClassDef) else None
            cls_caps = sum(1 for d in cls.decorator_list
                           if _cap_of(d) is not None) if cls else 0
            for m in (cls.body if cls else tree.body):
                if not isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                        or not m.name.startswith("test"):
                    continue
                own = sum(1 for d in m.decorator_list
                          if _cap_of(d) is not None)
                # 类级与函数级同时存在视为重复声明（0/2 都会被守卫拦下）
                n = own if own else cls_caps
                counts[f"{f.relative_to(root.parent)}::{m.name}"] = n
    return counts


def problems(root: Path | None = None) -> list[str]:
    """自检：未注册 id、重复标记、有 id 无测试、文档未同步。"""
    root = _resolve(root or TESTS_DIR)
    cap_file, doc = _resolve(CAP_FILE), _resolve(DOC)
    issues: list[str] = []
    mapping = collect(root)
    for cap in mapping:
        if cap not in CAPABILITIES:
            issues.append(f"未注册的能力 id: {cap}")
    for name, n in all_markers(root).items():
        if n != 1:
            issues.append(f"{name} 的 cap 标记数为 {n}（应为 1）")
    for cap in CAPABILITIES:
        if cap not in mapping:
            issues.append(f"能力 {cap} 没有任何测试")
    for cap in CAPABILITIES:
        if f"cap:{cap}" not in cap_file.read_text():
            issues.append(f"capabilities.md 未标注 {cap}")
    if not doc.exists():
        issues.append(f"{doc} 不存在（跑 myastro test-map 生成）")
    elif render(root) != doc.read_text():
        issues.append(f"{doc} 与生成器不一致（跑 myastro test-map 同步）")
    return issues


def render(root: Path | None = None) -> str:
    root = _resolve(root or TESTS_DIR)
    mapping = collect(root)
    lines = [
        "# 测试能力地图（生成文件，勿手改）",
        "",
        "生成：`myastro test-map`。守卫：`tests/guards/test_capability_map.py`"
        + "；手改本文件或漏挂标记都会让测试变红。",
        "",
        "能力 id 定义在 `src/myastro/io/testmap.py`；"
        + "能力说明与成熟度见 [capabilities.md](capabilities.md)。",
        "",
        f"共 {len(mapping)} 项能力、{sum(len(v) for v in mapping.values())} 个测试。",
        "",
        "| 能力 | 说明 | 测试数 |",
        "|---|---|---|",
    ]
    for cap, desc in CAPABILITIES.items():
        lines.append(f"| `{cap}` | {desc} | {len(mapping.get(cap, []))} |")
    lines += ["", "## 能力 → 测试明细", ""]
    for cap, desc in CAPABILITIES.items():
        lines.append(f"### `{cap}` — {desc}")
        lines.append("")
        for t in mapping.get(cap, []):
            lines.append(f"- `{t}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def sync(root: Path | None = None, path: Path | None = None) -> Path:
    """生成能力地图。path 缺省取模块级 DOC（运行期解析，便于测试重定向）。"""
    root = _resolve(root or TESTS_DIR)
    target = path if path is not None else _resolve(DOC)
    target.write_text(render(root))
    return target
