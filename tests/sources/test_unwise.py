"""unWISE 源测试：锁定 2026-10-09 实测澄清的三处服务端契约。

1. `bands` 是整数位掩码（1=w1 / 2=w2），传名字会让服务端 int('w') 崩溃→500
2. 响应是 tar.gz 压缩包，必须解包（aria2 型会把它原样存成 .fits）
3. 不支持 w1+w2 合并（bands=3 返回 0 字节）→ 描述符只提供 w1/w2
"""
from __future__ import annotations

import io
import tarfile

import pytest

from myastro.io.sources import unwise


@pytest.mark.cap("source.contract")
class TestCutoutUrl:
    def test_band_is_integer_bitmask(self):
        url = unwise.cutout_url(180.0, 1.1, 300, "w1")
        assert "bands=1" in url and "bands=w1" not in url
        assert "bands=2" in unwise.cutout_url(180.0, 1.1, 300, "w2")

    def test_merged_band_rejected(self):
        with pytest.raises(ValueError, match="合并"):
            unwise.cutout_url(180.0, 1.1, 300, "w1w2")

    def test_unknown_band_rejected(self):
        with pytest.raises(ValueError):
            unwise.cutout_url(180.0, 1.1, 300, "w3")


def _tarball(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, payload in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
    return buf.getvalue()


@pytest.mark.cap("source.contract")
class TestTarballExtraction:
    def _patch_get(self, monkeypatch, payload: bytes, status: int = 200):
        # 退避打桩：这些测试验证的是错误路径，不是重试节奏——
        # 不打桩会让"空响应"测试真等 1+2+4+8=15s（曾占全量 1/3 时长）
        monkeypatch.setattr(unwise, "retry", lambda fn, **kw: fn())

        class _Resp:
            status_code = status
            content = payload

            def raise_for_status(self):
                if status >= 400:
                    raise ConnectionError(f"HTTP {status}")

        monkeypatch.setattr("requests.get", lambda *a, **k: _Resp())

    def test_extracts_fits_members(self, tmp_path, monkeypatch):
        blob = _tarball({
            "unwise-1800p015-w1-img-m.fits": b"FITSIMG",
            "unwise-1800p015-w1-n-m.fits.gz": b"GZ",
            "readme.txt": b"ignore me",
        })
        self._patch_get(monkeypatch, blob)
        paths, meta = unwise._download_unwise(180.0, 1.5, 64, "w1",
                                              tmp_path / "out")
        names = [p.name for p in paths]
        assert names == ["unwise-1800p015-w1-img-m.fits",
                         "unwise-1800p015-w1-n-m.fits.gz"]   # 非 FITS 成员被忽略
        assert all(p.exists() for p in paths)
        assert meta["bands_bitmask"] == 1 and meta["n_files"] == 2
        assert (tmp_path / "out" / "unwise-1800p015-w1-img-m.fits"
                ).read_bytes() == b"FITSIMG"

    def test_empty_response_rejected(self, tmp_path, monkeypatch):
        self._patch_get(monkeypatch, b"")
        with pytest.raises(ConnectionError, match="空响应"):
            unwise._download_unwise(180.0, 1.5, 64, "w1", tmp_path / "out")

    def test_tarball_without_fits_rejected(self, tmp_path, monkeypatch):
        self._patch_get(monkeypatch, _tarball({"a.txt": b"x"}))
        with pytest.raises(ConnectionError, match="无 FITS"):
            unwise._download_unwise(180.0, 1.5, 64, "w1", tmp_path / "out")


@pytest.mark.cap("source.contract")
def test_task_reads_fits_and_registers(env, monkeypatch):
    """任务路径：落盘 → 入库 → meta 记录波段掩码（不触网）。"""
    def fake_download(ra, dec, size, band, dest_dir):
        dest_dir.mkdir(parents=True, exist_ok=True)
        p = dest_dir / f"unwise-{ra:.0f}_{dec}_w1-img-m.fits"
        p.write_bytes(b"FITS")
        return [p], {"ra": ra, "dec": dec, "size": size, "band": band,
                     "bands_bitmask": unwise.BANDS[band], "n_files": 1,
                     "members": [p.name]}

    monkeypatch.setattr(unwise, "_download_unwise", fake_download)
    r = unwise.unwise_cutout(180.0, 1.5, size=64, band="w1")
    assert r.cache_hit is False and len(r.paths) == 1
    assert r.meta["bands_bitmask"] == 1
    assert "unwise_180.0_1.5_64px_w1" in str(r.paths[0])


@pytest.mark.cap("source.registry")
def test_descriptor_offers_only_single_bands():
    """描述符不得再给出服务端无法满足的 w1w2 合并选项。"""
    from myastro.descriptors import REGISTRY

    band = next(f for f in REGISTRY["unwise"].fields if f.name == "band")
    assert tuple(band.choices) == ("w1", "w2")
    assert REGISTRY["unwise"].task == "unwise_cutout"
    assert REGISTRY["unwise"].url_key is None       # 已从 aria2 型改为 python 型


@pytest.mark.cap("source.health")
def test_health_probe_hits_service_endpoint():
    """探测必须打服务端点，而不是域名根（根 200 骗过我们一次）。"""
    from myastro.io.health import PROBES

    url = PROBES["unwise"]
    assert "/cutout_fits?" in url and "bands=1" in url
