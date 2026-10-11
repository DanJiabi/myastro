"""统一 parquet 落盘（core.write_parquet）。

**为什么不能用 `df.to_parquet` / `Table.from_pandas`**：实测（2026-10）全新数据根下
连续 `fetch ztf-lc` → `fetch ztf-meta`，第二个作业在**工作线程**里写 parquet 时
100% `SIGSEGV`（12/12），崩溃帧为 `pandas/.../string_.py: __arrow_array__`
← `pyarrow.pandas_compat.convert_column`。同序列在主线程里跑不崩（0/3），
即"非主线程 + pandas→arrow 转换"共同触发。故写入改为**逐列用纯 Python 值构造**。
"""
from __future__ import annotations

import pandas as pd
import pyarrow.parquet as pq
import pytest

from myastro.io.core import write_parquet


@pytest.mark.cap("manage.ledger")
class TestWriteParquet:
    def test_round_trip_values_and_dtypes(self, tmp_path):
        df = pd.DataFrame({
            "ra": [1.5, None], "n": [1, 2], "ok": [True, False],
            "name": pd.Series([b"NGC1234", None], dtype=object),
            "t": pd.to_datetime(["2020-01-01", None]),
        })
        path = tmp_path / "v.parquet"
        write_parquet(df, path)
        back = pd.read_parquet(path)
        assert back["ra"].tolist()[0] == 1.5 and pd.isna(back["ra"].iloc[1])
        assert back["n"].tolist() == [1, 2]
        assert back["ok"].tolist() == [True, False]
        assert back["name"].tolist()[0] == "NGC1234"        # bytes → 可读字符串
        assert pd.isna(back["name"].iloc[1])                # 缺失仍是缺失

    def test_empty_frame_keeps_dtypes(self, tmp_path):
        """空表是真实场景（ibe 检索无命中），**不能退化成 null 类型**。

        这正是"逐列构造 + 显式类型"要守住的东西：直接用
        `pa.array([], from_pandas=True)` 会得到 null 类型，读回来列就废了。
        """
        df = pd.DataFrame({"ra": pd.Series([], dtype="float64"),
                           "n": pd.Series([], dtype="int64"),
                           "name": pd.Series([], dtype=object)})
        path = tmp_path / "e.parquet"
        write_parquet(df, path)
        schema = pq.read_schema(path)
        assert str(schema.field("ra").type) == "double"
        assert str(schema.field("n").type) == "int64"
        assert str(schema.field("name").type) == "string"
        assert len(pd.read_parquet(path)) == 0

    def test_mixed_object_column_becomes_string(self, tmp_path):
        """混合类型 object 列统一转字符串。

        不能交给 arrow 推断：它按首个非空值定型，之后遇到别的类型就抛
        `ArrowTypeError: Expected bytes, got a 'int' object`（实测）。
        """
        write_parquet(pd.DataFrame({"mix": pd.Series(["a", 1, None], dtype=object)}),
                      tmp_path / "m.parquet")
        assert pd.read_parquet(tmp_path / "m.parquet")["mix"].tolist()[:2] == ["a", "1"]

    def test_broken_utf8_does_not_raise(self, tmp_path):
        write_parquet(pd.DataFrame({"s": pd.Series([b"\xff\xfe"], dtype=object)}),
                      tmp_path / "b.parquet")
        assert len(pd.read_parquet(tmp_path / "b.parquet")) == 1

    def test_does_not_use_pandas_arrow_conversion(self, tmp_path, monkeypatch):
        """**守卫**：必须绕开 pandas 的 `__arrow_array__` 路径（崩溃就在那里）。

        变异验证：改回 `Table.from_pandas` / `df.to_parquet` → 本测试立刻红。
        """
        def boom(self, *a, **k):
            raise AssertionError("不应走 pandas 的 __arrow_array__ 转换路径")

        monkeypatch.setattr(pd.arrays.StringArray, "__arrow_array__", boom,
                            raising=False)
        write_parquet(pd.DataFrame({"s": pd.Series(["a", None], dtype="string")}),
                      tmp_path / "guard.parquet")
        assert pd.read_parquet(tmp_path / "guard.parquet")["s"].tolist()[0] == "a"

    def test_index_is_not_written(self, tmp_path):
        write_parquet(pd.DataFrame({"v": [1, 2]}, index=["x", "y"]), tmp_path / "n.parquet")
        assert "index" not in pd.read_parquet(tmp_path / "n.parquet").columns

    def test_no_temp_file_left_behind(self, tmp_path):
        write_parquet(pd.DataFrame({"v": [1]}), tmp_path / "a.parquet")
        assert not list(tmp_path.glob("*.tmp"))

    def test_concurrent_writes_do_not_interfere(self, tmp_path):
        import threading

        errors = []

        def work(i):
            try:
                write_parquet(pd.DataFrame({"v": [i] * 50}), tmp_path / f"c{i}.parquet")
            except Exception as e:                       # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=work, args=(i,)) for i in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        assert not errors, errors
        for i in range(6):
            assert pd.read_parquet(tmp_path / f"c{i}.parquet")["v"].iloc[0] == i
