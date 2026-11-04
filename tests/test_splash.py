"""The boot screen: tools/patch_splash.py's pictures offline (layout, PNG, sips conversion), and with HX_STOMP_HXF set,
tools/features/splash.py through the features engine: the picture, the full-screen switch, the text and the renderer hook (run
in unicorn on the patched Entry 0)."""
import os
import random
import shutil
import struct

import pytest

import features
import image_store
import l6ia
import patch_amp as pa
import patch_menu as pm
import patch_splash as ps
import splash_emoji
from features import splash


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


def test_topo_picture():
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
    assert splash_emoji.clusters("v0.1 🎸👍🏽❤️👨‍👩‍👧") == list("v0.1 ") + ["🎸", "👍🏽", "❤️", "👨‍👩‍👧"]


def test_glyph_from_png(tmp_path):
    # a 40x40 red square in an 80x80 transparent PNG becomes an 18x18 red glyph at the top of the 21 px cell, level with the capitals
    rgba_png(tmp_path / "e.png", 80, 80, lambda x, y: (255, 0, 0, 255) if 20 <= x < 60 and 20 <= y < 60 else (0, 0, 0, 0))
    w, px = splash_emoji.glyph_from_png(tmp_path / "e.png", 21)
    assert w == splash_emoji.EMOJI_H and len(px) == w * 21 * 2
    at = lambda x, y: px[2 * (x * 21 + 21 - 1 - y):][:2]
    assert all(at(x, y) == (b"\x1f\x00" if y < splash_emoji.EMOJI_H else b"\0\0") for x in range(w) for y in range(21))


@pytest.mark.skipif(not shutil.which("sips"), reason="converting pictures needs macOS sips")
@pytest.mark.parametrize("fit", ["fill", "fit"])
def test_any_picture(tmp_path, fit):
    rows = [[(255, 0, 0) if x < 200 else (0, 0, 255) for x in range(400)] for _ in range(100)]
    ps.write_png(tmp_path / "wide.png", rows)
    w, h, out = ps.load_picture(tmp_path / "wide.png", fit)
    assert (w, h) == (ps.W, ps.FULL[1])
    assert out[120][0][0] > 200 and out[120][319][2] > 200
    assert (out[0][160] == (0, 0, 0)) == (fit == "fit")        # fit pads the wide picture's top and bottom with black


def test_text_must_be_printable():
    with pytest.raises(SystemExit, match="printable ASCII and emoji"):
        splash.boot_text(None, "HXS\x07")


@pytest.fixture(scope="module")
def stock():
    path = os.environ.get("HX_STOMP_HXF")
    if not path:
        pytest.skip("HX_STOMP_HXF is not set")
    return pa.load_l6ia_from_any(path)[0]


def build(stock, env, cwd=None):
    """{entry: bytes} and the enabled feature names, as patch_menu.py makes them with env set."""
    entries, on = pm.menu_entries(lambda n: pa.get_entry_swapped(stock, n), env=env, cwd=cwd)
    return entries, [features.name(m) for m in on]


def e0_at(e0, va, n):
    o = pa._e0_vaddr_to_foff(pa._parse_e0_segments(e0), va, n)
    return e0[o:o + n]


def bw_target(src, hw):
    """The destination of the Thumb-2 B.W hw (4 bytes) at src."""
    h1, h2 = struct.unpack("<2H", hw)
    s, j1, j2 = (h1 >> 10) & 1, (h2 >> 13) & 1, (h2 >> 11) & 1
    off = (s << 24) | ((~(j1 ^ s) & 1) << 23) | ((~(j2 ^ s) & 1) << 22) | ((h1 & 0x3ff) << 12) | ((h2 & 0x7ff) << 1)
    return src + 4 + off - ((1 << 25) if s else 0)


@pytest.mark.firmware
def test_off_without_inputs(stock):
    entries, on = build(stock, {})
    assert "splash" not in on and set(entries) == {0}
    assert e0_at(entries[0], splash.RENDER_FN, 6) == splash.RENDER_STOCK


@pytest.mark.firmware
def test_stock_colours(stock):
    e7, e8 = pa.get_entry_swapped(stock, 7), pa.get_entry_swapped(stock, 8)
    for name, channel in ((b"Play_Red", 0), (b"Play_Green", 1), (b"Play_Blue", 2)):
        img = image_store.image(e7, e8, name)
        px = struct.unpack_from(f"<{img.length // 2}H", e8, img.offset)
        rgb = image_store.pixel_rgb(max(set(px) - {0}, key=px.count))
        assert max(range(3), key=lambda k: rgb[k]) == channel, (name, rgb)


