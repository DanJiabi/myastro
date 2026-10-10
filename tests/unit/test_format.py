"""纯逻辑单元：无 db / 网络 / TUI。

（测试分层重组迁移；断言未改动。）
"""
import pytest


@pytest.mark.cap("present.tui")
def test_fmt_size_adaptive():
    from myastro.io.top import fmt_size

    assert fmt_size(0) == "0 B"
    assert fmt_size(512) == "512 B"
    assert fmt_size(62000) == "62.0 KB"
    assert fmt_size(22213440) == "22.2 MB"
    assert fmt_size(3.5e9) == "3.5 GB"
    assert fmt_size(2.7e12) == "2.7 TB"
    assert fmt_size(None) == "0 B"
