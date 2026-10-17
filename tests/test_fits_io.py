"""test_fits_io.py —— FITS 读写引擎测试（往返一致性 + 手搓标准用例）"""
import gzip

import numpy as np
import pytest

from core.fits_io import (HDU, is_fits, read_fits, read_primary_data,
                          read_table, write_fits_image, write_fits_table,
                          _fmt_card, BLOCK)


def _handcraft(cards, data=b""):
    """手搓 FITS 字节流：卡片列表（不含 END）+ 数据区，均补齐 2880 块"""
    raw = "".join(c.ljust(80) for c in cards) + "END".ljust(80)
    raw = raw + " " * ((-len(raw)) % BLOCK)
    return raw.encode("latin-1") + data + b"\x00" * ((-len(data)) % BLOCK)


# ---------- 图像往返 ----------
@pytest.mark.parametrize("dtype", [np.uint8, np.int16, np.int32, np.int64,
                                   np.float32, np.float64])
def test_image_roundtrip(tmp_path, dtype):
    rng = np.random.default_rng(7)
    img = (rng.uniform(0, 1000, (17, 31)) if np.dtype(dtype).kind == "f"
           else rng.integers(0, 100, (17, 31))).astype(dtype)
    p = tmp_path / "img.fits"
    write_fits_image(str(p), img, {"OBJECT": "M31", "EXPTIME": 60.0})
    hdus = read_fits(str(p))
    assert len(hdus) == 1
    data = hdus[0].data
    assert data.dtype == dtype
    np.testing.assert_array_equal(data, img)
    h = hdus[0].header
    assert h["OBJECT"] == "M31" and h["EXPTIME"] == 60.0
    assert h["NAXIS"] == 2 and h["NAXIS1"] == 31 and h["NAXIS2"] == 17


def test_image_non_native_type_promotes_to_float64(tmp_path):
    img = np.array([[1, 2], [3, 4]], dtype=np.bool_)
    p = tmp_path / "bool.fits"
    write_fits_image(str(p), img)
    out = read_primary_data(str(p))
    assert out.dtype == np.float64
    np.testing.assert_array_equal(out, img.astype(np.float64))


def test_extra_header_conflict_raises(tmp_path):
    with pytest.raises(ValueError):
        write_fits_image(str(tmp_path / "x.fits"), np.zeros((4, 4)),
                         {"NAXIS": 3})


# ---------- 表往返（多 HDU） ----------
def test_bintable_roundtrip(tmp_path):
    cols = {
        "name": ["HD-209458", "WASP-12", "Kepler-186"],
        "rv_ms": np.array([-14.32, 55.9, 3.141]),
        "epoch": np.array([2454000, 2454100, 2454300], dtype=np.int64),
        "flag": np.array([True, False, True], dtype=bool),
    }
    p = tmp_path / "tab.fits"
    write_fits_table(str(p), cols, {"OBSERVAT": "Xinglong"})
    hdus = read_fits(str(p))
    assert len(hdus) == 2                       # 空主 HDU + BINTABLE
    assert hdus[0].data is None and hdus[0].header["NAXIS"] == 0
    tb = hdus[1]
    assert tb.name == "TABLE" and tb.header["OBSERVAT"] == "Xinglong"
    assert list(tb.columns) == list(cols)
    np.testing.assert_allclose(tb.columns["rv_ms"], cols["rv_ms"], atol=1e-4)
    assert tb.columns["epoch"].dtype == np.int64
    np.testing.assert_array_equal(tb.columns["epoch"], cols["epoch"])
    assert list(tb.columns["flag"]) == [True, False, True]
    assert [str(s) for s in tb.columns["name"]] == cols["name"]
    # 便捷接口
    rt = read_table(str(p))
    np.testing.assert_allclose(rt["rv_ms"], cols["rv_ms"], atol=1e-4)


# ---------- 标准格式特性（手搓字节流） ----------
def test_unsigned_int16_via_bzero(tmp_path):
    vals = np.array([100, 40000, 5, 65535, 32768, 0], dtype=np.uint16)
    stored = (vals.astype(np.int64) - 32768).astype(">i2")   # BZERO=32768
    cards = [
        _fmt_card("SIMPLE", True), _fmt_card("BITPIX", 16),
        _fmt_card("NAXIS", 2), _fmt_card("NAXIS1", 3), _fmt_card("NAXIS2", 2),
        _fmt_card("BZERO", 32768), _fmt_card("BSCALE", 1),
    ]
    p = tmp_path / "u16.fits"
    p.write_bytes(_handcraft(cards, stored.tobytes()))
    data = read_primary_data(str(p))
    assert data.dtype == np.uint16
    np.testing.assert_array_equal(data, vals.reshape(2, 3))


