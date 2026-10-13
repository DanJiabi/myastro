"""本地数据文件的快速预览（CLI `preview` 与 TUI `p` 键共用）。

设计：
- 输出**结构化**的 `PreviewDoc`（段落 + 可选表格），由 CLI/TUI 各自渲染——
  避免内核直接拼终端字符串两头迁就；
- 格式**嗅探**而非只看扩展名：parquet 魔数 `PAR1`；FITS 魔数 `SIMPLE`
  （gzip 包裹的如 `legacy-bricks.src` 先解一层再嗅）；其余按可打印文本处理；
- 大文件不全读：parquet 行数走元数据，预览/统计只读前两个 row group。
"""
from __future__ import annotations

import gzip
from dataclasses import dataclass, field
from pathlib import Path

# 预览行数/列数上限：终端可读性优先
MAX_HEAD_ROWS = 8
MAX_COLS = 12
BIG_FILE = 200 * 1024 * 1024          # 超过就只读前两个 row group 做统计


@dataclass
class Section:
    title: str
    lines: list[str] = field(default_factory=list)
    table: tuple[list[str], list[list[str]]] | None = None   # (列名, 行)


@dataclass
class PreviewDoc:
    path: str
    kind: str                          # parquet | fits-image | fits-table | text | unknown
    size: int
    sections: list[Section] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"path": self.path, "kind": self.kind, "size": self.size,
                "sections": [{"title": s.title, "lines": s.lines,
                              "table": s.table} for s in self.sections]}


def sniff(path: Path) -> str:
    """按内容嗅探格式（parquet / fits / text / unknown）。"""
    try:
        with open(path, "rb") as f:
            head = f.read(290)          # FITS 魔数在第 1 个 80 字节卡片开头
    except OSError:
        return "unknown"
    if head[:4] == b"PAR1":
        return "parquet"
    if head[:2] == b"\x1f\x8b":                     # gzip：解一层再嗅
        try:
            with gzip.open(path, "rb") as f:
                inner = f.read(290)
            if inner[:6] == b"SIMPLE":
                return "fits"
        except OSError:
            return "unknown"
    if head[:6] == b"SIMPLE":
        return "fits"
    if head and all(b in b"\t\n\r" or 32 <= b < 127 or b >= 128 for b in head):
        return "text"
    return "unknown"


def _parquet(path: Path, doc: PreviewDoc) -> None:
    import pyarrow.parquet as pq

    pf = pq.ParquetFile(path)
    meta = pf.metadata
    schema = meta.schema
    doc.sections.append(Section("概要", [
        f"行数：{meta.num_rows}｜列数：{len(schema.names)}｜row groups：{meta.num_row_groups}",
    ]))
    arrow = pf.schema_arrow
    cols = [f"{schema.names[i]}: {arrow.field(i).type}" for i in
            range(min(len(schema.names), MAX_COLS))]
    if len(schema.names) > MAX_COLS:
        cols.append(f"… 共 {len(schema.names)} 列")
    doc.sections.append(Section("schema", cols))

    groups = min(2, meta.num_row_groups) if doc.size > BIG_FILE else meta.num_row_groups
    table = pf.read_row_groups(list(range(groups)))
    df = table.to_pandas()
    if groups < meta.num_row_groups:
        doc.sections.append(Section(
            "采样说明", [f"文件较大（{doc.size/1e6:.0f} MB），统计与前 N 行基于前 {groups} 个 row group"]))
    if len(df):
        head = df.head(MAX_HEAD_ROWS)
        use = list(head.columns[:MAX_COLS])
        rows = [[str(v)[:24] for v in row] for row in head[use].itertuples(index=False)]
        doc.sections.append(Section(f"前 {len(head)} 行", table=(use, rows)))
        nan = (df.isna().mean().sort_values(ascending=False) * 100).round(1)
        nan = nan[nan > 0]
        if len(nan):
            doc.sections.append(Section(
                "NaN 占比（前 5）", [f"{c}: {v}%" for c, v in nan.head(5).items()]))


