"""文档路径守卫：开发文档里引用的代码/测试路径必须真实存在。

为什么需要：文档比代码更容易腐化——重命名模块后，文档会继续指向
已经不存在的文件，读的人以为那里有实现。这里把"文档里的路径"
变成可机检的事实。

覆盖：docs/*.md 中出现的 `src/myastro/...py`、`tests/...py`、
`githooks/...`、`docs/...md` 路径（反引号包裹或纯文本均可）。
"""
from __future__ import annotations

import pathlib
import re

import pytest

DOCS = pathlib.Path("docs")
ROOT = pathlib.Path(".")

# 形如 src/myastro/io/search.py / tests/kernel/test_db.py / docs/zh/dev/testing.md
PATH_RE = re.compile(
    r"(?:src/myastro|tests|docs|githooks)/[A-Za-z0-9_./*-]+?\.(?:py|md|sh)")
# 允许通配（`tests/sources/test_*.py`）与目录占位，逐个展开检查
PLAIN_RE = re.compile(r"githooks/[A-Za-z0-9_.-]+")


def _documented_paths() -> list[tuple[str, str]]:
    out = []
    for doc in sorted(DOCS.rglob("*.md")):   # 开发文档已移入 docs/zh/dev/
        for m in PATH_RE.finditer(doc.read_text()):
            out.append((doc.name, m.group(0)))
        for m in PLAIN_RE.finditer(doc.read_text()):
            out.append((doc.name, m.group(0)))
    return out


@pytest.mark.cap("design.guards")
def test_documented_paths_exist():
    missing = []
    for doc, path in _documented_paths():
        if "*" in path:                      # 通配：至少要有一个匹配
            if not list(ROOT.glob(path)):
                missing.append(f"{doc}: {path}（通配无匹配）")
        elif not (ROOT / path).exists():
            missing.append(f"{doc}: {path}")
    assert not missing, "文档引用了不存在的路径：\n" + "\n".join(missing)


@pytest.mark.cap("design.guards")
def test_processing_doc_is_linked_from_readme_and_io_design():
    """处理逻辑文档必须从 README 与 io 设计文档可达（否则等于没写）。"""
    readme = pathlib.Path("README.md").read_text()
    io_design = (DOCS / "zh" / "dev" / "design-io.md").read_text()
    assert "docs/zh/dev/processing.md" in readme, "README 未链接 processing.md"
    assert "processing.md" in io_design, "design-io 未链接 processing.md"


@pytest.mark.cap("design.guards")
def test_processing_doc_covers_core_modules():
    """处理逻辑文档的"代码位置速查"必须覆盖 io 层核心处理模块。"""
    text = (DOCS / "zh" / "dev" / "processing.md").read_text()
    core = ["descriptors.py", "io/jobs/", "io/db.py", "io/coords.py",
            "io/index.py", "io/search.py", "io/integrity.py", "io/health.py",
            "io/schedule.py", "facade.py"]
    missing = [m for m in core if m not in text]
    assert not missing, f"processing.md 未覆盖核心模块：{missing}"


@pytest.mark.cap("design.guards")
def test_bilingual_user_docs_are_paired():
    """用户向文档必须中英成对，且章节结构一致（防止只更新一边）。

    约定（docs/zh/dev/release.md §6）：`docs/en/<name>.md` 与 `docs/zh/<name>.md`
    同名成对；章节层级序列必须相同，否则说明有人只改了一边。
    """
    import re

    def rel(tree: str) -> set[pathlib.Path]:
        return {p.relative_to(DOCS / tree) for p in (DOCS / tree).rglob("*.md")}

    en, zh = rel("en"), rel("zh")
    assert en, "docs/en 下没有用户向文档"
    # 规则：**英文页必须在中文里有同名对应**（英文是给外部读者的，不能留孤儿页）；
    # 反过来允许——中文侧多出只面向开发者的文档（docs/zh/dev/**）。
    orphan = sorted(en - zh)
    assert not orphan, f"英文文档缺少中文对应：{[str(p) for p in orphan]}"

    def levels(path):
        return [len(m.group(1)) for m in
                re.finditer(r"(?m)^(#{1,6})\s", path.read_text())]

    mismatch = [(str(p), levels(DOCS / "en" / p), levels(DOCS / "zh" / p))
                for p in sorted(en & zh)
                if levels(DOCS / "en" / p) != levels(DOCS / "zh" / p)]
    assert not mismatch, f"中文章节结构与英文不一致：{mismatch}"


@pytest.mark.cap("design.guards")
def test_readme_pair_exists():
    """中英 README 成对存在（PyPI 长描述用英文那份）。"""
    root = pathlib.Path(".")
    assert (root / "README.md").is_file()
    assert (root / "README.zh-CN.md").is_file()
    en, zh = (root / "README.md").read_text(), (root / "README.zh-CN.md").read_text()
    assert "README.zh-CN.md" in en, "英文 README 应指向中文版"
    assert "README.md" in zh, "中文 README 应指向英文版"