@pytest.mark.firmware
def test_stock_picture_round_trip(tmp_path, stock):
    _, px = ps.drawn_image(stock)
    ps.write_png(tmp_path / "stock.png", ps.decode(px))
    entries, on = build(stock, {"HX_SPLASH": "stock.png"}, cwd=tmp_path)
    assert "splash" in on
    assert 8 not in entries                    # the same pixels: the engine leaves an unchanged entry out
    assert e0_at(entries[0], splash.NAME_SITE, 16) == ps.SPLASH[0].ljust(16, b"\0")


@pytest.mark.firmware
def test_full_screen(tmp_path, stock):
    rows = [[(x % 256, y, 128) for x in range(ps.W)] for y in range(ps.FULL[1])]
    ps.write_png(tmp_path / "full.png", rows)
    entries, _ = build(stock, {"HX_SPLASH": str(tmp_path / "full.png")})
    assert e0_at(entries[0], splash.NAME_SITE, 16) == ps.FULL[0].ljust(16, b"\0")
    out = l6ia.rebuild_archive(stock, entries)[0]
    name, px = ps.drawn_image(out)
    assert name == ps.FULL[0] and px == ps.encode(rows)
    e8, stock8 = entries[8], pa.get_entry_swapped(stock, 8)
    img = image_store.image(pa.get_entry_swapped(stock, 7), stock8, ps.FULL[0])
    assert e8[:img.offset] == stock8[:img.offset] and e8[img.offset + img.length:] == stock8[img.offset + img.length:]
    assert 1 not in entries and 7 not in entries


@pytest.mark.firmware
def test_text(stock):
    entries, _ = build(stock, {"HX_SPLASH_TEXT": "CustomOS 3.80.0"})
    assert set(entries) == {0}
    e0 = entries[0]
    assert e0_at(e0, splash.TEXT_SITE, len(splash.TEXT_STOCK)) == b"CustomOS 3.80.0".ljust(len(splash.TEXT_STOCK), b"\0")
    assert int.from_bytes(e0_at(e0, splash.VERSION_LITERAL, 4), "little") == splash.TEXT_SITE + len("CustomOS 3.80.0")


@pytest.mark.firmware
@pytest.mark.parametrize("text, ok", [("x" * 23, True), ("x" * 24, False), ("HXS \x07", False)])
def test_text_limits(stock, text, ok):
    if ok:
        build(stock, {"HX_SPLASH_TEXT": text})
    else:
        with pytest.raises(SystemExit):
            build(stock, {"HX_SPLASH_TEXT": text})


@pytest.mark.firmware
def test_fit_must_be_a_choice(tmp_path, stock):
    ps.write_png(tmp_path / "s.png", [[(0, 0, 0)] * ps.W for _ in range(ps.FULL[1])])
    with pytest.raises(SystemExit, match="HX_SPLASH_FIT"):
        build(stock, {"HX_SPLASH": str(tmp_path / "s.png"), "HX_SPLASH_FIT": "stretch"})


@pytest.mark.firmware
def test_renderer_hook(stock):
    e0 = build(stock, {"HX_SPLASH_TEXT": "HXS OS v0.1"})[0][0]
    site = e0_at(e0, splash.RENDER_FN, 6)
    assert site[4:] == b"\x00\xbf"
    handler = bw_target(splash.RENDER_FN, site[:4])
    stock_fn = bw_target(handler + 20, e0_at(e0, handler + 20, 4))        # the handler's closing b.w: to hook.stock
    assert e0_at(e0, handler, 24) == splash.transparent_text_cave(handler, stock_fn)
    assert e0_at(e0, stock_fn, 6) == splash.RENDER_STOCK
    assert bw_target(stock_fn + 6, e0_at(e0, stock_fn + 6, 4)) == splash.RENDER_FN + 6


@pytest.mark.firmware
@pytest.mark.parametrize("text, mode", [(splash.TEXT_BUF, 1), (splash.TEXT_BUF + 4, 0)])
@pytest.mark.parametrize("colour", [splash.TEXT_COLOUR, 0xffffff])      # stock grey, and the white of a line with emoji
def test_renderer_hook_runs(stock, m4emu, text, mode, colour):
    """Calls the patched renderer with its 5 stack arguments; at the instruction after the moved prologue, the 9th (glyph mode)
    is 1 for the boot line's buffer only, and the other four are untouched."""
    e0 = build(stock, {"HX_SPLASH_TEXT": "HXS OS v0.1"})[0][0]
    _, poff, slen, dst, _ = pa._parse_e0_segments(e0)[6]
    m = m4emu.M4(e0[poff:poff + slen], dst)
    seen = []
    # at fn + 6: the prologue (sub sp,#8; push.w 9 registers) is 44 bytes of stack, then the caller's arguments
    m.stub(splash.RENDER_FN + 6, lambda m: seen.append([m.u32(m.reg("sp") + 44 + 4 * i) for i in range(5)]),
           code=bytes.fromhex("bde8f04f02b07047"))                  # pop.w {r4-r11,lr}; add sp,#8; bx lr
    m.write(m4emu.STACK_TOP, struct.pack("<5I", 29, 1, colour, 6, 0))
    m.call(splash.RENDER_FN, 0x28d1ce98, text, 0x30, 160)
    assert seen == [[29, 1, colour, 6, mode]]


