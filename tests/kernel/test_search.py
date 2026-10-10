"""内核：真 sqlite（tmp），网络打桩；账本/作业/索引/健康/调度/巡检/检索。

（测试分层重组迁移；断言未改动。）
"""
import pytest


@pytest.mark.cap("manage.search")
def test_search_by_target_and_near(env, monkeypatch):
    monkeypatch.setenv("MYASTRO_DATA", str(env / "data"))
    monkeypatch.setenv("MYASTRO_DB", str(env / "astro.db"))
    import json as _json

    from myastro.io.db import DB
    from myastro.io.search import search

    db = DB().init()
    db.conn.execute(
        "INSERT INTO datasets(source,target,params_json,cache_key)"
        " VALUES('tess','WASP-12',?,'k1')",
        (_json.dumps({"target": "WASP-12", "sector": 20}),),
    )
    db.conn.execute(
        # ra/dec 由入库时解析写入（io/coords.py）；直插 SQL 要自行给出
        "INSERT INTO datasets(source,target,params_json,cache_key,ra,dec)"
        " VALUES('gaia',NULL,?,'k2',150.0,2.0)",
        (_json.dumps({"ra": 150.0, "dec": 2.0}),),
    )
    db.conn.commit()
    assert len(search(target="WASP")) == 1
    assert len(search(near=(150.001, 2.001), radius_deg=0.1)) == 1
    assert len(search(near=(0.0, 50.0))) == 0


@pytest.mark.cap("manage.coverage")
def test_coverage(env, monkeypatch):
    import pandas as pd

    import myastro.io.index as idx

    _mk(env, monkeypatch)  # tractor-0001x002.fits 在库
    fake = pd.DataFrame(
        {"brickname": ["0001x002", "0001x005"], "ra": [0.1, 0.2], "dec": [0.0, 0.0]}
    )
    monkeypatch.setattr(idx, "load_index", lambda n: fake)
    from myastro.io.search import coverage

    r = coverage("legacy-bricks")
    assert r == {"index": "legacy-bricks", "total": 2, "local": 1, "pct": 50.0}


def _mk(env, monkeypatch, content=b"DATA", sha=None):
    monkeypatch.setenv("MYASTRO_DATA", str(env / "data"))
    monkeypatch.setenv("MYASTRO_DB", str(env / "astro.db"))
    from myastro.io import jobs
    from myastro.io.db import DB

    jobs._DEFAULT_SESSION.clear()
    db = DB().init()
    f = env / "data" / "legacy" / "tractor-0001x002.fits"
    f.parent.mkdir(parents=True)
    f.write_bytes(content)
    cur = db.conn.execute(
        "INSERT INTO datasets(source,target,params_json,cache_key)"
        " VALUES('legacy','t','{}','kc1')"
    )
    db.conn.execute(
        "INSERT INTO files(dataset_id,path,size,sha256,format) VALUES(?,?,?,?,?)",
        (cur.lastrowid, str(f), len(content), sha, "fits"),
    )
    db.conn.commit()
    return db, f


