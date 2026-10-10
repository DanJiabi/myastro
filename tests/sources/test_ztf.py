"""数据源契约：只打桩网络层，描述符/落盘/入库走真实路径。

（测试分层重组迁移；断言未改动。）
"""

import pytest

from myastro.io.sources import ztf


class TestZtfUrl:
    @pytest.mark.cap("source.contract")
    def test_url_pattern(self):
        url = ztf.ztf_sci_url("20191214561238", 673, "zg", 1, 1)
        assert url == (
            "https://irsa.ipac.caltech.edu/ibe/data/ztf/products/"
            "sci/2019/1214/561238/"
            "ztf_20191214561238_000673_zg_c01_o_q1_sciimg.fits"
        )

    @pytest.mark.cap("source.contract")
    def test_frame_name(self):
        n = ztf.frame_name("20191214561238", 673, "zg", 1, 1)
        assert n == "ztf_20191214561238_000673_zg_c01_o_q1_sciimg.fits"


class TestZtfFrameCache:
    @pytest.mark.cap("source.contract")
    def test_frame_cache_hit_no_new_job(self, env):
        """已入库且文件在盘 → ztf_frame 返回 cache_hit，不建新 job。"""
        from myastro.io.db import DB

        db = DB().init()
        name = ztf.frame_name("20200219403889", 673, "zg", 1, 1)
        f = env / "data" / "ztf" / "f000673" / name
        f.parent.mkdir(parents=True)
        f.write_bytes(b"FITS")
        from myastro.io.core import cache_key

        key = cache_key("ztf", {"name": name, "field": 673, "filtercode": "zg"})
        cur = db.conn.execute(
            "INSERT INTO datasets(source,target,params_json,cache_key)"
            " VALUES('ztf','t','{}',?)",
            (key,),
        )
        db.conn.execute(
            "INSERT INTO files(dataset_id,path,size,format) VALUES(?,?,4,'fits')",
            (cur.lastrowid, str(f)),
        )
        db.conn.commit()
        r = ztf.ztf_frame("20200219403889", 673, "zg", 1, 1)
        assert r.cache_hit is True
        n = db.conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"]
        assert n == 0


@pytest.mark.cap("source.contract")
def test_ztf_lc_descriptor_and_mock(env, monkeypatch):
    import pandas as pd

    import myastro.io.sources.ztf_lc as zl

    monkeypatch.setattr(
        zl,
        "_download_ztflc",
        lambda ra, dec, r: (
            pd.DataFrame({"oid": [1, 1], "mag": [15.0, 15.1], "hjd": [1.0, 2.0]}),
            {"n_rows": 2, "n_sources": 1},
        ),
    )
    from myastro.io import jobs

    jobs._DEFAULT_SESSION.clear()
    import myastro as ma

    r = ma.fetch("ztf-lc", ra=97.14, dec=30.49)
    assert r.paths[0].suffix == ".parquet" and r.meta["n_sources"] == 1
