"""数据源注册表（单一事实来源）——TUI info 面板与文档矩阵的渲染数据。

schema（构造时校验，违规即 ValueError）：
  status: STATUS 枚举键（封闭词汇表，显示文案由 status_display 派生）
  executor_type: "python" | "aria2"
  via: 通道/依赖（lightkurve、ibe HTTP…）
  product: 产物格式
  url_key: 可选，指向 io/urls.py URL_SOURCES（TUI 下单表单）
未实现的源不进本表（本表 = 已实现清单）；规划全集见 PLANNED_SOURCES。
历史数据注意：datasets.source 是存储事实（legacy-surveys/quick/index 等
历史值不做迁移），本表不与 DB 任何列 join。
"""
from __future__ import annotations

# ── 状态词汇表：全系统封闭枚举，显示文案唯一出处 ──
STATUS: dict[str, str] = {
    "ok": "✅ 可用",
    "degraded": "⚠ 服务故障",      # 我方实现完好，服务端问题
    "unreachable": "❌ 不可达",     # 网络层面不可达
}


def _entry(name: str, desc: str, status: str, executor_type: str,
           via: str, product: str, example: str,
           note: str = "", url_key: str | None = None) -> dict:
    if status not in STATUS:
        raise ValueError(f"{name}: status {status!r} 不在 STATUS 枚举")
    if executor_type not in ("python", "aria2"):
        raise ValueError(f"{name}: executor_type 须为 python|aria2")
    return {"name": name, "desc": desc, "status": status,
            "executor_type": executor_type, "via": via, "product": product,
            "example": example, "note": note, "url_key": url_key}


def status_display(entry: dict) -> str:
    return STATUS[entry["status"]]


def executor_display(entry: dict) -> str:
    return f"{entry['executor_type']} · {entry['via']}"


