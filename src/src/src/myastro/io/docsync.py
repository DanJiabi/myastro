"""文档同步：design-io.md §7.1 矩阵由注册表生成（文档是渲染产物）。

标记块：<!-- BEGIN sources-matrix --> ... <!-- END sources-matrix -->
命令：myastro doc-sync。测试守卫保证文档与生成器输出逐字一致。
"""
from __future__ import annotations

from pathlib import Path

from .sources import PLANNED_SOURCES, SOURCES, executor_display, status_display

BEGIN = "<!-- BEGIN sources-matrix -->"
END = "<!-- END sources-matrix -->"
# 相对路径在运行期挂到源码仓库根（见 core.source_root）。
# 此前这里是 `Path(__file__).resolve().parents[3]`——在已安装的 wheel 里
# parents[3] 落在 venv 的 lib 目录，会把文档**写进 site-packages**。
DOC = Path("docs/design-io.md")


def doc_path(path: Path | None = None) -> Path:
    """文档路径：绝对路径原样使用（测试重定向），相对路径挂到源码仓库根。"""
    target = path if path is not None else DOC
    if target.is_absolute():
        return target
    from .core import source_root
    return source_root() / target


def render_matrix() -> str:
    """SOURCES + PLANNED_SOURCES → markdown 表格（唯一渲染实现）。"""
    lines = [
        "| 数据源 | 说明 | 状态 | 执行器 | 通道 | 产物 | TUI 下单 |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, s in SOURCES.items():
        lines.append(
            f"| {name} | {s['desc']} | {status_display(s)} "
            f"| {executor_display(s)} | {s['via']} | {s['product']} "
            f"| {s['url_key'] or '—'} |")
    lines.append(f"| （规划未实现，{len(PLANNED_SOURCES)} 项） | | | | | | |")
    for name, desc in PLANNED_SOURCES.items():
        lines.append(f"| {name} | {desc} | 未实现 | — | — | — | — |")
    return "\n".join(lines)


def sync(doc: Path | None = None) -> bool:
    """重写文档标记块。返回是否发生变化。"""
    doc = doc_path(doc)
    text = doc.read_text()
    if BEGIN not in text or END not in text:
        raise RuntimeError(f"{doc} 缺少 {BEGIN}/{END} 标记块")
    head, rest = text.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    new = head + BEGIN + "\n" + render_matrix() + "\n" + END + tail
    if new == text:
        return False
    doc.write_text(new)
    return True
