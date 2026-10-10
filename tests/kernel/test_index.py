"""内核：真 sqlite（tmp），网络打桩；账本/作业/索引/健康/调度/巡检/检索。

（测试分层重组迁移；断言未改动。）
"""

import pytest

from myastro.io.index import INDEXES, count_index, load_index, search_index

"""索引能力测试：builder 来源、键列语义、批量资格规则。

覆盖 2026-10 新增：ztf-fields（builder 型，本地构造无下载）。
"""


class TestIndexRegistry:
    @pytest.mark.cap("manage.index")
    def test_ztf_fields_registered_as_builder(self):
        spec = INDEXES["ztf-fields"]
        assert "builder" in spec and "url" not in spec  # 本地构造，无下载
        assert spec["key_col"] == "field"

    @pytest.mark.cap("manage.index")
    def test_legacy_still_url_based(self):
        spec = INDEXES["legacy-bricks"]
        assert "url" in spec and "parse" in spec
        assert "builder" not in spec


class TestZtfFieldsBuild:
    @pytest.fixture
    def built(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MYASTRO_DATA", str(tmp_path / "data"))
        monkeypatch.setenv("MYASTRO_DB", str(tmp_path / "astro.db"))
        from myastro.io.index import update_index

        return update_index("ztf-fields")

    @pytest.mark.cap("manage.index")
    def test_build_is_local_and_compact(self, built):
        df = load_index("ztf-fields")
        assert df.shape == (1776, 3)
        assert list(df.columns) == ["field", "ra", "dec"]
        assert df["field"].dtype.kind in "iu"  # 键保持整型

    @pytest.mark.cap("manage.index")
    def test_known_field_coordinates(self, built):
        df = load_index("ztf-fields")
        row = df[df.field == 673].iloc[0]
        assert 196.0 < row.ra < 196.3 and 33.2 < row.dec < 33.5

    @pytest.mark.cap("manage.index")
    def test_prefix_search_on_int_key(self, built):
        # int 键按字符串化前缀匹配：'67' 命中 67 与 670-679
        hits = search_index("ztf-fields", "67", limit=10)
        assert "67" in hits and "673" in hits
        assert count_index("ztf-fields", "673") == 1

    @pytest.mark.cap("manage.index")
    def test_rebuild_idempotent(self, built, tmp_path, monkeypatch):
        from myastro.io.index import update_index

        p2 = update_index("ztf-fields")
        assert p2 == built  # 同一路径重复构建


class TestBatchEligibility:
    """批量资格：索引字段须能单独标识一次获取。"""

    @pytest.mark.cap("manage.index")
    def test_ztf_excluded_needs_ffd(self):
        from myastro.io.top.batchscreen import _indexed_sources

        keys = {k for k, _ in _indexed_sources()}
        assert "ztf" not in keys  # ffd 无默认 → 单 field 构不出 spec

    @pytest.mark.cap("manage.index")
    def test_ztf_meta_included(self):
        from myastro.io.top.batchscreen import _indexed_sources

        keys = {k for k, _ in _indexed_sources()}
        assert "ztf-meta" in keys  # 除 field 外全有默认

    @pytest.mark.cap("manage.index")
    def test_legacy_included(self):
        from myastro.io.top.batchscreen import _indexed_sources

        assert ("legacy", "brick") in _indexed_sources()

    @pytest.mark.cap("manage.index")
    def test_eligibility_matches_buildable_spec(self):
        """资格规则自证：入选源用默认值补齐后必须能 build_spec。"""
        from myastro.descriptors import REGISTRY
        from myastro.io.top.batchscreen import _indexed_sources

        for key, fname in _indexed_sources():
            d = REGISTRY[key]
            params = {
                f.name: (
                    f.default
                    if f.default is not None
                    else (1 if f.type is int else "x")
                )
                for f in d.fields
            }
            params[fname] = d.example_params.get(fname, params[fname])
            d.build_spec(params)  # 不抛即资格成立

    @pytest.mark.cap("manage.index")
    def test_ztf_would_fail_without_ffd(self):
        """反证：绕过资格规则直接构造 ztf 单 field spec 必然失败。"""
        from myastro.descriptors import REGISTRY

        with pytest.raises(ValueError):
            REGISTRY["ztf"].build_spec({"field": 673})


@pytest.mark.cap("manage.index")
class TestIndexCacheAndPrefix:
    """缓存与前缀二分：TUI 每敲一键都查索引，性能与正确性都要守住。"""

    def _synth(self, tmp_path, monkeypatch, keys):
        import pandas as pd

        from myastro.io import index as idx
        monkeypatch.setenv("MYASTRO_DATA", str(tmp_path / "data"))
        monkeypatch.setenv("MYASTRO_DB", str(tmp_path / "astro.db"))
        idx.INDEXES["synth"] = {"desc": "合成", "key_col": "key"}
        p = idx.index_path("synth")
        pd.DataFrame({"key": keys}).to_parquet(p, index=False)
        return idx, p

    def test_prefix_matches_naive_scan(self, tmp_path, monkeypatch):
        keys = [f"{i:04d}" for i in range(500)] + ["0001a", "0001b"]
        idx, _ = self._synth(tmp_path, monkeypatch, keys)
        try:
            for prefix in ("0", "0001", "00012", "004", "zz"):
                naive = sorted(k for k in keys if k.startswith(prefix))
                assert idx.count_index("synth", prefix) == len(naive)
                assert idx.search_index("synth", prefix, 5) == naive[:5]
        finally:
            idx.INDEXES.pop("synth", None)

    def test_cache_reused_until_file_changes(self, tmp_path, monkeypatch):
        import pandas as pd
        idx, path = self._synth(tmp_path, monkeypatch, ["a1", "a2"])
        try:
            first = idx.load_index("synth")
            assert idx.load_index("synth") is first          # 命中缓存，不重读
            assert idx.search_index("synth", "a", 5) == ["a1", "a2"]

            pd.DataFrame({"key": ["a1", "a9"]}).to_parquet(path, index=False)
            second = idx.load_index("synth")
            assert second is not first                       # mtime 变化 → 失效
            assert idx.search_index("synth", "a", 5) == ["a1", "a9"]
        finally:
            idx.INDEXES.pop("synth", None)

    def test_save_invalidates_cache(self, tmp_path, monkeypatch):
        idx, _ = self._synth(tmp_path, monkeypatch, ["old1"])
        try:
            assert idx.search_index("synth", "old", 5) == ["old1"]
            idx._save("synth", __import__("pandas").DataFrame(
                {"key": ["new1"]}))
            assert idx.search_index("synth", "old", 5) == []
            assert idx.search_index("synth", "new", 5) == ["new1"]
        finally:
            idx.INDEXES.pop("synth", None)
