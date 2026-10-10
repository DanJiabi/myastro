"""内核：真 sqlite（tmp），网络打桩；账本/作业/索引/健康/调度/巡检/检索。

（测试分层重组迁移；断言未改动。）
"""
import pytest


class TestSchedule:
    @pytest.mark.cap("acquire.schedule")
    def test_plist_render_and_install(self, env, monkeypatch):
        import myastro.io.schedule as sc

        monkeypatch.setattr(sc, "LAUNCHD_DIR", env / "LaunchAgents")
        monkeypatch.setattr(sc.subprocess, "run", lambda *a, **k: None)
        p = sc.install("health")
        assert p.exists()
        xml = p.read_text()
        assert "com.myastro.health" in xml
        assert "<integer>9</integer>" in xml  # 09:00
        assert "-m</string>" in xml and "health" in xml
        # 幂等重装
        p2 = sc.install("health")
        assert p2 == p
        assert sc.remove("health") and not p.exists()
        rows = sc.list_installed()
        assert all(not r["installed"] for r in rows)

    @pytest.mark.cap("acquire.schedule")
    def test_weekday_variant(self, env, monkeypatch):
        import myastro.io.schedule as sc

        monkeypatch.setattr(sc, "LAUNCHD_DIR", env / "LA")
        monkeypatch.setattr(sc.subprocess, "run", lambda *a, **k: None)
        sc.install("index-weekly")
        xml = (env / "LA" / "com.myastro.index.plist").read_text()
        assert "<key>Weekday</key><integer>0</integer>" in xml

    @pytest.mark.cap("acquire.schedule")
    def test_unknown_task(self):

        import myastro.io.schedule as sc

        with pytest.raises(LookupError):
            sc.install("nope")