def _fits(path: Path, doc: PreviewDoc) -> None:
    from astropy.io import fits

    with fits.open(path, memmap=True) as hdul:
        h0 = hdul[0].header
        lines = [f"HDU 数：{len(hdul)}"]
        if hdul[0].data is not None and hasattr(hdul[0].data, "shape"):
            lines.append(f"形状：{hdul[0].data.shape}")
        for key in ("TELESCOP", "INSTRUME", "FILTER", "EXPTIME", "OBSJD",
                    "DATE-OBS", "CRVAL1", "CRVAL2", "CDELT1", "CDELT2",
                    "OBJECT", "SEEING"):
            if key in h0:
                lines.append(f"{key} = {h0[key]}")
        doc.sections.append(Section("头部", lines))
        for i, hdu in enumerate(hdul):
            if getattr(hdu, "columns", None) is not None and hdu.data is not None:
                names = list(hdu.columns.names)
                shown = names[:MAX_COLS]
                if len(names) > MAX_COLS:
                    shown.append(f"… 共 {len(names)} 列")
                doc.sections.append(Section(f"表 HDU{i}（{len(hdu.data)} 行）", shown))
                head = hdu.data[:MAX_HEAD_ROWS]
                rows = [[str(row[c])[:24] for c in names[:MAX_COLS]] for row in head]
                doc.sections.append(
                    Section(f"前 {len(head)} 行", table=(names[:MAX_COLS], rows)))
                break
            if hdu.data is not None and i == 0 and getattr(hdu.data, "ndim", 0) >= 2:
                import numpy as np
                data = hdu.data
                sample = data[:: max(1, data.shape[0] // 64),
                              :: max(1, data.shape[1] // 64)]
                p = np.nanpercentile(sample, [1, 50, 99])
                doc.sections.append(Section(
                    "图像统计（抽稀）",
                    [f"p1={p[0]:.1f}｜中位={p[1]:.1f}｜p99={p[2]:.1f}"]))
                doc.kind = "fits-image"
                return
        if doc.kind == "fits" and len(hdul) > 1:
            doc.kind = "fits-table"


def preview(path: str | Path, lines: int = MAX_HEAD_ROWS) -> PreviewDoc:
    """预览一个本地文件：嗅探格式 → 结构化预览文档。"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"文件不存在：{p}")
    kind = sniff(p)
    doc = PreviewDoc(path=str(p), kind=kind, size=p.stat().st_size)
    if kind == "parquet":
        _parquet(p, doc)
    elif kind == "fits":
        _fits(p, doc)
    elif kind == "text":
        text = p.read_text(errors="replace").splitlines()[:lines]
        doc.sections.append(Section(f"前 {len(text)} 行", text))
    else:
        doc.sections.append(Section("提示", ["未知格式：不是 parquet/FITS/可读文本"]))
    return doc


def render_text(doc: PreviewDoc) -> str:
    """把 PreviewDoc 渲染成纯文本（CLI 打印 / TUI 详情面板共用）。"""
    # 用【】而不是 []——Rich/TUI 会把 [xxx] 当 markup 标签吞掉（TUI 测试抓到的）
    out = [f"【{doc.kind}】{doc.path}（{doc.size/1024:.0f} KB）"]
    for s in doc.sections:
        out.append(f"── {s.title} ──")
        out.extend(f"  {line}" for line in s.lines)
        if s.table:
            cols, rows = s.table
            widths = [max(len(c), *(len(r[i]) for r in rows)) if rows else len(c)
                      for i, c in enumerate(cols)]
            out.append("  " + "  ".join(c.ljust(w) for c, w in zip(cols, widths)))
            for r in rows:
                out.append("  " + "  ".join(v.ljust(w) for v, w in zip(r, widths)))
    return "\n".join(out)
