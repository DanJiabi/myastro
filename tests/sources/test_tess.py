"""数据源契约：只打桩网络层，描述符/落盘/入库走真实路径。

（测试分层重组迁移；断言未改动。）
"""

import pandas as pd
import pytest

from myastro.io.db import DB
from myastro.io.sources import tess


class TestTess:
    @pytest.mark.cap("source.contract")
    def test_slug(self):
        assert tess._slug("WASP-12 b") == "WASP-12_b"
        assert tess._slug("///") == "unnamed"

    @pytest.mark.cap("source.contract")
    def test_invalid_cadence_rejected(self, env):
        DB().init()
        try:
            tess.tess_lightcurve("WASP-12", cadence="5m")
            assert False
        except ValueError:
            pass

    @pytest.mark.cap("source.contract")
    def test_fn_produces_parquet_and_registers(self, env, monkeypatch):

        def fake_download(target, sector, cadence, cache_dir):
            df = pd.DataFrame(
                {
                    "time": [1.0, 2.0, 3.0],
                    "flux": [1.0, 0.99, 1.01],
                    "flux_err": [1e-4] * 3,
                    "quality": [0] * 3,
                }
            )
            return df, {
                "target": target,
                "mission": "TESS",
                "sector": 20,
                "cadence": cadence,
            }

        monkeypatch.setattr(tess, "_download_lc", fake_download)
        result = tess.tess_lightcurve("WASP-12", sector=20)
        assert result.cache_hit is False
        p = result.paths[0]
        assert p.name == "lc_s20_2m.parquet"
        assert "data/tess/WASP-12" in str(p)

        # 入库检查
        db = DB().init()
        ds = db.conn.execute("SELECT * FROM datasets").fetchone()
        assert ds["source"] == "tess" and ds["target"] == "WASP-12"

        # 第二次：缓存命中，fake 不再被调
        calls = []

        def fail_download(*a, **k):
            calls.append(1)
            raise AssertionError("不应触网")

        monkeypatch.setattr(tess, "_download_lc", fail_download)
        r2 = tess.tess_lightcurve("WASP-12", sector=20)
        assert r2.cache_hit is True and not calls
