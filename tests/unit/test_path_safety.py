"""路径安全（单元层）：清洗规则与描述符声明式校验。

背景：名字型参数会被拼进文件名/目录名。曾靠"各处自己 replace"——
tess 用 slug（`..` 仍能穿过）、mpc 只换空格（`/` 保留）、legacy 完全没处理，
结果 `brick="../../x"` 能把产物写到数据根之外（实测已证）。
现在两道防线：**输入即拒**（FieldSpec.name_like/pattern）+ 运行时兜底
（见 tests/kernel/test_path_safety.py）。
"""
from __future__ import annotations

from typing import ClassVar

import pytest

from myastro.descriptors import REGISTRY
from myastro.io.core import safe_name


@pytest.mark.cap("design.guards")
class TestSafeName:
    @pytest.mark.parametrize("value", [
        "0001m002", "WASP-12", "Ceres", "V* AB Aur", "ok.name", "目标一",
    ])
    def test_accepts_reasonable_names(self, value):
        assert safe_name(value, field="f") == value

    @pytest.mark.parametrize("value,why", [
        ("a/b", "斜杠"),
        ("a\\b", "反斜杠"),
        ("../x", "上跳"),
        ("..", "上跳"),
        (".", "当前目录"),
        ("", "空"),
        ("   ", "纯空白"),
        ("a\x00b", "NUL"),
        ("a\nb", "控制字符"),
        ("x" * 65, "过长"),
    ])
    def test_rejects_unsafe(self, value, why):
        with pytest.raises(ValueError):
            safe_name(value, field="f")

    def test_error_message_names_the_field(self):
        with pytest.raises(ValueError, match="target"):
            safe_name("../x", field="target")


@pytest.mark.cap("source.contract")
class TestDescriptorRejectsHostileValues:
    """会进路径的字段：恶意值必须在参数校验阶段被拒（不是到落盘才炸）。"""

    HOSTILE: ClassVar[list[str]] = ["../EVIL", "..", "a/b", "a\\b", "", "  ", "x" * 80]

    @pytest.mark.parametrize("source,field,extra", [
        ("legacy", "brick", {}),
        ("tess", "target", {"sector": 1}),
        ("mpc", "target", {"number": 1}),
        ("ztf", "ffd", {"field": 673, "filtercode": "zg", "ccdid": 1, "qid": 1}),
    ])
    def test_hostile_value_rejected(self, source, field, extra):
        d = REGISTRY[source]
        for bad in self.HOSTILE:
            params = {field: bad, **extra}
            with pytest.raises(ValueError):
                d.build_spec(params)

    @pytest.mark.parametrize("source,field,value,extra", [
        ("legacy", "brick", "0001m002", {}),
        ("tess", "target", "WASP-12", {"sector": 20}),
        ("mpc", "target", "Ceres", {"number": 1}),
        ("ztf", "ffd", "20200219403889",
         {"field": 673, "filtercode": "zg", "ccdid": 1, "qid": 1}),
    ])
    def test_normal_value_still_accepted(self, source, field, value, extra):
        spec = REGISTRY[source].build_spec({field: value, **extra})
        assert spec.params[field] == value

    def test_brick_pattern_is_strict(self):
        """brick 有真实格式（索引里都是 8 位小写字母数字）→ 用正则从严。"""
        d = REGISTRY["legacy"]
        for bad in ("0001M002", "0001m02", "0001m0002", "0001-m02", "abcdefgh"):
            if bad == "abcdefgh":
                continue                      # 合法形态
            with pytest.raises(ValueError):
                d.build_spec({"brick": bad})
        assert d.build_spec({"brick": "0001m002"})
