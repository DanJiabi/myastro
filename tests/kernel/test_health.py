"""内核：真 sqlite（tmp），网络打桩；账本/作业/索引/健康/调度/巡检/检索。

（测试分层重组迁移；断言未改动。）
"""
import pytest


class TestHealth:
    @pytest.mark.cap("source.health")
    def test_probe_persists_and_grades(self, env, monkeypatch):
        monkeypatch.setenv("MYASTRO_DATA", str(env / "data"))
        monkeypatch.setenv("MYASTRO_DB", str(env / "astro.db"))
        import myastro.io.health as h
        from myastro.io.db import DB

        DB().init()
        monkeypatch.setattr(
            h, "_probe_one", lambda url, timeout=10: ("degraded", "HTTP 500")
        )
        out = h.probe("unwise")
        assert out[0]["status"] == "degraded"
        view = h.health_view()
        assert view["unwise"]["status"] == "degraded"

    @pytest.mark.cap("source.health")
    def test_unprobeable_rejected(self, env, monkeypatch):
        monkeypatch.setenv("MYASTRO_DATA", str(env / "data"))
        monkeypatch.setenv("MYASTRO_DB", str(env / "astro.db"))
        import myastro.io.health as h
        from myastro.io.db import DB

        DB().init()

        with pytest.raises(LookupError):
            h.probe("manifest")

    @pytest.mark.cap("source.health")
    def test_facade_health(self, env, monkeypatch):
        monkeypatch.setenv("MYASTRO_DATA", str(env / "data"))
        monkeypatch.setenv("MYASTRO_DB", str(env / "astro.db"))
        import myastro.io.health as h
        from myastro.io.db import DB

        DB().init()
        monkeypatch.setattr(h, "_probe_one", lambda u, timeout=10: ("ok", "200"))
        import myastro as ma

        assert all(r["status"] == "ok" for r in ma.health())


class TestProbeGrading:
    """_probe_one 的 HTTP 分级（ok/degraded/unreachable）——健康能力的核心逻辑。

    此前只被 monkeypatch 掉，从未验证分级本身：服务端 500 与 DNS 失联
    对用户是两种处置（等待恢复 vs 找替代源），不能被归成一类。
    """

    class _Resp:
        def __init__(self, code):
            self.status_code = code

    def _grade(self, monkeypatch, behavior):
        import myastro.io.health as h

        if isinstance(behavior, Exception):

            def head(*a, **k):
                raise behavior
        else:

            def head(*a, **k):
                return self._Resp(behavior)

        monkeypatch.setattr(h.requests, "head", head)
        return h._probe_one("https://example.invalid")

    @pytest.mark.cap("source.health")
    def test_2xx_is_ok(self, monkeypatch):
        assert self._grade(monkeypatch, 200) == ("ok", "HTTP 200")

    @pytest.mark.cap("source.health")
    def test_5xx_is_degraded(self, monkeypatch):
        assert self._grade(monkeypatch, 503)[0] == "degraded"

    @pytest.mark.cap("source.health")
    def test_4xx_is_degraded(self, monkeypatch):
        assert self._grade(monkeypatch, 404)[0] == "degraded"

    @pytest.mark.cap("source.health")
    def test_connection_error_is_unreachable(self, monkeypatch):
        import requests

        assert (
            self._grade(monkeypatch, requests.ConnectionError("dns"))[0]
            == "unreachable"
        )

    @pytest.mark.cap("source.health")
    def test_timeout_is_unreachable(self, monkeypatch):
        import requests

        assert self._grade(monkeypatch, requests.Timeout())[0] == "unreachable"
