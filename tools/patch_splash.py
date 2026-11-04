#!/usr/bin/env python3
"""patch_splash.py - the boot splash picture of the HX Stomp 3.80.0 firmware (the app's copy, not the bootloader's).

usage:
  patch_splash.py export <in.hxf|in.l6ia> <out.png>          # the splash now in the image, as a template
  patch_splash.py apply <in> <out> --image <picture> [--fit fill|fit] [--donor stock.hxf]
  patch_splash.py text <in> <out> --text "HXS OS v0.1 🎸" [--glyph 🎸=guitar.png ...] [--donor stock.hxf]

The app's boot view draws the image store's HXStomp_Splash (Entry 8, 320x181) at
the top of the screen, the loading bar across it at y = 121, and the firmware
version in the 59 rows below it. A 320x240 PNG fills the whole screen instead: it
goes into the unused Screen_Boot image (320x240), and the boot view's image name
becomes Screen_Boot; the loading bar and the version are drawn over it.
With either picture, the text's glyphs are drawn without their black backgrounds.
The text under the picture is "   Firmware  " with "3.80.0" appended, next to the
firmware icon; `text` replaces the whole line (up to 23 characters). Each emoji in it
becomes a colour glyph of the line's font in a free control-code slot (its PNG from
--glyph, else rendered by tools/emoji_png.swift on macOS), and the line is drawn white,
the one colour the glyph blitters copy unchanged.
The bootloader shows its own copy of the stock splash before that, from power-on
until the app starts; this tool leaves it alone.
Picture: a 320x240 (or 320x181) PNG, 8-bit grey, RGB, palette or with alpha (blended
onto black), not interlaced, is used as it is. Any other picture (JPEG, HEIC, PNG of
another size...) is converted on macOS with sips to sRGB at 320x240: scaled to cover
the screen and cropped at the centre (fill, the default), or scaled to fit inside it
on black (fit).
"""
import argparse
import hashlib
import os
import shutil
import struct
import subprocess
import tempfile
import zlib

import l6ia
import patch_amp as pa
from patch_menu import STOCK_BASE, Asm, Cave

W = 320
# name, height, MD5 of the stock pixels
SPLASH = (b'HXStomp_Splash', 181, '102fdff9f8738b232273a27d581c49ae')
FULL = (b'Screen_Boot', 240, '051d4adbbbcdf074b62077e549ac1e20')
NAME_SITE = 0x28e24cf4                              # the boot view's image name, read only by the literal at 0x28d92924
TEXT_SITE, TEXT_STOCK = 0x28e24d14, b'   Firmware  \0\0\0' + b'3.80.0\0\0'
VERSION_LITERAL = 0x28d92938                        # the "3.80.0" the boot view appends to the text
RENDER_FN, RENDER_STOCK = 0x28db7aa4, bytes.fromhex('82b02de9f04f')    # the text renderer's sub sp,#8; push.w {r4-r11,lr}
TEXT_BUF = 0x2811ee38                               # the boot view's text buffer: the renderer's r1 for that line only
TEXT_COLOUR_LITERAL, TEXT_COLOUR = 0x28d92940, 0xb1b1b1     # the boot view's two text widgets' colour
FONT_SITE = 0x28d92836                              # movs r1,#1 before setFont: the line's font is the loader's 2nd
FONT_NAME_LITERAL, FONT_NAME = 0x28db75c4, b'hx21_regularFont'
FONT_H = 21
EMOJI_TOP, EMOJI_H = 0, 18          # the font's capitals are rows 1..16 of the cell (baseline 16): emoji 1 px beyond, centred on them
# Control codes the line can hold: not NUL (the end), \n or \r (line breaks); all empty in every font
FREE_SLOTS = [c for c in range(1, 32) if c not in (0x0a, 0x0d)]
EMOJI_PNG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'emoji_png.swift')
SRGB = '/System/Library/ColorSync/Profiles/sRGB Profile.icc'


