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


@pytest.mark.skipif(not shutil.which("sips"), reason="converting pictures needs macOS sips")
@pytest.mark.parametrize("fit", ["fill", "fit"])
def test_any_picture(tmp_path, fit):
    rows = [[(255, 0, 0) if x < 200 else (0, 0, 255) for x in range(400)] for _ in range(100)]
    ps.write_png(tmp_path / "wide.png", rows)
    w, h, out = ps.load_picture(tmp_path / "wide.png", fit)
    assert (w, h) == (ps.W, ps.FULL[1])
    assert out[120][0][0] > 200 and out[120][319][2] > 200
    assert (out[0][160] == (0, 0, 0)) == (fit == "fit")        # fit pads the wide picture's top and bottom with black


def test_text_must_be_ascii():
    with pytest.raises(SystemExit, match="printable ASCII"):
        splash.boot_text(None, "HXS OS \U0001f3b8")


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
@pytest.mark.parametrize("text, ok", [("x" * 23, True), ("x" * 24, False), ("HXS \U0001f3b8", False)])
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
def test_renderer_hook_runs(stock, m4emu, text, mode):
    """Calls the patched renderer with its 5 stack arguments; at the instruction after the moved prologue, the 9th (glyph mode)
    is 1 for the boot line's buffer only, and the other four are untouched."""
    e0 = build(stock, {"HX_SPLASH_TEXT": "HXS OS v0.1"})[0][0]
    _, poff, slen, dst, _ = pa._parse_e0_segments(e0)[6]
    m = m4emu.M4(e0[poff:poff + slen], dst)
    seen = []
    # at fn + 6: the prologue (sub sp,#8; push.w 9 registers) is 44 bytes of stack, then the caller's arguments
    m.stub(splash.RENDER_FN + 6, lambda m: seen.append([m.u32(m.reg("sp") + 44 + 4 * i) for i in range(5)]),
           code=bytes.fromhex("bde8f04f02b07047"))                  # pop.w {r4-r11,lr}; add sp,#8; bx lr
    m.write(m4emu.STACK_TOP, struct.pack("<5I", 29, 1, 0xb1b1b1, 6, 0))
    m.call(splash.RENDER_FN, 0x28d1ce98, text, 0x30, 160)
    assert seen == [[29, 1, 0xb1b1b1, 6, mode]]
