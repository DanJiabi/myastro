"""门面异常体系：第三方可 catch 区分的四类错误。

内核内部仍用原生异常；门面负责映射。映射规则：
  参数缺失/类型错/未知源       → ParamError
  源/作业/索引/数据不存在      → NotFoundError
  网络与远端服务失败           → NetworkError（内核 ConnectionError/HTTPError
                                 及含"aria2 error/503/timeout"语义的运行时错）
  状态冲突（活跃作业删/重试）   → StateError
"""
from __future__ import annotations


class MyAstroError(Exception):
    """门面异常基类。"""


class ParamError(MyAstroError, ValueError):
    """调用方参数问题：缺失、类型不符、未知源名。"""


class NotFoundError(MyAstroError, LookupError):
    """目标不存在：job id、索引名、数据记录。"""


class NetworkError(MyAstroError, ConnectionError):
    """网络/远端服务失败（可重试类）。"""


class StateError(MyAstroError, RuntimeError):
    """状态冲突：对活跃作业删除、对健康作业重试等。"""