def find_image(e7, e8, name, h_want):
    """(offset, length) of an image's pixels in Entry 8."""
    if struct.unpack_from('<I', e7, 0)[0] != 0x5b21255e or struct.unpack_from('<I', e8, 0)[0] != 0x2a5f3b5e:
        raise SystemExit('patch-splash: Entry 7/8 is not the image store')
    n, recs = struct.unpack_from('<I', e7, 0x10)[0], struct.unpack_from('<I', e7, 0x14)[0]
    for i in range(n):
        off, ln = struct.unpack_from('<2I', e7, 0x24 + 8 * i)
        if e7[off:off + ln] != name:
            continue
        idx, _, _, h, w, bpp = struct.unpack_from('<6I', e7, recs + 48 * i + 8)
        ln8, off8 = struct.unpack_from('<2I', e8, struct.unpack_from('<I', e8, 12)[0] + 8 * idx)
        if (w, h, bpp, ln8) != (W, h_want, 16, W * h_want * 2):
            raise SystemExit(f'patch-splash: {name.decode()} is {w}x{h}, {bpp} bpp, {ln8} bytes; '
                             f'expected {W}x{h_want} RGB565')
        return off8, ln8
    raise SystemExit(f'patch-splash: no {name.decode()} in the image store')


def read_png(path, alpha=False):
    """(width, height, rows of (r, g, b) tuples, blended onto black; (r, g, b, a) with alpha) from an 8-bit, non-interlaced PNG."""
    raw = open(path, 'rb').read()
    if raw[:8] != b'\x89PNG\r\n\x1a\n':
        raise SystemExit(f'{path}: not a PNG')
    pos, idat, palette, trns = 8, b'', None, b''
    while pos < len(raw):
        ln, kind = struct.unpack_from('>I4s', raw, pos)
        body = raw[pos + 8:pos + 8 + ln]
        if kind == b'IHDR':
            w, h, depth, ctype, _, _, interlace = struct.unpack('>IIBBBBB', body)
        elif kind == b'PLTE':
            palette = [tuple(body[i:i + 3]) for i in range(0, len(body), 3)]
        elif kind == b'tRNS':
            trns = body
        elif kind == b'IDAT':
            idat += body
        pos += 12 + ln
    nch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(ctype)
    if depth != 8 or nch is None or interlace:
        raise SystemExit(f'{path}: needs 8 bits per channel, not interlaced (it has {depth} bits, colour type {ctype}, '
                         f'interlace {interlace}); re-save it as a plain RGB PNG')
    data, stride = zlib.decompress(idat), w * nch
    prev, rows = bytearray(stride), []
    for y in range(h):
        f, line = data[y * (stride + 1)], bytearray(data[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - nch] if i >= nch else 0
            b, c = prev[i], prev[i - nch] if i >= nch else 0
            if f == 1:
                line[i] = (line[i] + a) & 0xff
            elif f == 2:
                line[i] = (line[i] + b) & 0xff
            elif f == 3:
                line[i] = (line[i] + (a + b) // 2) & 0xff
            elif f == 4:
                p = a + b - c
                pa_, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa_ <= pb and pa_ <= pc else b if pb <= pc else c)) & 0xff
        prev = line
        row = []
        for x in range(w):
            px = line[x * nch:(x + 1) * nch]
            if ctype == 3:
                rgb, a = palette[px[0]], trns[px[0]] if px[0] < len(trns) else 255
            elif ctype in (0, 4):
                rgb, a = (px[0],) * 3, px[1] if ctype == 4 else 255
            else:
                rgb, a = tuple(px[:3]), px[3] if ctype == 6 else 255
            row.append(tuple(rgb) + (a,) if alpha else tuple(v * a // 255 for v in rgb))
        rows.append(row)
    return w, h, rows


def read_bmp(path):
    """Rows of (r, g, b) from a 24- or 32-bit uncompressed BMP, as sips writes them."""
    raw = open(path, 'rb').read()
    off, w, h, bpp = struct.unpack_from('<I', raw, 10)[0], *struct.unpack_from('<iiHH', raw, 18)[:2], \
        struct.unpack_from('<H', raw, 28)[0]
    if raw[:2] != b'BM' or bpp not in (24, 32) or struct.unpack_from('<I', raw, 30)[0] not in (0, 3):
        raise SystemExit(f'{path}: not an uncompressed 24/32-bit BMP')
    n, stride = bpp // 8, (w * bpp // 8 + 3) & ~3
    rows = [[tuple(raw[off + y * stride + x * n + k] for k in (2, 1, 0)) for x in range(w)] for y in range(abs(h))]
    return rows[::-1] if h > 0 else rows


def png_size(path):
    """(width, height) of a PNG that read_png can take, else None."""
    head = open(path, 'rb').read(29)
    if head[:8] != b'\x89PNG\r\n\x1a\n' or head[12:16] != b'IHDR':
        return None
    w, h, depth, ctype, _, _, interlace = struct.unpack('>IIBBBBB', head[16:29])
    return (w, h) if depth == 8 and ctype in (0, 2, 3, 4, 6) and not interlace else None


def load_picture(path, fit='fill'):
    """(width, height, rows) for the splash: a 320x240 or 320x181 PNG as it is, anything else through sips at 320x240."""
    if png_size(path) in ((W, SPLASH[1]), (W, FULL[1])):
        return read_png(path)
    if not shutil.which('sips'):
        raise SystemExit(f'{path}: not a 320x240 PNG, and converting it needs macOS (sips)')
    H = FULL[1]

    def sips(*args):
        r = subprocess.run(['sips', *args], capture_output=True, text=True)
        if r.returncode:
            raise SystemExit(f'{path}: sips could not convert it: {r.stderr.strip() or r.stdout.strip()}')
        return r.stdout

    info = sips('-g', 'pixelWidth', '-g', 'pixelHeight', path)
    sw, sh = (int(line.split()[-1]) for line in info.splitlines()[1:3])
    pick = max if fit == 'fill' else min
    scale = pick(W / sw, H / sh)
    rw, rh = pick(W, round(sw * scale)), pick(H, round(sh * scale))
    with tempfile.TemporaryDirectory() as tmp:
        scaled, final = os.path.join(tmp, 'scaled.bmp'), os.path.join(tmp, 'final.bmp')
        sips('-s', 'format', 'bmp', '--matchTo', SRGB, '--resampleHeightWidth', str(rh), str(rw), path, '--out', scaled)
        if fit == 'fill':
            sips('--cropToHeightWidth', str(H), str(W), scaled, '--out', final)
        else:
            sips('--padToHeightWidth', str(H), str(W), '--padColor', '000000', scaled, '--out', final)
        rows = read_bmp(final)
    if (len(rows[0]), len(rows)) != (W, H):
        raise SystemExit(f'{path}: sips made {len(rows[0])}x{len(rows)}, not {W}x{H}')
    return W, H, rows


def write_png(path, rows):
    w, h = len(rows[0]), len(rows)
    raw = b''.join(b'\x00' + bytes(v for px in row for v in px) for row in rows)
    chunk = lambda kind, body: struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))
    open(path, 'wb').write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
                           + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))


