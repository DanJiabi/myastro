"""插件发现（协议 v1 的第三块：注册契约 → 示例 → **自动发现**）。

设计（见 docs/zh/dev/plugin-api.md §8 与批准的设计稿）：

- **惰性**：不在 `import myastro` 时发现——那会拖慢每次启动，并把插件缺陷的影响面
  扩大到所有命令。由需要源清单的入口（`sources`/`describe`/`fetch`）触发一次，结果缓存。
- **两条通道**：entry-points 组 `myastro.sources`（正式）+ `MYASTRO_SOURCES`
  环境变量（本地开发免打包；逗号分隔，支持 `模块:属性`）。
- **隔离**：先在本进程之外**预探测**（子进程 `import` + 超时），失败/挂死的插件被记为
  错误并跳过，**绝不影响主进程**——这是"插件出问题不能拖垮核心"这条不变量的实现手段。
- **错误可见**：每个失败插件留一条结构化记录（模块名/异常类型/摘要/建议），
  由 `doctor` 与 `sources()` 呈现（不落盘）。

本模块**不**在导入时做任何发现动作；`discover()` 是唯一的副作用入口，且幂等。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

PLUGIN_GROUP = "myastro.sources"
ENV_VAR = "MYASTRO_SOURCES"

# 预探测超时（秒）。测试可 monkeypatch 成小值，避免用"等 20 秒"来验证超时行为。
PROBE_TIMEOUT = 20.0


@dataclass
class PluginError:
    """一条插件加载失败记录（给 doctor/CLI 展示，不抛给调用方）。"""

    module: str
    error_type: str
    message: str
    hint: str = ""

    def as_dict(self) -> dict:
        return {"module": self.module, "error_type": self.error_type,
                "message": self.message, "hint": self.hint}


@dataclass
class _State:
    discovered: bool = False
    loaded: list[str] = field(default_factory=list)
    errors: list[PluginError] = field(default_factory=list)
    # 源名 → 提供它的插件模块（发现时按"导入前后新增的注册表键"归属）
    origins: dict[str, str] = field(default_factory=dict)


_STATE = _State()


def _candidates() -> list[tuple[str, str]]:
    """[(来源, 规格)]：**先环境变量**（开发者意图明确），后 entry-points（按名排序）。"""
    import importlib.metadata as md

    out: list[tuple[str, str]] = [("env", spec) for spec in env_entries()]
    try:
        eps = md.entry_points(group=PLUGIN_GROUP)
    except TypeError:                    # 旧版 API（dict 形态）
        eps = md.entry_points().get(PLUGIN_GROUP, [])   # type: ignore[attr-defined]
    for ep in sorted(eps, key=lambda e: e.name):
        out.append((f"entry-point:{ep.name}", str(ep.value)))
    return out


def _probe(module: str) -> PluginError | None:
    """子进程预探测：把"挂死/崩溃"挡在主进程之外（设计稿选择 (b)）。

    返回值：None 表示通过；否则是要记录的错误。
    """
    import subprocess
    import sys

    # 结构化探测：子进程把异常类型与消息按标记打到 stderr，主进程据此**精确分类**
    # （否则注册类错误 —— 如协议版本不符 —— 只会被笼统报成"子进程导入失败"，
    #  丢掉 ParamError 这个类型与对应的修复提示）。
    marker = "MYASTRO_PROBE_ERROR"
    code = (
        "import importlib, sys\n"
        "try:\n"
        f"    importlib.import_module({module!r})\n"
        "except BaseException as e:\n"
        f"    print({marker!r} + '\\t' + type(e).__name__ + '\\t' + str(e),"
        " file=sys.stderr)\n"
        "    raise SystemExit(3)\n"
    )
    # 把当前 `sys.path` 透传给子进程（PYTHONPATH）：否则**工作区里的开发模块**
    # （MYASTRO_SOURCES 指向它，未安装）会被预探测误判成"找不到模块"——
    # 这是实测踩到的：子进程只继承环境变量，不继承 sys.path。
    import os

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
    try:
        done = subprocess.run([sys.executable, "-c", code], check=False, env=env,
                              capture_output=True, text=True, timeout=PROBE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return PluginError(
            module, "ProbeTimeout",
            f"子进程预探测超过 {PROBE_TIMEOUT:g}s（疑似 import 阶段挂死）",
            "注册应尽量惰性：import 时不要做网络/阻塞操作")
    if done.returncode != 0:
        err = (done.stderr or "")
        for line in err.splitlines():
            if line.startswith(marker):
                _, etype, message = (line.split("\t", 2) + ["", ""])[:3]
                hint = ("检查描述符是否符合插件协议规则"
                        "（docs/zh/dev/plugin-api.md；myastro doctor 会复述原因）"
                        if etype in ("ParamError", "ValueError") else "")
                return PluginError(module, etype, message[:300], hint)
        last = (err.strip().splitlines() or [""])[-1]
        return PluginError(
            module, "ProbeFailed",
            f"子进程 import 失败：{last[:200]}",
            f"先在命令行复现：python -c \"import {module}\"")
    return None


def _load_one(module: str, attr: str | None) -> None:
    """在本进程导入插件（注册由 import 副作用完成）；异常向上抛，由调用方记录。"""
    import importlib

    mod = importlib.import_module(module)
    if attr:
        target = getattr(mod, attr)          # 属性不存在 → AttributeError 被记录
        if callable(target):
            target()                          # 约定：`模块:注册函数` 形态会被调用


def discover(*, force: bool = False) -> None:
    """发现并加载插件（幂等；唯一副作用入口）。

    流程：候选（env → entry-points）→ 按模块去重 → **子进程预探测** → 本进程导入。
    任何一步失败都只记一条 `PluginError` 并跳过该插件，**不影响主进程与其它插件**。
    """
    if _STATE.discovered and not force:
        return
    _STATE.discovered = True

    seen: set[str] = set()
    for origin, spec in _candidates():
        module, _, attr = spec.partition(":")
        module, attr = module.strip(), attr.strip() or None
        if not module or module in seen:
            continue                          # 空项/重复列出：只加载一次
        seen.add(module)

        probed = _probe(module)
        if probed is not None:
            _STATE.errors.append(probed)
            continue
        before = _registry_names()
        try:
            _load_one(module, attr)
        except Exception as exc:              # noqa: BLE001  插件缺陷必须被隔离
            hint = ("检查描述符是否符合插件协议规则（myastro doctor 会复述原因）"
                    if type(exc).__name__ in ("ParamError", "ValueError") else "")
            _STATE.errors.append(PluginError(
                module, type(exc).__name__, str(exc)[:300], hint))
            continue
        for name in _registry_names() - before:
            _STATE.origins[name] = module      # 新注册的源归这个插件
        _STATE.loaded.append(module)


def ensure_discovered() -> None:
    """惰性触发的唯一入口：需要源清单/任务表前调用一次（幂等、缓存）。

    **刻意不在 `import myastro` 时发现**：那会把插件缺陷的影响面扩大到所有命令，
    并拖慢每次启动。由 facade 的相关入口与 runner 的任务解析兜底调用。
    """
    discover()


def loaded() -> list[str]:
    """已成功加载的插件模块名（只读副本）。"""
    return list(_STATE.loaded)


def errors() -> list[PluginError]:
    """加载失败的插件记录（只读副本）。"""
    return list(_STATE.errors)


def _registry_names() -> set[str]:
    from ..descriptors import REGISTRY

    return set(REGISTRY)


def origin_of(source: str) -> str:
    """源的来源标注：`builtin` / `plugin:<模块>` / `runtime`（显式注册）。

    为什么需要：装了几个插件之后，用户与 doctor 都要能回答"这个源是谁提供的"。
    `runtime` 指插件机制之外显式 `register_source` 注册的源（例如 notebook 里临时加的）。
    """
    from ..descriptors import BUILTIN_SOURCES

    if source in BUILTIN_SOURCES:
        return "builtin"
    module = _STATE.origins.get(source)
    return f"plugin:{module}" if module else "runtime"


def _reset_for_tests() -> None:
    """测试专用：清空发现状态（下一个用例可重新发现）。"""
    _STATE.discovered = False
    _STATE.loaded.clear()
    _STATE.errors.clear()
    _STATE.origins.clear()


def env_entries() -> list[str]:
    """解析 `MYASTRO_SOURCES`（逗号分隔，允许空项与 `模块:属性`）。"""
    raw = os.environ.get(ENV_VAR, "")
    return [part.strip() for part in raw.split(",") if part.strip()]
