"""横切基础设施：缓存键、重试、原子落盘。"""
from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

# 可重试的异常类型（网络层）。requests 是 pyproject 里声明过的硬依赖，
# 且 aria2/health 早已在模块顶层导入它——这里直接导入，不再假装"软依赖"。
import requests as _requests

_RETRYABLE: tuple[type[BaseException], ...] = (
    ConnectionError, TimeoutError, OSError, _requests.exceptions.RequestException)


def is_retryable(exc: BaseException) -> bool:
    """5xx/网络错误可重试；4xx 属参数错误，重试无意义，直接抛。"""
    if isinstance(exc, _RETRYABLE):
        return True
    status = getattr(exc, "status_code", None) or getattr(
        getattr(exc, "response", None), "status_code", None)
    return bool(isinstance(status, int) and status >= 500)


def _normalize(obj: Any) -> Any:
    """递归规范化参数：浮点定 6 位有效数字，键排序由 json 保证。"""
    if isinstance(obj, dict):
        return {k: _normalize(v) for k, v in sorted(obj.items())}
    if isinstance(obj, (list, tuple)):
        return [_normalize(v) for v in obj]
    if isinstance(obj, float):
        return float(f"{obj:.6g}")
    return obj


def source_root(start: Path | None = None) -> Path:
    """定位 myastro **源码仓库根**；找不到则抛 ValueError。

    为什么需要：`test-map`/`doc-sync` 是开发向命令，它们要读写仓库里的
    `docs/*.md` 与 `tests/`。已安装的 wheel 里不存在源码树——此前
    `testmap` 用相对 CWD 的路径（在别处跑直接 FileNotFoundError 抛栈），
    `docsync` 用 `__file__` 上溯（在 wheel 里会**往 venv 的 site-packages 写文件**）。
    两者都应先确认"我在源码树里"，否则给出清晰提示。
    """
    import tomllib

    here = (start or Path(__file__)).resolve()
    for parent in [here, *here.parents]:
        pyproject = parent / "pyproject.toml"
        if not pyproject.is_file():
            continue
        try:
            data = tomllib.loads(pyproject.read_text())
        except Exception:              # noqa: BLE001, S112 — 别的 pyproject 不管
            continue
        if data.get("project", {}).get("name") == "myastro":
            return parent
    raise ValueError("未找到 myastro 源码仓库（该命令仅用于源码仓库开发）")


def safe_name(value: str, *, field: str = "参数") -> str:
    r"""校验"会被拼进文件/目录名"的字符串，返回原值；不安全则抛 ValueError。

    为什么需要单一入口：路径安全曾靠"各处自己 replace"——tess 用 slug
    （`..` 仍能穿过）、mpc 只换空格（`/` 原样保留）、legacy 完全没处理，
    结果 `brick="../../x"` 能把产物写到数据根之外。清洗规则只应有一处。

    规则（宁可拒绝，不做静默改写——静默改写会让人以为写的是别的名字）：
      - 非空、非纯空白
      - 不含路径分隔符 `/` `\` 与 NUL/控制字符
      - 不是 `.` 或 `..`
      - 长度 ≤ 64（文件名组件，不是完整路径）
    """
    if not isinstance(value, str):
        # 语义上类型错该用 TypeError，但校验层统一 ValueError → 门面 ParamError，
        # 保持"调用方输入有问题"这一类错误的单一出口
        raise ValueError(f"{field} 必须是字符串")  # noqa: TRY004
    if not value.strip():
        raise ValueError(f"{field} 不能为空")
    bad = [ch for ch in value if ch in "/\\\0" or ord(ch) < 32 or ord(ch) == 127]
    if bad:
        raise ValueError(
            f"{field} 含路径分隔符或控制字符 {bad[0]!r}：{value!r}")
    if value in (".", ".."):
        raise ValueError(f"{field} 不能是 {value!r}")
    if len(value) > 64:
        raise ValueError(f"{field} 过长（>{64}）：{value[:20]!r}…")
    return value


def cache_key(source: str, params: dict[str, Any]) -> str:
    """(source, params) → 稳定哈希键。乱序 dict、抖动浮点必须得到同一键。"""
    canonical = json.dumps({"source": source, "params": _normalize(params)},
                           sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def retry(fn: Callable[[], Any], *, attempts: int = 5,
          base: float = 1.0, max_delay: float = 60.0,
          sleep: Callable[[float], None] = time.sleep) -> Any:
    """指数退避重试：仅对 is_retryable 的异常重试，其余立即抛出。"""
    delay = base
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except BaseException as exc:
            if attempt == attempts or not is_retryable(exc):
                raise
            sleep(delay)
            delay = min(delay * 2, max_delay)
    raise AssertionError("unreachable")  # pragma: no cover


def atomic_write(path: str | os.PathLike,
                 write_fn: Callable[[Path], Any]) -> None:
    """原子落盘：写 .tmp 再 os.replace()；异常时清理临时文件。

    write_fn 接收临时路径并完成实际写入。返回值不向外传递——所有调用点
    都是 to_parquet 这类无返回值写入，透传是没有消费者的特性（审计删除）。
    """
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    try:
        write_fn(tmp)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
