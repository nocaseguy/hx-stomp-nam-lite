#!/usr/bin/env python3
"""patch_splash.py - the boot splash picture of the HX Stomp 3.80.0 firmware (the app's copy, not the bootloader's).

usage:
  patch_splash.py export <in.hxf|in.l6ia> <out.png>          # the splash now in the image, as a template
  patch_splash.py apply <in> <out> --png <320x181.png> [--donor stock.hxf]

The app's boot view draws the image store's HXStomp_Splash (Entry 8, 320x181) at
the top of the screen, the loading bar across it at y = 121, and the firmware
version in the 59 rows below it. The bootloader shows its own copy of the stock
splash before that, from power-on until the app starts; this tool leaves it alone.
PNG: 8-bit grey, RGB, palette or with alpha (blended onto black), not interlaced.
"""
import argparse
import hashlib
import struct
import zlib

import l6ia
import patch_amp as pa
from patch_menu import STOCK_BASE

NAME = b'HXStomp_Splash'
W, H = 320, 181
STOCK_MD5 = '102fdff9f8738b232273a27d581c49ae'     # the stock splash's pixels, Entry 8 item 527


def find_splash(e7, e8):
    """(offset, length) of the splash's pixels in Entry 8."""
    if struct.unpack_from('<I', e7, 0)[0] != 0x5b21255e or struct.unpack_from('<I', e8, 0)[0] != 0x2a5f3b5e:
        raise SystemExit('patch-splash: Entry 7/8 is not the image store')
    n, recs = struct.unpack_from('<I', e7, 0x10)[0], struct.unpack_from('<I', e7, 0x14)[0]
    for i in range(n):
        off, ln = struct.unpack_from('<2I', e7, 0x24 + 8 * i)
        if e7[off:off + ln] != NAME:
            continue
        idx, _, _, h, w, bpp = struct.unpack_from('<6I', e7, recs + 48 * i + 8)
        ln8, off8 = struct.unpack_from('<2I', e8, 0x18 + 8 * idx)
        if (w, h, bpp, ln8) != (W, H, 16, W * H * 2):
            raise SystemExit(f'patch-splash: {NAME.decode()} is {w}x{h}, {bpp} bpp, {ln8} bytes; expected {W}x{H} RGB565')
        return off8, ln8
    raise SystemExit(f'patch-splash: no {NAME.decode()} in the image store')


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


def write_png(path, rows):
    w, h = len(rows[0]), len(rows)
    raw = b''.join(b'\x00' + bytes(v for px in row for v in px) for row in rows)
    chunk = lambda kind, body: struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))
    open(path, 'wb').write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
                           + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))


def encode(rows):
    """RGB565 pixels as the image store keeps them: column by column, each from the bottom up."""
    out = bytearray(W * H * 2)
    for y, row in enumerate(rows):
        for x, (r, g, b) in enumerate(row):
            v = ((r * 31 + 127) // 255) << 11 | ((g * 63 + 127) // 255) << 5 | (b * 31 + 127) // 255
            struct.pack_into('<H', out, 2 * (x * H + H - 1 - y), v)
    return bytes(out)


def decode(px):
    rows = []
    for y in range(H):
        row = []
        for x in range(W):
            v = struct.unpack_from('<H', px, 2 * (x * H + H - 1 - y))[0]
            row.append(((v >> 11) * 255 // 31, (v >> 5 & 63) * 255 // 63, (v & 31) * 255 // 31))
        rows.append(row)
    return rows


def splash_entries(l6ia_bytes):
    e0 = pa.get_entry_swapped(l6ia_bytes, 0)
    if pa._parse_e0_segments(e0)[6][3] != STOCK_BASE:
        raise SystemExit('patch-splash: this patch is for the HX Stomp 3.80.0, not the XL')
    e7, e8 = pa.get_entry_swapped(l6ia_bytes, 7), pa.get_entry_swapped(l6ia_bytes, 8)
    return e8, find_splash(e7, e8)


def patch_splash(l6ia_bytes, png, log=print):
    w, h, rows = read_png(png)
    if (w, h) != (W, H):
        raise SystemExit(f'{png}: {w}x{h}; the splash is {W}x{H} (the version text takes the 59 rows below it)')
    e8, (off, ln) = splash_entries(l6ia_bytes)
    if hashlib.md5(e8[off:off + ln]).hexdigest() != STOCK_MD5:
        raise SystemExit('patch-splash: the splash is not the stock one (already patched?)')
    e8 = e8[:off] + encode(rows) + e8[off + ln:]
    new_l6ia, _, _ = l6ia.rebuild_archive(l6ia_bytes, {8: e8})
    log(f'[+] Entry 8: boot splash from {png}')
    return new_l6ia


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    ex = sub.add_parser('export', help='write the splash now in the image to a PNG')
    ex.add_argument('input', help='.hxf or L6IA')
    ex.add_argument('png')
    apl = sub.add_parser('apply', help='replace the splash with a 320x181 PNG')
    apl.add_argument('input', help='.hxf or L6IA')
    apl.add_argument('output')
    apl.add_argument('--png', required=True)
    apl.add_argument('--donor', help='Stock .hxf of the unit, when input is a raw L6IA and output a .hxf')
    a = ap.parse_args()
    data, is_hxf = pa.load_l6ia_from_any(a.input)
    if a.cmd == 'export':
        e8, (off, ln) = splash_entries(data)
        write_png(a.png, decode(e8[off:off + ln]))
        print(f'[+] Wrote {a.png} ({W}x{H})')
        return
    pa.save_l6ia_to_any(patch_splash(data, a.png), a.output, donor_hxf=a.input if is_hxf else a.donor)
    print(f'[+] Wrote {a.output}')


if __name__ == '__main__':
    main()