@pytest.mark.cap("manage.search")
class TestConeSearch:
    """精确圆锥：SQL 包围盒粗筛 + haversine 精判（旧实现是矩形，会误命中盒角）。"""

    def _seed(self, env, rows):
        from myastro.io.db import DB
        db = DB().init()
        for i, (ra, dec) in enumerate(rows):
            db.conn.execute(
                "INSERT INTO datasets(source,target,params_json,cache_key,"
                " ra, dec) VALUES('t','x','{}',?,?,?)", (f"k{i}", ra, dec))
        db.conn.commit()
        return db

    def test_box_corner_excluded(self, env):
        """对角方向上的点落在包围盒内但在圆锥外——必须剔除。"""
        # 半径 1°、中心 (10, 0)：点 (10.8, 0.8) 在包围盒内（Δra/Δdec≤1）
        # 但角距 √(0.8²+0.8²)=1.13°>1° —— 旧的矩形判定会误命中
        self._seed(env, [(10.0, 0.0), (10.8, 0.8)])
        from myastro.io.search import search
        hits = search(near=(10.0, 0.0), radius_deg=1.0)
        assert [h["sep_deg"] for h in hits] == [0.0]      # 只留中心那颗

    def test_sorted_by_separation(self, env):
        self._seed(env, [(10.0, 0.0), (10.3, 0.0), (10.1, 0.0)])
        from myastro.io.search import search
        hits = search(near=(10.0, 0.0), radius_deg=1.0)
        seps = [h["sep_deg"] for h in hits]
        assert seps == sorted(seps) and seps[0] == 0.0

    def test_ra_wraparound(self, env):
        """跨 0° 赤经：359.95 与 0.05 相距 0.1°，不能被当成 359.9°。"""
        self._seed(env, [(359.95, 0.0)])
        from myastro.io.search import search
        assert len(search(near=(0.05, 0.0), radius_deg=0.2)) == 1
        assert search(near=(0.05, 0.0), radius_deg=0.05) == []

    def test_rows_without_coords_excluded(self, env):
        from myastro.io.db import DB
        db = DB().init()
        db.conn.execute(
            "INSERT INTO datasets(source,target,params_json,cache_key)"
            " VALUES('mpc','Ceres','{}','nocoord')")
        db.conn.commit()
        from myastro.io.search import search
        assert search(near=(10.0, 0.0), radius_deg=5.0) == []

    def test_registration_resolves_and_stores_coords(self, env):
        """入库即解析坐标（不必等查询时）——含 meta 路径（tess 形态）。"""
        from myastro.io import jobs
        from myastro.io.db import DB

        def fn(ctx):
            p = ctx.dest_dir / "lc.parquet"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"X")
            return jobs.FetchResult(paths=[p], dataset_id=-1,
                                    meta={"target": "WASP-12",
                                          "ra": 97.6367, "dec": 29.6723})

        jobs.fetch(jobs.JobSpec(source="tess", params={"target": "WASP-12"},
                                executor="python", fn=fn))
        row = DB().init().conn.execute(
            "SELECT ra, dec FROM datasets WHERE source='tess'").fetchone()
        assert row["ra"] == pytest.approx(97.6367)
        assert row["dec"] == pytest.approx(29.6723)


@pytest.mark.cap("manage.search")
class TestQueryBoundaries:
    """越界参数必须显式报错——静默返回空结果等于"看起来查过了其实没查"。"""

    def _seed(self, env, n=8):
        from myastro.io.db import DB
        db = DB().init()
        for i in range(n):
            db.conn.execute(
                "INSERT INTO datasets(source,target,params_json,cache_key)"
                f" VALUES('s','t{i}','{{}}','kb{i}')")
        db.conn.commit()

    @pytest.mark.parametrize("kwargs,why", [
        ({"near": (150.0, 2.0), "radius_deg": -1}, "负半径"),
        ({"near": (150.0, 2.0), "radius_deg": 0}, "零半径"),
        ({"near": (150.0, 2.0), "radius_deg": 400}, "半径超过天球"),
        ({"near": (150.0, 95.0)}, "dec 越界"),
        ({"near": (float("nan"), 2.0)}, "nan"),
        ({"limit": 0}, "limit 为 0"),
        ({"limit": -1}, "limit 为负（切片语义最隐蔽）"),
        ({"since": "乱码"}, "日期格式"),
        ({"until": "2026/01/01"}, "日期分隔符"),
    ])
    def test_out_of_range_rejected(self, env, kwargs, why):
        self._seed(env)
        from myastro.io.search import search
        with pytest.raises(ValueError):
            search(**kwargs)

    def test_negative_limit_is_not_a_slice(self, env):
        """曾经的 bug：limit=-1 → out[:-1] → 返回"除最后一条外"的全部。"""
        self._seed(env, 8)
        from myastro.io.search import search
        with pytest.raises(ValueError):
            search(limit=-1)

    @pytest.mark.parametrize("kwargs", [
        {"limit": 3},
        {"since": "2020-01-01"},
        {"until": "2030-01-01 12:00:00"},
        {"near": (150.0, 2.0), "radius_deg": 0.5},
    ])
    def test_valid_parameters_still_work(self, env, kwargs):
        self._seed(env, 3)
        from myastro.io.search import search
        assert isinstance(search(**kwargs), list)
