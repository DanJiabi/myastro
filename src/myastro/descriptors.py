"""源描述符：内核契约（Roadmap E0）。

一份 fields 声明派生：TUI 动态表单、CLI 参数生成、参数校验、
跨进程持久化（name+params 即 JSON）。执行器（python/aria2）是
描述符的实现细节，对调用方不可见。

E0 采用"包装现有注册表"策略：SOURCES/URL_SOURCES/TASKS 保持原位，
本模块将其升格为统一描述符视图；源实现的重写留待逐源迁移。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .io.config import Config
from .io.jobs import JobSpec
from .io.sources import SOURCES
from .io.urls import URL_SOURCES


@dataclass
class FieldSpec:
    name: str
    type: type = str
    default: Any = None
    label: str = ""
    choices: tuple[str, ...] | None = None      # 有限取值（TUI 下拉/枚举校验）
    index: str | None = None                    # 本地索引名（候选/补全）
    optional: bool = False                      # 允许缺省（空 → None）
    pattern: str | None = None                  # 正则全匹配（严格格式，如 brick）
    name_like: bool = False                     # 会进文件名/目录名 → 走 safe_name

    def coerce(self, value: Any) -> Any:
        """类型收敛（字符串→目标类型），失败抛 ValueError。"""
        if value is None:
            if self.optional:
                return None
            if self.default is None:
                raise ValueError(f"缺少必填参数 {self.name!r}")
            return self.default
        if self.type is str:
            value = str(value)
        else:
            value = self.type(value)            # int/float
        if self.choices is not None and str(value) not in self.choices:
            raise ValueError(f"{self.name!r} 须为 {self.choices} 之一")
        if self.pattern is not None:
            import re
            if not re.fullmatch(self.pattern, str(value)):
                raise ValueError(
                    f"{self.name!r} 格式不符（需匹配 {self.pattern}）：{value!r}")
        if self.name_like:
            # 会被拼进文件名/目录名 → 统一在这里挡住路径穿越
            from .io.core import safe_name
            safe_name(str(value), field=self.name)
        return value


@dataclass
class SourceDescriptor:
    name: str
    desc: str
    product: str
    status: str                                  # SOURCES STATUS 枚举键
    fields: list[FieldSpec] = field(default_factory=list)
    task: str | None = None                      # python 执行器：TASKS 键
    url_key: str | None = None                   # aria2 执行器：URL_SOURCES 键
    example_params: dict = field(default_factory=dict)   # 完整合法参数示例

    def validate(self, params: dict) -> dict:
        """参数校验/补默认：返回规范化 params；未知键/类型错抛 ValueError。"""
        known = {f.name for f in self.fields}
        unknown = set(params) - known
        if unknown:
            raise ValueError(f"未知参数 {sorted(unknown)}"
                             f"（可用: {sorted(known)}）")
        return {f.name: f.coerce(params.get(f.name)) for f in self.fields}

    def build_spec(self, params: dict) -> JobSpec:
        p = self.validate(params)
        if self.task:
            return JobSpec(source=self.name, executor="python",
                           params=p, task=self.task)
        if self.url_key:
            u = URL_SOURCES[self.url_key]
            url = u["build_url"](p)
            name = u["build_name"](p)
            dest = Config().data / u["dest_dir"](p) / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            return JobSpec(source=self.name, executor="aria2", params=p,
                           url=url, dest=str(dest))
        raise ValueError(f"{self.name}: 无 task/url_key，不可构建作业")


@dataclass
class Prefill:
    """表单预填充结果（`prefill_from_spec` 的返回值）。

    mode:
      "descriptor" —— 命中注册源：source + params 可直接填进描述符表单
      "custom"     —— 未命中注册源但是自定义 URL 作业：填 url/name/mission
      "none"       —— 无法预填充，调用方退回空白表单（reason 说明原因）
    """

    mode: str
    source: str | None = None
    params: dict = field(default_factory=dict)
    custom: dict = field(default_factory=dict)   # {"url","name","mission"}
    reason: str = ""

    def __bool__(self) -> bool:
        return self.mode != "none"


def prefill_from_spec(stored: dict) -> Prefill:
    """`build_spec` 的逆映射：把已存 spec 还原成表单可填的值。

    设计意图：预填充逻辑属于**描述符契约**（源 ↔ 参数 ↔ 表单），
    不属于任何界面；TUI/CLI/第三方都通过它拿到同一份结果。

    规则：
    - 源在 REGISTRY 且有字段声明 → descriptor；params 只取已声明字段，
      未声明的计入 reason（改了描述符的老作业不会把表单搞乱）
    - 未命中注册源、但有 url（自定义下载）→ custom
    - 其余 → none（如已下线的源、无参数的内部作业）
    """
    source = stored.get("source")
    params = stored.get("params") or {}
    d = REGISTRY.get(source)

    if d is not None and d.fields:
        known = {f.name for f in d.fields}
        kept = {k: v for k, v in params.items() if k in known}
        dropped = sorted(set(params) - known)
        notes = []
        if dropped:
            notes.append(f"忽略 {len(dropped)} 个描述符未声明的参数"
                         f"（{'、'.join(dropped)}）")
        missing = [f.name for f in d.fields
                   if f.name not in kept and f.default is None
                   and not f.optional]
        if missing:
            notes.append(f"需补填：{', '.join(missing)}")
        if not kept:
            notes.append("参数与当前描述符无交集")
        return Prefill(mode="descriptor", source=source, params=kept,
                       reason="；".join(notes))

    url = stored.get("url")
    if url:
        dest = str(stored.get("dest") or "")
        name = Path(dest).name or Path(url).name
        mission = Path(dest).parent.name if dest else ""
        mission = "" if mission in ("", ".", "/") else mission
        return Prefill(mode="custom",
                       custom={"url": str(url), "name": name,
                               "mission": mission},
                       reason="未命中注册源，按自定义 URL 载入")

    why = (f"源 {source!r} 不在注册表" if source not in REGISTRY
           else f"源 {source!r} 无可填字段")
    return Prefill(mode="none", reason=why)


def _d(name: str, fields_: list[FieldSpec], task: str | None = None,
       url_key: str | None = None, **kw) -> SourceDescriptor:
    s = SOURCES[name]
    return SourceDescriptor(name=name, desc=s["desc"], product=s["product"],
                            status=s["status"], fields=fields_, task=task,
                            url_key=url_key or s.get("url_key"), **kw)


REGISTRY: dict[str, SourceDescriptor] = {d.name: d for d in [
    _d("tess", [
        FieldSpec("target", str, label="目标名", name_like=True),
        FieldSpec("sector", int, default=None, optional=True,
                  label="扇区（空=最新）"),
        FieldSpec("cadence", str, default="2m",
                  choices=("2m", "20s", "10m", "30m")),
    ], task="tess_lightcurve",
       example_params={"target": "WASP-12", "sector": 20, "cadence": "2m"}),
    _d("gaia", [
        FieldSpec("ra", float, label="赤经 (deg)"),
        FieldSpec("dec", float, label="赤纬 (deg)"),
        FieldSpec("radius_deg", float, default=0.05),
    ], task="gaia_cone",
       example_params={"ra": 286.6583, "dec": 0.8656, "radius_deg": 0.02}),
    _d("ztf-meta", [
        FieldSpec("field", int, index="ztf-fields"),
        FieldSpec("filtercode", str, default="zg", choices=("zg", "zr", "zi")),
        FieldSpec("ccdid", int, default=1),
        FieldSpec("qid", int, default=1),
        FieldSpec("jd_min", float, default=2458100),
        FieldSpec("jd_max", float, default=2461000),
    ], task="ztf_metadata",
       example_params={"field": 673, "filtercode": "zg", "ccdid": 1,
                       "qid": 1, "jd_min": 2458800, "jd_max": 2458900}),
    _d("ztf", [
        FieldSpec("ffd", str, label="filefracday 14 位", name_like=True),
        FieldSpec("field", int, index="ztf-fields"),
        FieldSpec("filtercode", str, choices=("zg", "zr", "zi")),
        FieldSpec("ccdid", int, default=1),
        FieldSpec("qid", int, default=1),
    ], example_params={"ffd": "20200219403889", "field": 673,
                       "filtercode": "zg", "ccdid": 1, "qid": 1}),
    _d("mpc", [
        FieldSpec("target", str, label="目标名/编号（Ceres, 1）", name_like=True),
        FieldSpec("number", int, default=10, label="步数"),
        FieldSpec("step_days", float, default=1.0, label="步长（天）"),
    ], task="mpc_ephemeris",
       example_params={"target": "Ceres", "number": 10, "step_days": 1.0}),
    _d("simbad", [
        FieldSpec("ra", float),
        FieldSpec("dec", float),
        FieldSpec("radius_deg", float, default=0.1),
    ], task="simbad_cone",
       example_params={"ra": 180.0, "dec": 0.0, "radius_deg": 0.1}),
    _d("vizier", [
        FieldSpec("catalog", str, label="星表号（如 II/246）"),
        FieldSpec("ra", float),
        FieldSpec("dec", float),
        FieldSpec("radius_deg", float, default=0.1),
    ], task="vizier_cone",
       example_params={"catalog": "II/246", "ra": 150.0, "dec": 2.0,
                       "radius_deg": 0.2}),
    _d("ztf-lc", [
        FieldSpec("ra", float),
        FieldSpec("dec", float),
        FieldSpec("radius_arcsec", float, default=5.0,
                  label="锥半径（角秒），单源建议 ≤5"),
    ], task="ztf_lightcurve",
       example_params={"ra": 97.2, "dec": 30.4, "radius_arcsec": 8}),
    _d("legacy", [FieldSpec("brick", str, label="brick 名", index="legacy-bricks",
                            pattern=r"^[0-9a-z]{8}$")],
       example_params={"brick": "0001m002"}),
    _d("unwise", [
        FieldSpec("ra", float),
        FieldSpec("dec", float),
        FieldSpec("size", int, default=300),
        FieldSpec("band", str, default="w1", choices=("w1", "w2"),
                  label="波段（服务端不支持合并）"),
    ], task="unwise_cutout",
       example_params={"ra": 180.0, "dec": 0.0, "size": 300, "band": "w1"}),
]}
