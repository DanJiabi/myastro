"""数据源契约：只打桩网络层，描述符/落盘/入库走真实路径。

（测试分层重组迁移；断言未改动。）
"""

import pytest


class TestManifest:
    @pytest.mark.cap("acquire.manifest")
    def test_parse_and_submit(self, env):
        m = env / "m.yaml"
        m.write_text("""
    source: legacy-surveys
    dest_dir: legacy/w44
    files:
      - https://example.com/a.fits
      - url: https://example.com/b.fits
        out: renamed.fits
    """)
        from myastro.io.manifest import parse_manifest

        specs = parse_manifest(m)
        assert len(specs) == 2
        assert specs[0].dest.endswith("legacy/w44/a.fits")
        assert specs[1].dest.endswith("renamed.fits")

    @pytest.mark.cap("acquire.manifest")
    def test_unknown_field_rejected(self, env):
        m = env / "m.yaml"
        m.write_text("source: x\nbogus: 1\nfiles: []\n")
        from myastro.io.manifest import parse_manifest

        with pytest.raises(ValueError, match="未知字段"):
            parse_manifest(m)
