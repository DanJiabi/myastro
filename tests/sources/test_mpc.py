"""数据源契约：只打桩网络层，描述符/落盘/入库走真实路径。

（测试分层重组迁移；断言未改动。）
"""
import pytest


@pytest.mark.cap("source.contract")
def test_mpc_registers_parquet(env, monkeypatch):
    import pandas as pd

    import myastro.io.sources.mpc as m

    monkeypatch.setattr(
        m,
        "_download_mpc",
        lambda t, n, s: (pd.DataFrame({"RA": [1.0]}), {"target": t, "n_rows": 1}),
    )
    from myastro.io import jobs

    jobs._DEFAULT_SESSION.clear()
    r = m.mpc_ephemeris("Ceres", number=3)
    # 文件名编码所有影响内容的参数（number/step_days）——
    # 否则不同参数共用同一文件，先到者的内容被覆盖、账本出现幽灵数据集
    assert r.paths[0].name == "eph_Ceres_n3_s1.0d.parquet"


@pytest.mark.cap("source.contract")
def test_mpc_different_params_do_not_collide(env, monkeypatch):
    """number 不同的两次取数 → 两个文件、两个数据集都带文件链接。

    真实事故（账本 #19/#39）：文件名只含 target，number=5 与 number=10 共用
    一个路径，后到者覆盖内容，先到者成为"有 dataset 无文件"的幽灵。
    """
    import pandas as pd

    import myastro.io.sources.mpc as m

    monkeypatch.setattr(
        m, "_download_mpc",
        lambda t, n, s: (pd.DataFrame({"RA": [1.0] * n}), {"target": t, "n_rows": n}),
    )
    from myastro.io import jobs

    jobs._DEFAULT_SESSION.clear()
    r5 = m.mpc_ephemeris("Ceres", number=5)
    jobs._DEFAULT_SESSION.clear()
    r10 = m.mpc_ephemeris("Ceres", number=10)

    assert r5.paths[0] != r10.paths[0], "不同参数必须落到不同文件"
    assert r5.paths[0].exists() and r10.paths[0].exists()

    import os
    import sqlite3
    db = sqlite3.connect(os.environ["MYASTRO_DB"])
    db.row_factory = sqlite3.Row
    n5 = db.execute("SELECT count(*) c FROM files WHERE dataset_id=?",
                    (r5.dataset_id,)).fetchone()["c"]
    n10 = db.execute("SELECT count(*) c FROM files WHERE dataset_id=?",
                     (r10.dataset_id,)).fetchone()["c"]
    assert n5 == 1 and n10 == 1, f"两个数据集都必须有文件链接: {n5}/{n10}"
