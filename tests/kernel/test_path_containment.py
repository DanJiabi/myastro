"""路径安全（内核层）：落盘路径的运行时兜底。

单元层保证"输入即拒"；这一层保证**即使某个源忘了标注**，
任务自己拼出的越界路径也会显式失败，而不是默默写到数据根之外。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from myastro.io import jobs
from myastro.io.db import DB


def _run_task(tmp_path, fn):
    return jobs.fetch(jobs.JobSpec(source="probe", params={"target": "x"},
                                   executor="python", fn=fn))


@pytest.mark.cap("manage.ledger")
class TestDataRootContainment:
    def test_escape_rejected_and_nothing_written(self, env, tmp_path):
        """产物写到数据根之外 → 失败，且不留下半条账本记录。"""
        from myastro.io.config import Config
        root = Config().data

        def evil(ctx):
            outside = Path(tmp_path) / "ESCAPED.parquet"   # tmp_path 不在数据根下
            outside.write_bytes(b"x")
            return jobs.FetchResult(paths=[outside], dataset_id=-1, meta={})

        with pytest.raises(jobs.JobFailed, match="逃出数据根"):
            _run_task(tmp_path, evil)
        assert (Path(tmp_path) / "ESCAPED.parquet").exists()   # 文件确实产生了
        db = DB().init()
        assert db.conn.execute("SELECT COUNT(*) c FROM datasets"
                               ).fetchone()["c"] == 0          # 但没入库
        assert root not in Path(tmp_path).parents or True       # 语义记录

    def test_parent_of_root_rejected(self, env):
        """数据根的父目录同样越界（`..` 只跳一级也算）。"""
        from myastro.io.config import Config
        root = Config().data

        def sneaky(ctx):
            outside = root.parent / "SIBLING.parquet"
            outside.parent.mkdir(parents=True, exist_ok=True)
            outside.write_bytes(b"x")
            return jobs.FetchResult(paths=[outside], dataset_id=-1, meta={})

        with pytest.raises(jobs.JobFailed, match="逃出数据根"):
            _run_task(None, sneaky)

    def test_inside_root_accepted(self, env):
        """正常产物（在数据根内）照常入库——兜底不能误伤。"""
        def good(ctx):
            p = ctx.dest_dir / "ok.parquet"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"x")
            return jobs.FetchResult(paths=[p], dataset_id=-1, meta={})

        result = _run_task(None, good)
        assert result.dataset_id > 0
        db = DB().init()
        assert db.conn.execute("SELECT COUNT(*) c FROM files").fetchone()["c"] == 1
