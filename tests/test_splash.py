"""tools/patch_splash.py: the pixel layout and PNG round trip offline; with HX_STOMP_HXF set, export then apply on
the stock firmware changes only Entry 0 (the text hook), and a 320x240 PNG switches the boot view to Screen_Boot."""
import os
import random
import shutil

import pytest

import patch_amp as pa
import patch_splash as ps


@pytest.mark.parametrize("h", [ps.SPLASH[1], ps.FULL[1]])
def test_encode_decode_round_trip(h):
    rng = random.Random(h)
    px = bytes(rng.randrange(256) for _ in range(ps.W * h * 2))
    assert ps.encode(ps.decode(px)) == px


def test_png_round_trip(tmp_path):
    rng = random.Random(2)
    rows = [[tuple(rng.randrange(256) for _ in range(3)) for _ in range(ps.W)] for _ in range(ps.FULL[1])]
    ps.write_png(tmp_path / "s.png", rows)
    assert ps.read_png(tmp_path / "s.png") == (ps.W, ps.FULL[1], rows)


def test_layout_column_major_from_bottom():
    h = ps.SPLASH[1]
    rows = [[(0, 0, 0)] * ps.W for _ in range(h)]
    rows[0][1] = (255, 0, 0)
    px = ps.encode(rows)
    assert px[2 * (1 * h + h - 1):][:2] == b"\x1f\x00"        # red in the bottom 5 bits, as stock Play_Red


@pytest.fixture(scope="module")
def stock():
    path = os.environ.get("HX_STOMP_HXF")
    if not path:
        pytest.skip("HX_STOMP_HXF is not set")
    return pa.load_l6ia_from_any(path)[0]


def pixels(data):
    e8, (off, ln) = ps.splash_entries(data)
    return e8[off:off + ln]


@pytest.mark.firmware
def test_stock_round_trip(tmp_path, stock):
    ps.write_png(tmp_path / "stock.png", ps.decode(pixels(stock)))
    out = ps.patch_splash(stock, tmp_path / "stock.png", log=lambda *_: None)
    for k in range(1, 15):
        assert pa.get_entry_swapped(out, k) == pa.get_entry_swapped(stock, k)


@pytest.mark.firmware
def test_full_screen(tmp_path, stock):
    rows = [[(x % 256, y, 128) for x in range(ps.W)] for y in range(ps.FULL[1])]
    ps.write_png(tmp_path / "full.png", rows)
    out = ps.patch_splash(stock, tmp_path / "full.png", log=lambda *_: None)
    assert ps.decode(pixels(out)) == ps.decode(ps.encode(rows))
    e0 = pa.get_entry_swapped(out, 0)
    o = ps.name_offset(e0)
    assert e0[o:o + 16] == b"Screen_Boot".ljust(16, b"\0")
    assert pa.get_entry_swapped(out, 1) == pa.get_entry_swapped(stock, 1)


@pytest.mark.firmware
def test_text(stock):
    out = ps.patch_text(stock, "CustomOS 3.80.0", log=lambda *_: None)
    e0 = pa.get_entry_swapped(out, 0)
    segs = pa._parse_e0_segments(e0)
    o = pa._e0_vaddr_to_foff(segs, ps.TEXT_SITE, len(ps.TEXT_STOCK))
    assert e0[o:o + len(ps.TEXT_STOCK)] == b"CustomOS 3.80.0".ljust(len(ps.TEXT_STOCK), b"\0")
    lit = pa._e0_vaddr_to_foff(segs, ps.VERSION_LITERAL)
    assert int.from_bytes(e0[lit:lit + 4], "little") == ps.TEXT_SITE + len("CustomOS 3.80.0")
    with pytest.raises(SystemExit):
        ps.patch_text(out, "again", log=lambda *_: None)
    with pytest.raises(SystemExit):
        ps.patch_text(stock, "x" * len(ps.TEXT_STOCK), log=lambda *_: None)


@pytest.mark.firmware
def test_transparent_text(tmp_path, stock):
    ps.write_png(tmp_path / "s.png", ps.decode(pixels(stock)))
    out = ps.patch_splash(stock, tmp_path / "s.png", log=lambda *_: None)
    e0 = pa.get_entry_swapped(out, 0)
    segs = pa._parse_e0_segments(e0)
    o = pa._e0_vaddr_to_foff(segs, ps.RENDER_FN, 6)
    _, _, slen, dst, _ = pa._parse_e0_segments(pa.get_entry_swapped(stock, 0))[6]
    assert e0[o:o + 6] == pa.thumb_bw(ps.RENDER_FN, dst + slen) + b"\x00\xbf"
    cave = ps.transparent_text_cave(dst + slen)
    c = pa._e0_vaddr_to_foff(segs, dst + slen, len(cave))
    assert e0[c:c + len(cave)] == cave
    assert cave[-10:-4] == ps.RENDER_STOCK


def test_topo_picture(tmp_path):
    import splash_topo
    rows = splash_topo.render(23, 34)
    assert (len(rows[0]), len(rows)) == (ps.W, ps.FULL[1])


@pytest.mark.skipif(not shutil.which("sips"), reason="converting pictures needs macOS sips")
@pytest.mark.parametrize("fit", ["fill", "fit"])
def test_any_picture(tmp_path, fit):
    rows = [[(255, 0, 0) if x < 200 else (0, 0, 255) for x in range(400)] for _ in range(100)]
    ps.write_png(tmp_path / "wide.png", rows)
    w, h, out = ps.load_picture(tmp_path / "wide.png", fit)
    assert (w, h) == (ps.W, ps.FULL[1])
    assert out[120][0][0] > 200 and out[120][319][2] > 200
    assert (out[0][160] == (0, 0, 0)) == (fit == "fit")        # fit pads the wide picture's top and bottom with black


@pytest.mark.firmware
def test_stock_colours(stock):
    import struct
    e7, e8 = pa.get_entry_swapped(stock, 7), pa.get_entry_swapped(stock, 8)
    n, recs = struct.unpack_from("<2I", e7, 0x10)
    names = {e7[o:o + ln]: i for i, (o, ln) in enumerate(struct.unpack_from("<2I", e7, 0x24 + 8 * i) for i in range(n))}
    for name, channel in ((b"Play_Red", 0), (b"Play_Green", 1), (b"Play_Blue", 2)):
        idx = struct.unpack_from("<I", e7, recs + 48 * names[name] + 8)[0]
        ln, off = struct.unpack_from("<2I", e8, 0x18 + 8 * idx)
        rgb = ps.pixel_rgb(max(set(px := struct.unpack_from(f"<{ln // 2}H", e8, off)) - {0}, key=px.count))
        assert max(range(3), key=lambda k: rgb[k]) == channel, (name, rgb)
