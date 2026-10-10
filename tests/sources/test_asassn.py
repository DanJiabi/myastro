"""数据源契约：只打桩网络层，描述符/落盘/入库走真实路径。

（测试分层重组迁移；断言未改动。）
"""

import pandas as pd
import pytest

from myastro.io.db import DB
from myastro.io.sources import asassn


class TestAsassn:
    @pytest.mark.cap("source.dormant")
    def test_radius_validation(self, env):
        DB().init()
        try:
            asassn.asassn_lightcurve(10, 10, 120)
            assert False
        except ValueError:
            pass

    @pytest.mark.cap("source.dormant")
    def test_fn_writes_parquet(self, env, monkeypatch):

        def fake(ra, dec, radius):
            df = pd.DataFrame({"jd": [2459000.5], "mag": [12.3]})
            return df, {"ra": ra, "dec": dec, "radius_arcmin": radius, "n_rows": 1}

        monkeypatch.setattr(asassn, "_download_asassn", fake)
        r = asassn.asassn_lightcurve(339.2729, 58.4153)
        assert r.paths[0].suffix == ".parquet"
        assert r.cache_hit is False
