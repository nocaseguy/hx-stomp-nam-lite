"""tools/patch_splash.py: the pixel layout and PNG round trip offline; with HX_STOMP_HXF set, export then apply on
the stock firmware changes only Entry 0 (the text hook), and a 320x240 PNG switches the boot view to Screen_Boot."""
import os
import random

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
    assert px[2 * (1 * h + h - 1):][:2] == b"\x1f\x00"


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


def rgba_png(path, w, h, px):
    import struct
    import zlib
    raw = b"".join(b"\0" + bytes(v for x in range(w) for v in px(x, y)) for y in range(h))
    chunk = lambda k, d: struct.pack(">I", len(d)) + k + d + struct.pack(">I", zlib.crc32(k + d))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def test_clusters():
    assert ps.clusters("v0.1 🎸👍🏽❤️👨‍👩‍👧") == list("v0.1 ") + ["🎸", "👍🏽", "❤️", "👨‍👩‍👧"]


def test_glyph_from_png(tmp_path):
    # a 40x40 red square in an 80x80 transparent PNG becomes an 18x18 red glyph at the top of the 21 px cell, level with the capitals
    rgba_png(tmp_path / "e.png", 80, 80, lambda x, y: (255, 0, 0, 255) if 20 <= x < 60 and 20 <= y < 60 else (0, 0, 0, 0))
    w, px = ps.glyph_from_png(tmp_path / "e.png")
    assert w == ps.EMOJI_H and len(px) == w * ps.FONT_H * 2
    at = lambda x, y: px[2 * (x * ps.FONT_H + ps.FONT_H - 1 - y):][:2]
    assert all(at(x, y) == (b"\x1f\x00" if y < ps.EMOJI_H else b"\0\0") for x in range(w) for y in range(ps.FONT_H))


@pytest.mark.firmware
def test_emoji_text(tmp_path, stock):
    import struct
    rgba_png(tmp_path / "e.png", 30, 30, lambda x, y: (0, 255, 0, 255) if (x - 15) ** 2 + (y - 15) ** 2 < 100 else (0, 0, 0, 0))
    out = ps.patch_text(stock, "HXS 🎸", {"🎸": str(tmp_path / "e.png")}, log=lambda *_: None)
    e0, e7, e8 = (pa.get_entry_swapped(out, k) for k in (0, 7, 8))
    segs = pa._parse_e0_segments(e0)
    o = pa._e0_vaddr_to_foff(segs, ps.TEXT_SITE, 6)
    assert e0[o:o + 6] == b"HXS \x01\0"
    assert struct.unpack_from("<I", e0, pa._e0_vaddr_to_foff(segs, ps.TEXT_COLOUR_LITERAL))[0] == 0xffffff
    h, w, idx = struct.unpack_from("<3I", e7, 0xa740 + 12 * 1)
    o8 = pa.get_entry_swapped(stock, 8)
    n = struct.unpack_from("<I", o8, 8)[0]
    assert (h, idx, struct.unpack_from("<I", e8, 8)[0]) == (ps.FONT_H, n, n + 1)
    item = lambda b, i: (lambda ln, off: b[off:off + ln])(*struct.unpack_from("<2I", b, struct.unpack_from("<I", b, 12)[0] + 8 * i))
    assert all(item(e8, i) == item(o8, i) for i in range(n))
    assert len(item(e8, n)) == w * h * 2 and struct.unpack_from("<I", e8, 20)[0] == len(e8)
    assert e8[24:len(o8)] == o8[24:]


@pytest.mark.firmware
def test_stock_red_is_red(stock):
    import struct
    e7, e8 = pa.get_entry_swapped(stock, 7), pa.get_entry_swapped(stock, 8)
    n, recs = struct.unpack_from("<I", e7, 0x10)[0], struct.unpack_from("<I", e7, 0x14)[0]
    names = [e7[o:o + ln] for o, ln in (struct.unpack_from("<2I", e7, 0x24 + 8 * i) for i in range(n))]
    idx, _, _, h, w, _ = struct.unpack_from("<6I", e7, recs + 48 * names.index(b"Play_Red") + 8)
    ln, off = struct.unpack_from("<2I", e8, 0x18 + 8 * idx)
    px = struct.unpack_from(f"<{w * h}H", e8, off)
    assert ps.pixel_rgb(max(set(px), key=px.count)) == (255, 0, 0)


@pytest.mark.firmware
def test_find_image_follows_header(tmp_path, stock):
    import struct
    rgba_png(tmp_path / "e.png", 30, 30, lambda x, y: (255, 0, 0, 255))
    out = ps.patch_text(stock, "HXS 🎸", {"🎸": str(tmp_path / "e.png")}, log=lambda *_: None)
    e7, e8 = pa.get_entry_swapped(out, 7), bytearray(pa.get_entry_swapped(out, 8))
    n = struct.unpack_from("<I", pa.get_entry_swapped(stock, 8), 8)[0]
    want = ps.find_image(e7, e8, ps.FULL[0], ps.FULL[1])
    e8[0x18:0x18 + 8 * n] = bytes(8 * n)
    assert ps.find_image(e7, e8, ps.FULL[0], ps.FULL[1]) == want