SOURCES: dict[str, dict] = {e["name"]: e for e in [
    _entry("tess", "TESS/Kepler/K2 光变曲线 → parquet", "ok",
           "python", "lightkurve", "parquet",
           'from myastro.io.sources.tess import tess_lightcurve\n'
           'r = tess_lightcurve("WASP-12", sector=20, cadence="2m")',
           note="缓存重定向到 MAD/cache/lightkurve；截断文件自动清理重试"),
    _entry("exoplanet", "NASA Exoplanet Archive 凌星参数直查", "ok",
           "python", "astroquery.nexsci", "dict",
           'from myastro.io.sources.exoplanet import exoplanet_params\n'
           'p = exoplanet_params("WASP-12 b")',
           note="量级 KB，不建 job；ps 表多解取周期非空的默认解"),
    _entry("gaia", "Gaia DR3 锥形星表切片 → parquet", "ok",
           "python", "astroquery.gaia (ADQL)", "parquet",
           'from myastro.io.sources.gaia import gaia_cone\n'
           'r = gaia_cone(286.6583, 0.8656, radius_deg=0.02)',
           note="DR4 前 archive 偶不稳，重试兜底；大锥建议拆小"),
    _entry("asassn", "ASAS-SN Sky Patrol v2 变星光变", "unreachable",
           "python", "pyasassn", "parquet",
           'from myastro.io.sources.asassn import asassn_lightcurve\n'
           'r = asassn_lightcurve(339.27, 58.42, radius_arcmin=1.0)',
           note="2026-10: 后端 asassn-lb01.ifa.hawaii.edu DNS NXDOMAIN，"
                "服务迁移中。决策(2026-10-09)：实现+测试保留为休眠代码，"
                "恢复日跑一次真实验证；若届时确认弃用，实现/测试/SOURCES "
                "条目一并删除"),
    _entry("ztf-meta", "ZTF sci 帧元数据（视宁度/历元）→ parquet", "ok",
           "python", "ibe HTTP", "parquet",
           'from myastro.io.sources.ztf import ztf_metadata\n'
           'r = ztf_metadata(673, "zg", 1, 1, jd_min=2458700, jd_max=2458900)',
           note="ztfquery 1.28 强制 IRSA token，此处匿名 ibe；偶发 504 重试兜底"),
    _entry("ztf", "ZTF sci 图像单帧/多帧栈下载", "ok",
           "aria2", "ibe HTTP", "fits",
           'from myastro.io.sources.ztf import ztf_frame, ztf_stack\n'
           'r = ztf_frame("20200219403889", 673, "zg", 1, 1)',
           note="实测 ~84 KB/s，单帧 38MB ≈ 8 分钟；批量排夜间；"
                "部分 fracday 元数据有但文件 404，选帧前先 HEAD",
           url_key="ztf"),
    _entry("legacy", "Legacy Surveys DR10 tractor 星表（brick 切片）", "ok",
           "aria2", "NERSC HTTP", "fits",
           '# legacy 走 TUI（n → 选源）或 manifest',
           note="36.7 万 brick 索引已本地化，TUI 表单前缀候选 + Tab 补全；"
                "实测 3–29 MB/s", url_key="legacy"),
    _entry("unwise", "unWISE 中红外叠加切片", "ok",
           "python", "unwise.me cutout（requests + tarfile）", "fits（含辅助）",
           'from myastro.io.sources.unwise import unwise_cutout\n'
           'r = unwise_cutout(180.0, 1.1, size=300, band="w1")',
           note="2026-10-09 澄清：bands 需整数位掩码（1=w1/2=w2，传名字会 500）、"
                "响应是 tar.gz 需解包、不支持 w1+w2 合并（返回 0 字节）"),
    _entry("manifest", "任意 URL 批量下载（manifest 提交）", "ok",
           "aria2", "yaml 清单", "任意",
           'from myastro.io.manifest import submit_manifest\n'
           'ids = submit_manifest("manifests/legacy-dr10.yaml")',
           note="files 为 URL 列表；dest_dir 相对 data root"),
    _entry("mpc", "MPC 小行星/彗星星历（Horizons 替代）", "ok",
           "python", "astroquery.mpc", "parquet",
           "from myastro.io.sources.mpc import mpc_ephemeris\n"
           'r = mpc_ephemeris("Ceres", number=10)',
           note="实测可达；step 天/步"),
    _entry("simbad", "SIMBAD 锥搜：天区目标认证", "ok",
           "python", "astroquery.simbad", "parquet",
           "from myastro.io.sources.simbad import simbad_cone\n"
           'r = simbad_cone(180.0, 0.0, radius_deg=0.1)',
           note="空结果返回 empty 标记"),
    _entry("vizier", "VizieR 任意发表星表锥检", "ok",
           "python", "astroquery.vizier", "parquet",
           "from myastro.io.sources.vizier import vizier_cone\n"
           'r = vizier_cone("II/246", 180.0, 0.0)',
           note="catalog 形如 II/246（2MASS）；需指定星表号"),
    _entry("ztf-lc", "ZTF 光变曲线（匿名可用）", "ok",
           "python", "ztfquery.lightcurve", "parquet",
           "from myastro.io.sources.ztf_lc import ztf_lightcurve\n"
           'r = ztf_lightcurve(97.14, 30.49, radius_arcsec=5)',
           note="直连 IRSA 原生 API（公开数据无需凭据；ztfquery 1.28 包装层"
                "对当前服务端静默返回空，已绕开）；实测 8as 锥 8 源×3729 点"
                "/51s；响应量随半径平方增长，单源建议 5–10as、大锥排夜间"),
    _entry("horizons", "JPL Horizons 星历", "unreachable",
           "python", "—", "—",
           "# 本网络 ssd.jpl.nasa.gov 连接超时",
           note="替代：astroquery.mpc（MPC 星历）+ skyfield 本地历表（离线）"),
]}

# ── 规划全集（未实现）：仅名字 + 一句话；实现后迁移进 SOURCES ──
PLANNED_SOURCES: dict[str, str] = {
    "panstarrs": "Pan-STARRS DR2 stack cutout（MAST URL）",
    "sdss": "SDSS DR18 光谱/测光（astroquery.sdss）",
    "skyfield": "DE440s 历表本地化（一次性下载）",
}
