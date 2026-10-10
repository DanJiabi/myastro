"""数据类型注册表（单一事实来源）——top 的 data 面板与详情读它渲染。

files.format 存后缀（注册时取 p.suffix），TYPES 按后缀给出统一的人类描述
与读取方式。新增产物类型：在此登记一行。
"""

TYPES: dict[str, dict] = {
    "parquet": {
        "label": "Parquet 表格",
        "desc": "列式表格（时间序列/星表）。astropy Table 与 pandas 双读，"
                "小体积快加载，是 myastro 时序与星表产物的标准格式",
        "load": "pd.read_parquet(path)  # 或 Table.read(path)",
    },
    "fits": {
        "label": "FITS 天文图像/表",
        "desc": "天文标准格式。ZTF/Legacy 的 sci 图像（HDU0 数据阵 + WCS 头）、"
                "TESS 原始光变均为此类；后续自有设备数据同格式",
        "load": 'fits.open(path)[0].data   # 图像\n'
                'Table.read(path)          # 表',
    },
    "fz": {
        "label": "FITS 压缩包",
        "desc": "fpack 压缩的 FITS（.fits.fz），astropy 透明解压",
        "load": "fits.open(path)  # memmap=True 省内存",
    },
    "csv": {
        "label": "CSV 文本表",
        "desc": "ASAS-SN 等服务的原始导出格式，轻量通用",
        "load": "pd.read_csv(path)",
    },
    "bsp": {
        "label": "星历文件",
        "desc": "skyfield 历表（DE440s 等），本地星历计算用，一次性下载长期缓存",
        "load": "load('de440s.bsp')  # skyfield.api",
    },
}


def type_info(fmt: str | None) -> dict:
    """后缀 → 类型信息；未登记的类型给出兜底描述。"""
    fmt = (fmt or "").lower().lstrip(".")
    if fmt in TYPES:
        return TYPES[fmt]
    return {"label": fmt or "未知", "desc": "（未登记类型，可在 "
            "io/types.py TYPES 注册）", "load": ""}
