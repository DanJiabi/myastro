"""预填充映射（`build_spec` 的逆）：纯逻辑，不碰 db/网络/TUI。"""
from __future__ import annotations

import pytest

from myastro.descriptors import Prefill, prefill_from_spec


@pytest.mark.cap("source.registry")
class TestPrefillMapping:
    def test_descriptor_hit_keeps_declared_params(self):
        pf = prefill_from_spec({"source": "tess", "params": {
            "target": "WASP-12", "sector": 20, "cadence": "2m"}})
        assert pf.mode == "descriptor" and pf.source == "tess"
        assert pf.params == {"target": "WASP-12", "sector": 20,
                             "cadence": "2m"}
        assert pf.reason == ""
        assert bool(pf) is True

    def test_extra_params_dropped_and_reported(self):
        """老作业带的描述符外参数（如 gaia 的 columns）不得污染表单。"""
        pf = prefill_from_spec({"source": "gaia", "params": {
            "ra": 1.0, "dec": 2.0, "columns": ["source_id"]}})
        assert pf.mode == "descriptor"
        assert pf.params == {"ra": 1.0, "dec": 2.0}
        assert "columns" in pf.reason

    def test_missing_required_fields_reported(self):
        """部分匹配仍可用，但必须告知缺哪些必填项。"""
        pf = prefill_from_spec({"source": "tess", "params": {}})
        assert pf.mode == "descriptor" and pf.params == {}
        assert "需补填" in pf.reason and "target" in pf.reason

    def test_params_with_no_overlap_reported(self):
        pf = prefill_from_spec({"source": "vizier",
                                "params": {"legacy_key": 1}})
        assert pf.mode == "descriptor" and pf.params == {}
        assert "无交集" in pf.reason

    def test_custom_url_job_maps_to_custom_form(self):
        pf = prefill_from_spec({
            "source": "quick", "params": {},
            "url": "https://example.com/a/b.fits",
            "dest": "/data/MAD/quick/b.fits"})
        assert pf.mode == "custom" and pf.source is None
        assert pf.custom == {"url": "https://example.com/a/b.fits",
                             "name": "b.fits", "mission": "quick"}

    def test_custom_url_without_dest_uses_url_basename(self):
        pf = prefill_from_spec({"source": "x", "params": {},
                                "url": "https://example.com/z.fits"})
        assert pf.mode == "custom" and pf.custom["name"] == "z.fits"
        assert pf.custom["mission"] == ""

    def test_unknown_source_degrades(self):
        pf = prefill_from_spec({"source": "index",
                                "params": {"name": "legacy-bricks"}})
        assert pf.mode == "none" and bool(pf) is False
        assert "不在注册表" in pf.reason

    def test_empty_spec_degrades(self):
        pf = prefill_from_spec({})
        assert pf.mode == "none" and pf.reason

    def test_prefill_type_is_exported(self):
        """门面/客户端构造与判断依赖该类型（bool 语义即"能预填充"）。"""
        assert bool(Prefill(mode="descriptor")) is True
        assert bool(Prefill(mode="none")) is False
