"""tools/patch_splash.py: the pixel layout and PNG round trip offline; with HX_STOMP_HXF set, export then apply on
the stock firmware gives back the stock archive byte for byte."""
import os
import random

import pytest

import patch_amp as pa
import patch_splash as ps


def test_encode_decode_round_trip():
    rng = random.Random(1)
    px = bytes(rng.randrange(256) for _ in range(ps.W * ps.H * 2))
    assert ps.encode(ps.decode(px)) == px


def test_png_round_trip(tmp_path):
    rng = random.Random(2)
    rows = [[tuple(rng.randrange(256) for _ in range(3)) for _ in range(ps.W)] for _ in range(ps.H)]
    ps.write_png(tmp_path / "s.png", rows)
    assert ps.read_png(tmp_path / "s.png") == (ps.W, ps.H, rows)


def test_layout_column_major_from_bottom():
    rows = [[(0, 0, 0)] * ps.W for _ in range(ps.H)]
    rows[0][1] = (255, 0, 0)
    px = ps.encode(rows)
    assert px[2 * (1 * ps.H + ps.H - 1):][:2] == b"\x00\xf8"


@pytest.mark.firmware
def test_stock_round_trip(tmp_path):
    stock = os.environ.get("HX_STOMP_HXF")
    if not stock:
        pytest.skip("HX_STOMP_HXF is not set")
    data, _ = pa.load_l6ia_from_any(stock)
    e8, (off, ln) = ps.splash_entries(data)
    ps.write_png(tmp_path / "stock.png", ps.decode(e8[off:off + ln]))
    assert ps.patch_splash(data, tmp_path / "stock.png", log=lambda *_: None) == data
