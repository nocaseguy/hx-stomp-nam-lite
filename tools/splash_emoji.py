"""splash_emoji.py - emoji for the boot line (tools/features/splash.py): text split into emoji, and an emoji's picture as a glyph.

A glyph is the picture's opaque part, scaled to EMOJI_H rows (1 px beyond the capitals of hx21_regularFont, rows 1..16 of its
21 px cell) at the top of the cell, blended onto black, packed as image_store.pixel() column by column from the bottom.
Pixel 0 is transparent to the glyph blitters, so opaque black is stored as 1. Without a picture for an emoji,
tools/emoji_png.swift renders one from Apple Color Emoji (macOS).
"""
import os
import shutil
import struct
import subprocess

import image_store
import patch_splash as ps

EMOJI_TOP, EMOJI_H, EMOJI_MAX_W = 0, 18, 21
EMOJI_PNG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'emoji_png.swift')


def clusters(text):
    """Text split into ASCII characters and emoji (a non-ASCII code point with its joiners, modifiers and selectors)."""
    out = []
    for ch in text:
        cp = ord(ch)
        joins = cp in (0x200d, 0xfe0e, 0xfe0f, 0x20e3) or 0x1f3fb <= cp <= 0x1f3ff or 0xe0020 <= cp <= 0xe007f
        if out and not out[-1].isascii() and (joins or out[-1][-1] == '‍'):
            out[-1] += ch
        else:
            out.append(ch)
    return out


def glyph_from_png(path, cell_h):
    """(width, pixels) of a glyph cell_h tall: the PNG's opaque part, scaled, blended onto black; 0 = transparent."""
    w, h, rows = ps.read_png(path, alpha=True)
    ys = [y for y in range(h) if any(px[3] for px in rows[y])]
    xs = [x for x in range(w) if any(rows[y][x][3] for y in range(h))]
    if not ys:
        raise SystemExit(f'{path}: fully transparent')
    x0, y0, cw, ch = xs[0], ys[0], xs[-1] + 1 - xs[0], ys[-1] + 1 - ys[0]
    scale = EMOJI_H / max(ch, cw * EMOJI_H / EMOJI_MAX_W)
    gw, gh = max(1, round(cw * scale)), max(1, round(ch * scale))
    top = EMOJI_TOP + (EMOJI_H - gh) // 2
    out = bytearray(gw * cell_h * 2)
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
            v = image_store.pixel(*(c // (255 * n) for c in acc[:3]))
            struct.pack_into('<H', out, 2 * (gx * cell_h + cell_h - 1 - (top + gy)), v or 1)
    return gw, bytes(out)


def render_emoji(emoji, tmp):
    """A PNG of emoji rendered by tools/emoji_png.swift (macOS), in the directory tmp."""
    if not shutil.which('swift'):
        raise SystemExit(f'splash: no picture for {emoji!r}; give one in HX_SPLASH_GLYPHS (build.py --splash-glyph '
                         f'{emoji}=file.png), or build on macOS, which renders it')
    out = os.path.join(tmp, f'emoji_{"_".join(f"{ord(c):x}" for c in emoji)}.png')
    r = subprocess.run(['swift', EMOJI_PNG, emoji, out], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f'splash: rendering {emoji!r} failed: {r.stderr.strip() or r.stdout.strip()}')
    return out
