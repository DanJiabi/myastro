"""URL 生成器注册表——top 新建下载表单与 Python API 共用的单一事实来源。

每个条目声明：参数字段、URL/文件名/目录的派生函数。
TUI 据此渲染动态表单（不写任何 per-source UI 代码）；
加新源 = 登记一条 + 三个纯函数。
"""
from __future__ import annotations

from .sources.ztf import frame_name as _ztf_name
from .sources.ztf import ztf_sci_url as _ztf_url


def legacy_tractor_url(brick: str) -> str:
    return ("https://portal.nersc.gov/cfs/cosmo/data/legacysurvey/dr10/"
            f"south/tractor/{brick[:3]}/tractor-{brick}.fits")


URL_SOURCES: dict[str, dict] = {
    "ztf": {
        "label": "ZTF sci 帧",
        "fields": [
            ("field", "field 号，如 673", "673"),
            ("filtercode", "zg / zr / zi", "zg"),
            ("ccdid", "CCD 1–16", "1"),
            ("qid", "象限 1–4", "1"),
            ("ffd", "filefracday 14 位，如 20200219403889", ""),
        ],
        "build_url": lambda p: _ztf_url(
            p["ffd"], int(p["field"]), p["filtercode"],
            int(p["ccdid"]), int(p["qid"])),
        "build_name": lambda p: _ztf_name(
            p["ffd"], int(p["field"]), p["filtercode"],
            int(p["ccdid"]), int(p["qid"])),
        "dest_dir": lambda p: f"ztf/f{int(p['field']):06d}",
    },
    "legacy": {
        "label": "Legacy Surveys tractor",
        "fields": [
            # 第 4 元素 = 本地索引名（io/index.py）：前缀候选 + Tab 补全
            ("brick", "brick 名（索引 legacy-bricks：输入即补全，→ 接受）",
             "0001m002", "legacy-bricks"),
        ],
        "build_url": lambda p: legacy_tractor_url(p["brick"]),
        "build_name": lambda p: f"tractor-{p['brick']}.fits",
        "dest_dir": lambda p: "legacy",
    },
}
