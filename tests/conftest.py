"""共享 fixture 与 helper：隔离环境（data/db 指向 tmp，会话清空）。

各测试模块的 `_env(tmp_path, monkeypatch)` 一律转发到 setup_env——
历史上四个文件各抄一份，其中一份还漏了 _dest_dir_cache 清理。


env        —— 干净账本（内核/门面测试）
env_seeded —— 额外含一条 tess/T1 done 种子记录（TUI 面板测试）
"""

import pathlib

import pytest

from myastro.io import jobs
from myastro.io.db import DB


def setup_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MYASTRO_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("MYASTRO_DB", str(tmp_path / "astro.db"))
    jobs._DEFAULT_SESSION.clear()
    jobs._dest_dir_cache.clear()
    DB().init()


def teardown_env():
    jobs._DEFAULT_SESSION.clear()
    jobs._dest_dir_cache.clear()


@pytest.fixture
def env(tmp_path, monkeypatch):
    setup_env(tmp_path, monkeypatch)
    yield tmp_path
    teardown_env()


@pytest.fixture
def env_seeded(tmp_path, monkeypatch):
    setup_env(tmp_path, monkeypatch)
    p = tmp_path / "data" / "tess" / "T1" / "lc.parquet"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"DATA")
    db = DB().init()
    cur = db.conn.execute(
        "INSERT INTO datasets(source,target,params_json,cache_key)"
        " VALUES('tess','T1','{}','k')"
    )
    db.conn.execute(
        "INSERT INTO files(dataset_id,path,size,format) VALUES(?,?,4,'parquet')",
        (cur.lastrowid, str(p)),
    )
    db.conn.execute(
        "INSERT INTO jobs(spec_json,executor,status,dataset_id)"
        " VALUES('{}','python','done',?)",
        (cur.lastrowid,),
    )
    db.conn.commit()
    yield tmp_path
    teardown_env()

# ── 层标记：按目录自动挂 unit/kernel/sources/facade/ui/guards ──
# 用于快通道 `pytest -m "unit or guards"`（见 docs/zh/dev/testing.md §5）
LAYERS = ("unit", "kernel", "sources", "facade", "ui", "cli", "guards")


def pytest_addoption(parser):
    parser.addoption("--cap", action="store", default=None, metavar="ID",
                     help="只运行指定能力（cap 标记）的测试，如 --cap acquire.retry")


def pytest_collection_modifyitems(config, items):
    # 1) 按目录挂层标记
    for item in items:
        parts = pathlib.Path(str(item.fspath)).parts
        for layer in LAYERS:
            if layer in parts:
                item.add_marker(getattr(pytest.mark, layer))
                break
    # 2) --cap 过滤（-m 只能匹配标记名，不能匹配标记参数）
    want = config.getoption("--cap")
    if want:
        keep, drop = [], []
        for item in items:
            caps = [m.args[0] for m in item.iter_markers("cap") if m.args]
            (keep if want in caps else drop).append(item)
        config.hook.pytest_deselected(items=drop)
        items[:] = keep
