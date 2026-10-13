"""facade.preview 的 `#id` 账本解析。"""
from __future__ import annotations

import pytest


@pytest.mark.cap("facade.api")
class TestFacadePreview:
    def test_preview_by_dataset_id(self, env):
        import pandas as pd

        import myastro as ma
        from myastro.io.db import DB

        f = env / "data" / "x.parquet"
        f.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"a": [1]}).to_parquet(f)
        db = DB().init()
        cur = db.conn.execute(
            "INSERT INTO datasets(source,target,params_json,cache_key)"
            " VALUES('t','','{}','k')")
        db.conn.execute(
            "INSERT INTO files(dataset_id,path,size,format) VALUES(?,?,1,'parquet')",
            (cur.lastrowid, str(f)))
        db.conn.commit()

        doc = ma.preview(f"#{cur.lastrowid}")
        assert doc["kind"] == "parquet" and doc["path"] == str(f)

    def test_dataset_without_files_is_notfound(self, env):
        import myastro as ma

        with pytest.raises(ma.NotFoundError):
            ma.preview("#999")

    def test_bad_id_is_param_error(self, env):
        import myastro as ma

        with pytest.raises(ma.ParamError):
            ma.preview("#abc")
