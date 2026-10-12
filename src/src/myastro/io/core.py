"""横切基础设施：缓存键、重试、原子落盘。"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
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


@contextmanager
def quiet_warnings(*patterns: str):
    """临时抑制匹配这些正则的警告（只用于第三方库导入期的已知无害提示）。

    刻意**按消息精确匹配**而不是 `simplefilter("ignore")`：只挡我们判定过的那条，
    第三方以后新增的其它警告照常暴露，不会被我们的代码吞掉。
    """
    import warnings

    with warnings.catch_warnings():
        for pattern in patterns:
            warnings.filterwarnings("ignore", message=pattern)
        yield


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


# parquet 写入串行化（见 write_parquet 说明）
_PARQUET_WRITE_LOCK = threading.Lock()


def _clean_object_column(s):
    """object 列规整：bytes → 字符串（缺失仍是缺失）。

    IPAC/VizieR 返回的表里 char 列常是 bytes；规整后语义确定、可读。
    """
    if s.map(lambda v: isinstance(v, (bytes, bytearray))).any():
        return s.map(lambda v: v.decode("utf-8", "replace")
                     if isinstance(v, (bytes, bytearray)) else v)
    return s


def _arrow_type(dtype):
    """pandas dtype → pyarrow 类型（空表也要保住类型，不能退化成 null）。

    返回 None 表示"交给 arrow 自己推断"（混合类型的 object 列走这条）。
    """
    import pandas as pd
    import pyarrow as pa

    if pd.api.types.is_bool_dtype(dtype):
        return pa.bool_()
    if pd.api.types.is_integer_dtype(dtype):
        return pa.int64()
    if pd.api.types.is_float_dtype(dtype):
        return pa.float64()
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return pa.timestamp("us")
    if dtype == object:
        return None                      # 混合类型：让 arrow 推断
    if pd.api.types.is_string_dtype(dtype):
        return pa.string()               # pandas StringDtype 等
    return None


def _column_to_arrow(series):
    """单列 → arrow 数组。**逐列用纯 Python 值构造**，绕开 pandas 的
    `__arrow_array__` / `Table.from_pandas` 转换路径。

    为什么必须绕开（2026-10 实测的段错误，100% 可复现）：
    全新数据根下连续 `fetch ztf-lc` → `fetch ztf-meta`，第二个作业在**工作线程**
    里写 parquet 时 `SIGSEGV`（12/12），崩溃帧为
    `pandas/core/arrays/string_.py: __arrow_array__` ← `pyarrow.pandas_compat.convert_column`
    ← 我们这一行。同序列在**主线程**里跑不崩（直接调用源函数 0/3），
    说明是"非主线程 + pandas→arrow 转换"共同触发（pyarrow 25.0.0 / pandas 2.3.3 /
    numpy 2.5.3）。逐列构造实测不再崩溃；且显式传类型后空表的 dtype 不会丢
    （`pa.array([], from_pandas=True)` 单独用会退化成 null 类型）。
    """
    import pyarrow as pa

    dtype = series.dtype
    values = _clean_object_column(series).tolist()
    if dtype == object:
        # object：一律建成字符串列。不能交给 arrow 推断——它按**首个非空值**定型，
        # 之后遇到别的类型就抛 ArrowTypeError（实测混合列 ["a", 1] 即如此）。
        # 统一 str() 后语义确定，且与"表元数据列"的实际用法一致。
        return pa.array([None if v is None else str(v) for v in values],
                        type=pa.string())
    arrow_type = _arrow_type(dtype)
    if arrow_type is None:
        return pa.array(values, from_pandas=True)
    return pa.array(values, type=arrow_type, from_pandas=True)


def write_parquet(df, path: str | os.PathLike) -> None:
    """统一的 parquet 落盘：逐列构造 arrow 数组 + 进程内互斥 + 原子替换。

    **不要直接用 `df.to_parquet(...)`**。这里逐列用纯 Python 值构造 arrow 数组并
    显式给类型，原因有二：
    1. 绕开 pandas 的转换入口（`__arrow_array__` / `Table.from_pandas`），
       顺带避开混合 object 列上 `ArrowTypeError: Expected bytes, got a 'int' object`
       这类按首个非空值定型的坑；
    2. 空表（ibe 检索无命中是常态）**必须保住 dtype**——直接
       `pa.array([], from_pandas=True)` 会得到 null 类型，读回来整列就废了。

    段错误（0.3.5 处理，结论如实记录）：
    实测在本机环境（conda pyarrow 25.0.0 / pandas 2.3.3 / numpy 2.5.3）全新数据根下
    连续 `fetch ztf-lc` → `fetch ztf-meta`，**100% SIGSEGV**，崩溃帧在作业**工作线程**
    里构造 arrow 数组那一行。已验证的事实：
    - 同序列在**调用线程**里执行不崩（直接调用源函数 0/3、作业同步执行 0/5）；
      工作线程里 6/6、10/10 崩；
    - 逐列构造、`set_cpu_count(1)`/`set_io_thread_count(1)`（两种摆放位置）**都不能**
      消除它（均 6/6 崩）；因此线程池钉位已撤掉——无效的规避手段留在代码里是负担。
    故 0.3.5 的处置是：**阻塞式 fetch 不再用工作线程**（见 `jobs.runner.fetch`），
    并在 `scripts/soak_write.py` 留了可复现的浸泡工具。TUI/submit 路径仍在工作线程里
    跑作业，属**已知残留风险**（上游 pyarrow 在非主线程里的问题，未定位到根因）。
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    def _write(tmp) -> None:
        with _PARQUET_WRITE_LOCK:
            table = pa.table({str(c): _column_to_arrow(df[c])
                              for c in df.columns})
            pq.write_table(table, tmp)

    atomic_write(path, _write)


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
