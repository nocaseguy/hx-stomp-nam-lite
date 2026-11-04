#!/usr/bin/env python3
"""patch_splash.py - the boot splash picture of the HX Stomp 3.80.0 firmware (the app's copy, not the bootloader's).

usage:
  patch_splash.py export <in.hxf|in.l6ia> <out.png>          # the splash now in the image, as a template
  patch_splash.py apply <in> <out> --image <picture> [--fit fill|fit] [--donor stock.hxf]
  patch_splash.py text <in> <out> --text "CustomOS 3.80.0" [--donor stock.hxf]

The app's boot view draws the image store's HXStomp_Splash (Entry 8, 320x181) at
the top of the screen, the loading bar across it at y = 121, and the firmware
version in the 59 rows below it. A 320x240 PNG fills the whole screen instead: it
goes into the unused Screen_Boot image (320x240), and the boot view's image name
becomes Screen_Boot; the loading bar and the version are drawn over it.
With either picture, the text's glyphs are drawn without their black backgrounds.
The text under the picture is "   Firmware  " with "3.80.0" appended, next to the
firmware icon; `text` replaces the whole line (up to 23 characters).
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
        ln8, off8 = struct.unpack_from('<2I', e8, 0x18 + 8 * idx)
        if (w, h, bpp, ln8) != (W, h_want, 16, W * h_want * 2):
            raise SystemExit(f'patch-splash: {name.decode()} is {w}x{h}, {bpp} bpp, {ln8} bytes; '
                             f'expected {W}x{h_want} RGB565')
        return off8, ln8
    raise SystemExit(f'patch-splash: no {name.decode()} in the image store')


def read_png(path):
    """(width, height, rows of (r, g, b) tuples) from an 8-bit, non-interlaced PNG."""
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
                rgb, alpha = palette[px[0]], trns[px[0]] if px[0] < len(trns) else 255
            elif ctype in (0, 4):
                rgb, alpha = (px[0],) * 3, px[1] if ctype == 4 else 255
            else:
                rgb, alpha = tuple(px[:3]), px[3] if ctype == 6 else 255
            row.append(tuple(v * alpha // 255 for v in rgb))
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


def patch_text(l6ia_bytes, text, log=print):
    raw = text.encode('ascii', 'strict') if text.isprintable() else b''
    if not raw or len(raw) >= len(TEXT_STOCK):
        raise SystemExit(f'patch-splash: the text must be 1 to {len(TEXT_STOCK) - 1} printable ASCII characters')
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
    new_l6ia, _, _ = l6ia.rebuild_archive(l6ia_bytes, {0: bytes(e0)})
    log(f'[+] Entry 0: boot text "{text}"')
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
    txt.add_argument('--donor', help='Stock .hxf of the unit, when input is a raw L6IA and output a .hxf')
    a = ap.parse_args()
    data, is_hxf = pa.load_l6ia_from_any(a.input)
    if a.cmd == 'export':
        e8, (off, ln) = splash_entries(data)
        rows = decode(e8[off:off + ln])
        write_png(a.png, rows)
        print(f'[+] Wrote {a.png} ({W}x{len(rows)})')
        return
    new = patch_splash(data, a.image, fit=a.fit) if a.cmd == 'apply' else patch_text(data, a.text)
    pa.save_l6ia_to_any(new, a.output, donor_hxf=a.input if is_hxf else a.donor)
    print(f'[+] Wrote {a.output}')


if __name__ == '__main__':
    main()
