#!/usr/bin/env python3
"""patch_splash.py - pictures for the HX Stomp's boot screen: reading, converting and packing them (tools/features/splash.py
builds them in with build.py --splash), and exporting the picture an image has now.

usage:
  patch_splash.py export <in.hxf|in.l6ia> <out.png>          # the boot picture now in the image, as a template

Picture: a 320x240 (or 320x181) PNG, 8-bit grey, RGB, palette or with alpha (blended
onto black), not interlaced, is used as it is. Any other picture (JPEG, HEIC, PNG of
another size...) is converted on macOS with sips to sRGB at 320x240: scaled to cover
the screen and cropped at the centre (fill, the default), or scaled to fit inside it
on black (fit).
"""
import argparse
import os
import shutil
import struct
import subprocess
import tempfile
import zlib

import image_store
import patch_amp as pa

W = 320
# name, height, MD5 of the stock pixels
SPLASH = (b'HXStomp_Splash', 181, '102fdff9f8738b232273a27d581c49ae')
FULL = (b'Screen_Boot', 240, '051d4adbbbcdf074b62077e549ac1e20')
SRGB = '/System/Library/ColorSync/Profiles/sRGB Profile.icc'


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


def encode(rows):
    """Pixels as the image store keeps them: column by column, each from the bottom up."""
    H = len(rows)
    out = bytearray(W * H * 2)
    for y, row in enumerate(rows):
        for x, (r, g, b) in enumerate(row):
            struct.pack_into('<H', out, 2 * (x * H + H - 1 - y), image_store.pixel(r, g, b))
    return bytes(out)


def decode(px):
    H = len(px) // (2 * W)
    rows = []
    for y in range(H):
        row = []
        for x in range(W):
            row.append(image_store.pixel_rgb(struct.unpack_from('<H', px, 2 * (x * H + H - 1 - y))[0]))
        rows.append(row)
    return rows


def drawn_image(l6ia_bytes):
    """(name, pixels) of the picture the boot view draws: Screen_Boot once the splash feature has renamed it."""
    from features.splash import NAME_SITE
    e0 = pa.get_entry_swapped(l6ia_bytes, 0)
    o = pa._e0_vaddr_to_foff(pa._parse_e0_segments(e0), NAME_SITE, 16)
    name = FULL[0] if e0[o:o + 16] == FULL[0].ljust(16, b'\0') else SPLASH[0]
    e7, e8 = pa.get_entry_swapped(l6ia_bytes, 7), pa.get_entry_swapped(l6ia_bytes, 8)
    img = image_store.image(e7, e8, name)
    return name, e8[img.offset:img.offset + img.length]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    ex = sub.add_parser('export', help='write the boot picture now in the image to a PNG')
    ex.add_argument('input', help='.hxf or L6IA')
    ex.add_argument('png')
    a = ap.parse_args()
    data, _ = pa.load_l6ia_from_any(a.input)
    _, px = drawn_image(data)
    rows = decode(px)
    write_png(a.png, rows)
    print(f'[+] Wrote {a.png} ({W}x{len(rows)})')


if __name__ == '__main__':
    main()