def test_bscale_float_scaling(tmp_path):
    stored = np.array([[1, 2], [3, 4]], dtype=">i2")
    cards = [
        _fmt_card("SIMPLE", True), _fmt_card("BITPIX", 16),
        _fmt_card("NAXIS", 2), _fmt_card("NAXIS1", 2), _fmt_card("NAXIS2", 2),
        _fmt_card("BSCALE", 0.5), _fmt_card("BZERO", 10.0),
    ]
    p = tmp_path / "scaled.fits"
    p.write_bytes(_handcraft(cards, stored.tobytes()))
    np.testing.assert_allclose(read_primary_data(str(p)),
                               stored.astype(float) * 0.5 + 10.0)


def test_ascii_table(tmp_path):
    # 真实 FITS 首个 HDU 必须是主 HDU：手搓「空主 HDU + ASCII 表扩展」
    pri = _handcraft([_fmt_card("SIMPLE", True), _fmt_card("BITPIX", 8),
                      _fmt_card("NAXIS", 0)])
    cards = [
        "XTENSION= 'TABLE   '", _fmt_card("BITPIX", 8),
        _fmt_card("NAXIS", 2), _fmt_card("NAXIS1", 20), _fmt_card("NAXIS2", 2),
        _fmt_card("TFIELDS", 2),
        _fmt_card("TTYPE1", "name"), _fmt_card("TFORM1", "A6"), _fmt_card("TBCOL1", 1),
        _fmt_card("TTYPE2", "flux"), _fmt_card("TFORM2", "E10.3"), _fmt_card("TBCOL2", 9),
    ]
    data = ("Sun     1.000E+00    " + "Vega    4.500E+01    ").encode("latin-1")
    p = tmp_path / "ascii.fits"
    p.write_bytes(pri + _handcraft(cards, data))
    hdus = read_fits(str(p))
    assert len(hdus) == 2
    cols = hdus[1].columns
    assert cols["name"][0] == "Sun" and cols["name"][1] == "Vega"
    np.testing.assert_allclose(cols["flux"], [1.0, 45.0])


def test_continue_long_string(tmp_path):
    cards = [
        _fmt_card("SIMPLE", True), _fmt_card("BITPIX", 8), _fmt_card("NAXIS", 0),
        "LONGSTR = 'the quick brown &'",
        "CONTINUE  'fox jumps over'",
    ]
    p = tmp_path / "long.fits"
    p.write_bytes(_handcraft(cards))
    h = read_fits(str(p))[0].header
    assert h["LONGSTR"] == "the quick brown fox jumps over"


def test_gzip_fits(tmp_path):
    img = np.arange(12, dtype=np.float32).reshape(3, 4)
    src = tmp_path / "g.fits"
    write_fits_image(str(src), img)
    gz = tmp_path / "g.fits.gz"
    with open(str(src), "rb") as f_in, gzip.open(str(gz), "wb") as f_out:
        f_out.write(f_in.read())
    np.testing.assert_array_equal(read_primary_data(str(gz)), img)
    assert is_fits(str(gz)) and not is_fits(str(tmp_path))


def test_invalid_file_raises(tmp_path):
    p = tmp_path / "bad.fits"
    p.write_bytes(b"NOTAFITS" * 360)
    with pytest.raises(ValueError):
        read_fits(str(p))
    assert not is_fits(str(p))


def test_oversized_grid_rejected(tmp_path):
    """构造 NAXIS1=3 但 TFORM 总宽 4 的损坏表 → ValueError"""
    cards = [
        "XTENSION= 'BINTABLE'", _fmt_card("BITPIX", 8),
        _fmt_card("NAXIS", 2), _fmt_card("NAXIS1", 3), _fmt_card("NAXIS2", 2),
        _fmt_card("TFIELDS", 1), _fmt_card("TTYPE1", "x"), _fmt_card("TFORM1", "E"),
    ]
    data = b"\x00" * 8
    p = tmp_path / "bad_tab.fits"
    p.write_bytes(_handcraft(cards, data))
    with pytest.raises(ValueError):
        read_fits(str(p))