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


@pytest.mark.cap("source.contract")
def test_service_unreachable_gives_concise_actionable_error(env, monkeypatch):
    """服务不可达时给出可执行的说明，而不是几十行 urllib3 重试栈。

    背景：pyasassn 的 SkyPatrolClient 构造函数就会请求服务端 schema，
    因此"构造失败"等价于"服务不可达"。该服务 2026-10 实测拒连
    （asassn-lb01.ifa.hawaii.edu:9006），`myastro health asassn` 也报 unreachable。
    """
    import sys
    import types

    fake = types.ModuleType("pyasassn.client")

    class SkyPatrolClient:
        def __init__(self, *a, **k):
            raise ConnectionError(
                "HTTPConnectionPool(host='asassn-lb01.ifa.hawaii.edu', port=9006): "
                "Max retries exceeded ... (一堆 urllib3 细节)")

    fake.SkyPatrolClient = SkyPatrolClient
    pkg = types.ModuleType("pyasassn")
    pkg.client = fake
    monkeypatch.setitem(sys.modules, "pyasassn", pkg)
    monkeypatch.setitem(sys.modules, "pyasassn.client", fake)

    from myastro.io.sources.asassn import _download_asassn
    with pytest.raises(ConnectionError) as e:
        _download_asassn(270.0, -30.0, 1.0)
    msg = str(e.value)
    assert "ASAS-SN Sky Patrol v2 服务不可达" in msg
    assert "myastro health asassn" in msg          # 给出下一步动作
    assert "urllib3" not in msg                    # 不再把原始栈丢给用户
