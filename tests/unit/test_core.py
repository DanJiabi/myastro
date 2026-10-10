"""纯逻辑单元：无 db / 网络 / TUI。

（测试分层重组迁移；断言未改动。）
"""

import pytest

from myastro.io.core import atomic_write, cache_key, is_retryable, retry


class TestCacheKey:
    @pytest.mark.cap("manage.ledger")
    def test_dict_order_insensitive(self):
        assert cache_key("tess", {"a": 1, "b": 2}) == cache_key(
            "tess", {"b": 2, "a": 1}
        )

    @pytest.mark.cap("manage.ledger")
    def test_float_jitter_stable(self):
        assert cache_key("gaia", {"r": 0.10000001}) == cache_key("gaia", {"r": 0.1})

    @pytest.mark.cap("manage.ledger")
    def test_different_sources_differ(self):
        assert cache_key("tess", {"a": 1}) != cache_key("ztf", {"a": 1})

    @pytest.mark.cap("manage.ledger")
    def test_different_params_differ(self):
        assert cache_key("tess", {"a": 1}) != cache_key("tess", {"a": 2})


class Fake5xx(Exception):
    status_code = 503


class Fake4xx(Exception):
    status_code = 404


class TestRetry:
    @pytest.mark.cap("acquire.fetch")
    def test_success_after_failures(self):
        calls = []

        def flaky():
            calls.append(1)
            if len(calls) < 3:
                raise Fake5xx("boom")
            return "ok"

        assert retry(flaky, sleep=lambda _: None) == "ok"
        assert len(calls) == 3

    @pytest.mark.cap("acquire.fetch")
    def test_4xx_not_retried(self):
        calls = []

        def bad():
            calls.append(1)
            raise Fake4xx("not found")

        with pytest.raises(Fake4xx):
            retry(bad, sleep=lambda _: None)
        assert len(calls) == 1

    @pytest.mark.cap("acquire.fetch")
    def test_exhaustion_raises(self):
        def always_fail():
            raise ConnectionError("down")

        with pytest.raises(ConnectionError):
            retry(always_fail, attempts=3, sleep=lambda _: None)

    @pytest.mark.cap("acquire.fetch")
    def test_is_retryable_classification(self):
        assert is_retryable(Fake5xx())
        assert is_retryable(ConnectionError())
        assert not is_retryable(Fake4xx())
        assert not is_retryable(ValueError())


class TestAtomicWrite:
    @pytest.mark.cap("acquire.fetch")
    def test_writes_and_replaces(self, tmp_path):
        target = tmp_path / "out.fits"

        def write(p):
            p.write_bytes(b"FITS")

        atomic_write(target, write)
        assert target.read_bytes() == b"FITS"
        assert list(tmp_path.glob("*.tmp")) == []

    @pytest.mark.cap("acquire.fetch")
    def test_failure_leaves_no_tmp_and_no_target(self, tmp_path):
        target = tmp_path / "out.fits"

        def write(p):
            p.write_bytes(b"partial")
            raise RuntimeError("disk full")

        with pytest.raises(RuntimeError):
            atomic_write(target, write)
        assert not target.exists()
        assert list(tmp_path.glob("*.tmp")) == []

    @pytest.mark.cap("acquire.fetch")
    def test_failure_keeps_existing_file_intact(self, tmp_path):
        target = tmp_path / "out.fits"
        target.write_bytes(b"OLD")

        def write(p):
            p.write_bytes(b"NEW")
            raise RuntimeError("interrupted")

        with pytest.raises(RuntimeError):
            atomic_write(target, write)
        assert target.read_bytes() == b"OLD"
