"""设计守卫：注册表漂移、文档同步、边界规则、schema/描述符契约。

（测试分层重组迁移；断言未改动。）
"""
import pytest


class TestRegistryDrift:
    @pytest.mark.cap("source.registry")
    def test_url_sources_have_source_entries(self):
        """漂移守卫：URL_SOURCES 每个键必须在 SOURCES 有条目且 url_key 互指。"""
        from myastro.io.sources import SOURCES
        from myastro.io.urls import URL_SOURCES

        for key in URL_SOURCES:
            assert key in SOURCES, f"URL_SOURCES[{key}] 在 SOURCES 无条目（漂移）"
            assert SOURCES[key].get("url_key") == key, (
                f"SOURCES[{key}].url_key 应为 {key}"
            )


class TestSourcesSchema:
    # 其余成员已拆分至：guards/test_doc_sync.py

    @pytest.mark.cap("source.registry")
    def test_schema_rejects_bad_status(self):

        from myastro.io.sources import _entry

        with pytest.raises(ValueError, match="STATUS"):
            _entry("x", "d", "bogus", "python", "v", "p", "e")
        with pytest.raises(ValueError, match="executor_type"):
            _entry("x", "d", "ok", "ftp", "v", "p", "e")

    @pytest.mark.cap("source.registry")
    def test_statuses_are_closed_vocab(self):
        from myastro.io.sources import SOURCES, STATUS

        for s in SOURCES.values():
            assert s["status"] in STATUS