def emoji_env(tmp_path, text, emoji):
    """The splash inputs for text, each emoji's picture a small opaque disc of its own colour (no rendering needed)."""
    for k, e in enumerate(emoji):
        colour = ((255, 0, 0), (0, 255, 0), (0, 0, 255))[k % 3]
        rgba_png(tmp_path / f"e{k}.png", 30, 30,
                 lambda x, y, c=colour: c + (255,) if (x - 15) ** 2 + (y - 15) ** 2 < 100 else (0, 0, 0, 0))
    return {"HX_SPLASH_TEXT": text, "HX_SPLASH_GLYPHS": ",".join(f"{e}=e{k}.png" for k, e in enumerate(emoji))}


@pytest.mark.firmware
def test_emoji_text(tmp_path, stock):
    entries, _ = build(stock, emoji_env(tmp_path, "HXS 🎸 v 🎸🔥", ["🎸", "🔥"]), cwd=tmp_path)
    e0, e7, e8 = entries[0], entries[7], entries[8]
    assert e0_at(e0, splash.TEXT_SITE, 11) == b"HXS \x01 v \x01\x02\0"          # the repeated emoji shares its slot
    assert int.from_bytes(e0_at(e0, splash.TEXT_COLOUR_LITERAL, 4), "little") == 0xffffff
    stock7, stock8 = pa.get_entry_swapped(stock, 7), pa.get_entry_swapped(stock, 8)
    n = struct.unpack_from("<I", stock8, 8)[0]
    count, table = image_store.font(e7, splash.FONT_NAME)
    for slot, k in ((1, 0), (2, 1)):
        h, w, idx = image_store.glyph(e7, table, slot)
        assert (h, idx) == (21, n + k)
        off, ln = image_store.item(e8, idx)
        assert e8[off:off + ln] == splash_emoji.glyph_from_png(tmp_path / f"e{k}.png", 21)[1] and ln == 2 * w * h
    assert image_store.glyph(e7, table, 3)[2] == image_store.EMPTY_GLYPH
    assert struct.unpack_from("<I", e8, 8)[0] == n + 2 and e8[24:len(stock8)] == stock8[24:]   # no stock byte moves


@pytest.mark.firmware
def test_emoji_pictures_follow_the_header(tmp_path, stock):
    rows = [[(x % 256, y, 128) for x in range(ps.W)] for y in range(ps.FULL[1])]
    ps.write_png(tmp_path / "full.png", rows)
    env = dict(emoji_env(tmp_path, "HXS 🎸", ["🎸"]), HX_SPLASH=str(tmp_path / "full.png"))
    entries, _ = build(stock, env, cwd=tmp_path)
    e7, e8 = entries[7], bytearray(entries[8])
    n = struct.unpack_from("<I", pa.get_entry_swapped(stock, 8), 8)[0]
    want = image_store.image(e7, e8, ps.FULL[0])
    e8[0x18:0x18 + 8 * n] = bytes(8 * n)                       # the stock table, which nothing should read any more
    img = image_store.image(e7, e8, ps.FULL[0])
    assert img == want and e8[img.offset:img.offset + img.length] == ps.encode(rows)


@pytest.mark.firmware
@pytest.mark.parametrize("text, emoji, ok", [
    ("HXS OS v0.1 " + "".join(chr(0x1f600 + i) for i in range(11)), 11, True),     # 23 characters
    ("HXS OS v0.1 " + "".join(chr(0x1f600 + i) for i in range(12)), 12, False),    # 24
    ("".join(chr(0x1f600 + i) for i in range(30)), 30, False),                     # more emoji than free slots
])
def test_emoji_limits(tmp_path, stock, text, emoji, ok):
    env = emoji_env(tmp_path, text, [chr(0x1f600 + i) for i in range(emoji)])
    if ok:
        build(stock, env, cwd=tmp_path)
    else:
        with pytest.raises(SystemExit):
            build(stock, env, cwd=tmp_path)


@pytest.mark.firmware
def test_emoji_needs_a_picture_or_swift(tmp_path, stock, monkeypatch):
    monkeypatch.setattr(splash_emoji.shutil, "which", lambda name: None)
    with pytest.raises(SystemExit, match="--splash-glyph"):
        build(stock, {"HX_SPLASH_TEXT": "HXS 🎸"})
