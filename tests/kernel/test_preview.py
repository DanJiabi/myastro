"""io.preview：格式嗅探与各格式的结构化预览（内核层）。"""
from __future__ import annotations

import gzip

import pytest


@pytest.mark.cap("manage.integrity")
class TestSniff:
    def test_parquet_by_magic(self, tmp_path):
        import pandas as pd
        f = tmp_path / "data.weird"           # 扩展名骗人也要认内容
        pd.DataFrame({"a": [1]}).to_parquet(f)
        from myastro.io.preview import sniff
        assert sniff(f) == "parquet"

    def test_fits_by_magic_and_gzip_wrapped(self, tmp_path):
        import numpy as np
        from astropy.io import fits
        plain = tmp_path / "img.fits"
        fits.writeto(plain, np.zeros((8, 8)))
        from myastro.io.preview import sniff
        assert sniff(plain) == "fits"
        # legacy-bricks.src 形态：gzip 包裹的 FITS，扩展名是 .src
        packed = tmp_path / "index.src"
        with open(plain, "rb") as fi, gzip.open(packed, "wb") as fo:
            fo.write(fi.read())
        assert sniff(packed) == "fits"

    def test_text_and_unknown(self, tmp_path):
        from myastro.io.preview import sniff
        t = tmp_path / "a.log"
        t.write_text("hello\n")
        assert sniff(t) == "text"
        b = tmp_path / "a.bin"
        b.write_bytes(bytes(range(256)))
        assert sniff(b) in ("unknown", "text")   # 只要求不崩


@pytest.mark.cap("manage.integrity")
class TestParquet:
    def test_doc_sections(self, tmp_path):
        import pandas as pd
        f = tmp_path / "t.parquet"
        pd.DataFrame({"x": [1, 2, None], "y": ["a", "b", "c"]}).to_parquet(f)
        from myastro.io.preview import preview
        doc = preview(f)
        assert doc.kind == "parquet"
        titles = [s.title for s in doc.sections]
        assert "概要" in titles and "schema" in titles and "NaN 占比（前 5）" in titles
        overview = doc.sections[0].lines[0]
        assert "行数：3" in overview and "列数：2" in overview
        head = next(s for s in doc.sections if s.table)
        assert head.table[0] == ["x", "y"] and len(head.table[1]) == 3

    def test_missing_file_raises(self, tmp_path):
        from myastro.io.preview import preview
        with pytest.raises(FileNotFoundError):
            preview(tmp_path / "nope.parquet")


@pytest.mark.cap("manage.integrity")
class TestFits:
    def test_image_header_card_and_stats(self, tmp_path):
        import numpy as np
        from astropy.io import fits
        f = tmp_path / "sci.fits"
        hdr = fits.Header({"TELESCOP": "Palomar 48-inch", "EXPTIME": 30.0})
        fits.writeto(f, np.arange(64, dtype=float).reshape(8, 8), hdr)
        from myastro.io.preview import preview
        doc = preview(f)
        assert doc.kind == "fits-image"
        header = "\n".join(doc.sections[0].lines)
        assert "TELESCOP" in header and "EXPTIME" in header
        assert any("图像统计" in s.title for s in doc.sections)

    def test_table_hdu(self, tmp_path):
        from astropy.io import fits
        cols = [fits.Column(name="brickname", format="8A", array=["0001m002"]),
                fits.Column(name="ra", format="D", array=[1.0])]
        f = tmp_path / "tbl.fits"
        fits.HDUList([fits.PrimaryHDU(),
                      fits.BinTableHDU.from_columns(cols)]).writeto(f)
        from myastro.io.preview import preview
        doc = preview(f)
        assert doc.kind == "fits-table"
        assert any("brickname" in line for s in doc.sections for line in s.lines)

    def test_gzip_wrapped_src(self, tmp_path):
        import numpy as np
        from astropy.io import fits
        plain = tmp_path / "x.fits"
        fits.writeto(plain, np.zeros((4, 4)))
        packed = tmp_path / "bricks.src"
        with open(plain, "rb") as fi, gzip.open(packed, "wb") as fo:
            fo.write(fi.read())
        from myastro.io.preview import preview
        assert preview(packed).kind.startswith("fits")


@pytest.mark.cap("manage.integrity")
def test_text_preview(tmp_path):
    from myastro.io.preview import preview
    f = tmp_path / "a.csv"
    f.write_text("a,b\n1,2\n3,4\n")
    doc = preview(f, lines=2)
    assert doc.kind == "text"
    assert doc.sections[0].lines == ["a,b", "1,2"]