def pixel(r, g, b):
    """A pixel as the screen takes it: blue in the top 5 bits, red in the bottom 5 (stock Play_Red is 0x001f)."""
    return ((b * 31 + 127) // 255) << 11 | ((g * 63 + 127) // 255) << 5 | (r * 31 + 127) // 255


def pixel_rgb(v):
    return ((v & 31) * 255 // 31, (v >> 5 & 63) * 255 // 63, (v >> 11) * 255 // 31)


def encode(rows):
    """Pixels as the image store keeps them: column by column, each from the bottom up."""
    H = len(rows)
    out = bytearray(W * H * 2)
    for y, row in enumerate(rows):
        for x, (r, g, b) in enumerate(row):
            struct.pack_into('<H', out, 2 * (x * H + H - 1 - y), pixel(r, g, b))
    return bytes(out)


def decode(px):
    H = len(px) // (2 * W)
    rows = []
    for y in range(H):
        row = []
        for x in range(W):
            row.append(pixel_rgb(struct.unpack_from('<H', px, 2 * (x * H + H - 1 - y))[0]))
        rows.append(row)
    return rows


def name_offset(e0):
    segs = pa._parse_e0_segments(e0)
    if segs[6][3] != STOCK_BASE:
        raise SystemExit('patch-splash: this patch is for the HX Stomp 3.80.0, not the XL')
    return pa._e0_vaddr_to_foff(segs, NAME_SITE, 16)


def splash_entries(l6ia_bytes):
    """(Entry 8, (offset, length) of the image the boot view draws)."""
    e0 = pa.get_entry_swapped(l6ia_bytes, 0)
    o = name_offset(e0)
    name, h, _ = FULL if e0[o:o + len(FULL[0]) + 1] == FULL[0] + b'\0' else SPLASH
    e7, e8 = pa.get_entry_swapped(l6ia_bytes, 7), pa.get_entry_swapped(l6ia_bytes, 8)
    return e8, find_image(e7, e8, name, h)


def transparent_text_cave(at):
    """Sets the renderer's 9th argument (glyph mode, [sp, #0x10] on entry) to 1 for the boot line, then runs the replaced prologue."""
    a = Asm(at)
    a.movw_movt(12, TEXT_BUF)
    a.h(0x4561)                         # cmp r1, r12
    a.b16('ne', 'stock')
    a.h(0xf04f, 0x0c01)                 # mov.w r12, #1
    a.h(0xf8cd, 0xc010)                 # str.w r12, [sp, #0x10]
    a.label('stock')
    a.raw(RENDER_STOCK)
    a.bw(RENDER_FN + len(RENDER_STOCK))
    return a.bytes()


def transparent_text_entry0(e0):
    """Entry 0 whose boot line draws only its glyphs' ink (mode 1), not each glyph's black box (mode 0)."""
    segs = pa._parse_e0_segments(e0)
    o = pa._e0_vaddr_to_foff(segs, RENDER_FN, len(RENDER_STOCK))
    if e0[o:o + len(RENDER_STOCK)] != RENDER_STOCK:
        raise SystemExit('patch-splash: the text renderer\'s entry is not the stock one (already patched?)')
    hdr, poff, slen, dst, nxt = segs[6]
    cave = Cave(dst + slen)
    va = cave.add(transparent_text_cave(cave.next()))
    out = bytearray(e0[:nxt])
    out[o:o + len(RENDER_STOCK)] = pa.thumb_bw(RENDER_FN, va) + b'\x00\xbf'
    out += cave.buf
    out += b'\x00' * ((-len(out)) & 3)
    struct.pack_into('<3I', out, hdr, slen + len(cave.buf), dst, poff + slen + len(cave.buf))
    struct.pack_into('<I', out, 4, len(out))
    if len(out) > pa.E0_MAX:
        raise SystemExit(f'patch-splash: Entry 0 would be {len(out):#x} bytes; its partition holds {pa.E0_MAX:#x}')
    return bytes(out)


def patch_splash(l6ia_bytes, png, log=print, fit='fill'):
    w, h, rows = load_picture(png, fit)
    name, _, stock_md5 = FULL if h == FULL[1] else SPLASH
    e0 = bytearray(pa.get_entry_swapped(l6ia_bytes, 0))
    o = name_offset(e0)
    if e0[o:o + 16] != SPLASH[0] + b'\0\0':
        raise SystemExit('patch-splash: the boot view\'s image name is not the stock one (already patched?)')
    e7, e8 = pa.get_entry_swapped(l6ia_bytes, 7), pa.get_entry_swapped(l6ia_bytes, 8)
    off, ln = find_image(e7, e8, name, h)
    if hashlib.md5(e8[off:off + ln]).hexdigest() != stock_md5:
        raise SystemExit(f'patch-splash: {name.decode()} is not the stock one (already patched?)')
    e8 = e8[:off] + encode(rows) + e8[off + ln:]
    if name == FULL[0]:
        e0[o:o + 16] = FULL[0].ljust(16, b'\0')
    new_l6ia, _, _ = l6ia.rebuild_archive(l6ia_bytes, {0: transparent_text_entry0(e0), 8: e8})
    log(f'[+] Entry 8: boot splash ({name.decode()}, {W}x{h}) from {png}; Entry 0: '
        + ('the boot view draws Screen_Boot, ' if name == FULL[0] else '') + 'its text without glyph backgrounds')
    return new_l6ia


def clusters(text):
    """Text split into ASCII characters and emoji (a non-ASCII code point with its joiners, modifiers and selectors)."""
    out = []
    for ch in text:
        cp = ord(ch)
        joins = cp in (0x200d, 0xfe0e, 0xfe0f, 0x20e3) or 0x1f3fb <= cp <= 0x1f3ff or 0xe0020 <= cp <= 0xe007f
        if out and not out[-1].isascii() and (joins or out[-1][-1] == '\u200d'):
            out[-1] += ch
        else:
            out.append(ch)
    return out


def glyph_from_png(path):
    """(width, RGB565 pixels) of a FONT_H tall glyph: the PNG's opaque part, scaled, blended onto black; 0 = transparent."""
    w, h, rows = read_png(path, alpha=True)
    ys = [y for y in range(h) if any(px[3] for px in rows[y])]
    xs = [x for x in range(w) if any(rows[y][x][3] for y in range(h))]
    if not ys:
        raise SystemExit(f'{path}: fully transparent')
    x0, y0, cw, ch = xs[0], ys[0], xs[-1] + 1 - xs[0], ys[-1] + 1 - ys[0]
    scale = EMOJI_H / max(ch, cw * EMOJI_H / 21)     # at most 21 px wide
    gw, gh = max(1, round(cw * scale)), max(1, round(ch * scale))
    top = EMOJI_TOP + (EMOJI_H - gh) // 2
    out = bytearray(gw * FONT_H * 2)
    for gy in range(gh):
        for gx in range(gw):
            sy0, sy1 = y0 + int(gy / scale), y0 + max(int(gy / scale) + 1, int((gy + 1) / scale))
            sx0, sx1 = x0 + int(gx / scale), x0 + max(int(gx / scale) + 1, int((gx + 1) / scale))
            acc, n = [0, 0, 0, 0], 0
            for sy in range(sy0, min(sy1, h)):
                for sx in range(sx0, min(sx1, w)):
                    r, g, b, a = rows[sy][sx]
                    acc[0] += r * a; acc[1] += g * a; acc[2] += b * a; acc[3] += a
                    n += 1
            if acc[3] < 0.1 * 255 * n:
                continue
            r, g, b = (v // (255 * n) for v in acc[:3])
            v = pixel(r, g, b)
            y = top + gy
            struct.pack_into('<H', out, 2 * (gx * FONT_H + FONT_H - 1 - y), v or 1)   # 1, not 0: black stays opaque
    return gw, bytes(out)


def render_emoji(emoji, tmp):
    if not shutil.which('swift'):
        raise SystemExit(f'patch-splash: no PNG for {emoji!r}; pass --glyph {emoji}=file.png (rendering one needs macOS swift)')
    out = os.path.join(tmp, f'emoji_{"_".join(f"{ord(c):x}" for c in emoji)}.png')
    subprocess.run(['swift', EMOJI_PNG, emoji, out], check=True, capture_output=True)
    return out


def add_glyphs(e7, e8, glyphs):
    """Entries 7 and 8 with glyphs {slot: (width, pixels)} in the line's font; Entry 8's new items and item table go after its end, so no stock byte moves."""
    e7, n = bytearray(e7), struct.unpack_from('<I', e7, 0x10)[0]
    recs = struct.unpack_from('<I', e7, 0x14)[0]
    names = [e7[o:o + ln] for o, ln in (struct.unpack_from('<2I', e7, 0x24 + 8 * i) for i in range(n))]
    font = names.index(FONT_NAME)
    count, table = struct.unpack_from('<2I', e7, recs + 48 * font + 40)
    magic, ver, items, toff, doff, size = struct.unpack_from('<6I', e8, 0)
    if (toff, doff, size) != (0x18, 0x18 + 8 * items, len(e8)):
        raise SystemExit('patch-splash: Entry 8 is not laid out as the stock one')
    recs8 = [struct.unpack_from('<2I', e8, toff + 8 * i) for i in range(items)]
    out = bytearray(e8)
    for slot, (gw, px) in sorted(glyphs.items()):
        if slot >= count or struct.unpack_from('<3I', e7, table + 12 * slot)[2] != 0xffffffff:
            raise SystemExit(f'patch-splash: slot {slot:#x} of {FONT_NAME.decode()} is not empty')
        out += b'\0' * ((-len(out)) & 3)
        recs8.append((len(px), len(out)))
        struct.pack_into('<3I', e7, table + 12 * slot, FONT_H, gw, len(recs8) - 1)
        out += px
    out += b'\0' * ((-len(out)) & 3)
    new_toff = len(out)
    out += b''.join(struct.pack('<2I', ln, off) for ln, off in recs8)
    struct.pack_into('<6I', out, 0, magic, ver, len(recs8), new_toff, doff, len(out))
    return bytes(e7), bytes(out)


def patch_text(l6ia_bytes, text, glyph_pngs=None, log=print):
    parts, glyph_pngs = clusters(text), dict(glyph_pngs or {})
    emoji = list(dict.fromkeys(p for p in parts if not p.isascii()))
    if len(emoji) > len(FREE_SLOTS):
        raise SystemExit(f'patch-splash: at most {len(FREE_SLOTS)} different emoji')
    slot = {e: FREE_SLOTS[i] for i, e in enumerate(emoji)}
    raw = b''.join(bytes([slot[p]]) if p in slot else p.encode('ascii') for p in parts) \
        if all(p in slot or p.isprintable() for p in parts) else b''
    if not raw or len(raw) >= len(TEXT_STOCK):
        raise SystemExit(f'patch-splash: the text must be 1 to {len(TEXT_STOCK) - 1} printable ASCII characters or emoji')
    e0 = bytearray(pa.get_entry_swapped(l6ia_bytes, 0))
    segs = pa._parse_e0_segments(e0)
    if segs[6][3] != STOCK_BASE:
        raise SystemExit('patch-splash: this patch is for the HX Stomp 3.80.0, not the XL')
    o = pa._e0_vaddr_to_foff(segs, TEXT_SITE, len(TEXT_STOCK))
    lit = pa._e0_vaddr_to_foff(segs, VERSION_LITERAL)
    if e0[o:o + len(TEXT_STOCK)] != TEXT_STOCK or struct.unpack_from('<I', e0, lit)[0] != TEXT_SITE + 16:
        raise SystemExit('patch-splash: the boot text is not the stock one (already patched?)')
    e0[o:o + len(TEXT_STOCK)] = raw.ljust(len(TEXT_STOCK), b'\0')
    struct.pack_into('<I', e0, lit, TEXT_SITE + len(raw))      # an empty string: nothing is appended
    replaced = {0: e0}
    if emoji:
        expect = ((FONT_SITE, b'\x01\x21'), (TEXT_COLOUR_LITERAL, struct.pack('<I', TEXT_COLOUR)))
        for va, stock in expect:
            fo = pa._e0_vaddr_to_foff(segs, va, len(stock))
            if e0[fo:fo + len(stock)] != stock:
                raise SystemExit(f'patch-splash: {va:#x} is not the stock code')
        fo = pa._e0_vaddr_to_foff(segs, struct.unpack_from('<I', e0, pa._e0_vaddr_to_foff(segs, FONT_NAME_LITERAL))[0], 17)
        if e0[fo:fo + 17] != FONT_NAME + b'\0':
            raise SystemExit('patch-splash: the font loader\'s 2nd font is not hx21_regularFont')
        struct.pack_into('<I', e0, pa._e0_vaddr_to_foff(segs, TEXT_COLOUR_LITERAL), 0xffffff)
        with tempfile.TemporaryDirectory() as tmp:
            glyphs = {slot[e]: glyph_from_png(glyph_pngs.get(e) or render_emoji(e, tmp)) for e in emoji}
        replaced[7], replaced[8] = add_glyphs(pa.get_entry_swapped(l6ia_bytes, 7), pa.get_entry_swapped(l6ia_bytes, 8), glyphs)
    new_l6ia, _, _ = l6ia.rebuild_archive(l6ia_bytes, {k: bytes(v) for k, v in replaced.items()})
    log(f'[+] Entry 0: boot text "{text}"' + (f', white; Entries 7 and 8: {len(emoji)} emoji glyph(s) in '
                                              f'{FONT_NAME.decode()} slots {[hex(slot[e]) for e in emoji]}' if emoji else ''))
    return new_l6ia


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    ex = sub.add_parser('export', help='write the splash now in the image to a PNG')
    ex.add_argument('input', help='.hxf or L6IA')
    ex.add_argument('png')
    apl = sub.add_parser('apply', help='replace the splash with a picture')
    apl.add_argument('input', help='.hxf or L6IA')
    apl.add_argument('output')
    apl.add_argument('--image', '--png', dest='image', required=True, help='a 320x240 PNG, or any picture sips can read')
    apl.add_argument('--fit', choices=('fill', 'fit'), default='fill',
                     help='for a converted picture: crop to fill the screen (default), or fit inside it on black')
    apl.add_argument('--donor', help='Stock .hxf of the unit, when input is a raw L6IA and output a .hxf')
    txt = sub.add_parser('text', help='replace the "Firmware 3.80.0" line under the picture')
    txt.add_argument('input', help='.hxf or L6IA')
    txt.add_argument('output')
    txt.add_argument('--text', required=True)
    txt.add_argument('--glyph', action='append', default=[], metavar='EMOJI=PNG', help='the picture for an emoji in --text')
    txt.add_argument('--donor', help='Stock .hxf of the unit, when input is a raw L6IA and output a .hxf')
    a = ap.parse_args()
    data, is_hxf = pa.load_l6ia_from_any(a.input)
    if a.cmd == 'export':
        e8, (off, ln) = splash_entries(data)
        rows = decode(e8[off:off + ln])
        write_png(a.png, rows)
        print(f'[+] Wrote {a.png} ({W}x{len(rows)})')
        return
    new = patch_splash(data, a.image, fit=a.fit) if a.cmd == 'apply' else \
        patch_text(data, a.text, dict(g.split('=', 1) for g in a.glyph))
    pa.save_l6ia_to_any(new, a.output, donor_hxf=a.input if is_hxf else a.donor)
    print(f'[+] Wrote {a.output}')


if __name__ == '__main__':
    main()
