"""image_store.py - the image store of the HX Stomp 3.80.0 firmware: Entry 7 names the images and fonts, Entry 8 holds their pixels.

Entry 7 (little-endian words): +8 its size, +0xc the names' offset (0x24), +0x10 their count, +0x14 the records' offset, +0x18
their count; a (name offset, name length) pair per name. The firmware streams it and takes every offset and count from the header, so
a build that adds images appends a copy of the records with them and repoints +0x14 and +0x18: they have no name, only an index.
A record is 48 bytes: +8 its Entry 8 item, then two words, height, width, bits per pixel; a font's has +40 its glyph count and the
offset of its glyph table, 12 bytes a glyph: (height, width, Entry 8 item), the item 0xffffffff for an empty slot.
Entry 8: a header of six words (magic, version, item count, item table offset, data offset, size), then the item table, a
(length, offset) pair per item, and the items. Stock has the table at 0x18; a build that adds items moves it, so read word 3.
"""
import math
import struct
from dataclasses import dataclass

E7_MAGIC, E8_MAGIC = 0x5b21255e, 0x2a5f3b5e
RECORD = 48
EMPTY_GLYPH = 0xffffffff


@dataclass(frozen=True)
class Image:
    item: int               # its Entry 8 item
    width: int
    height: int
    bpp: int
    offset: int             # its pixels in Entry 8
    length: int


def check(e7, e8):
    if struct.unpack_from('<I', e7, 0)[0] != E7_MAGIC or struct.unpack_from('<I', e8, 0)[0] != E8_MAGIC:
        raise SystemExit('image-store: Entry 7/8 is not the image store')


def names(e7):
    n = struct.unpack_from('<I', e7, 0x10)[0]
    return [bytes(e7[o:o + ln]) for o, ln in (struct.unpack_from('<2I', e7, 0x24 + 8 * i) for i in range(n))]


def record(e7, name):
    """The offset in Entry 7 of the record named name."""
    try:
        i = names(e7).index(name)
    except ValueError:
        raise SystemExit(f'image-store: no {name.decode()} in the image store') from None
    return struct.unpack_from('<I', e7, 0x14)[0] + RECORD * i


def record_at(e7, idx):
    """The offset in Entry 7 of record idx."""
    table, count = struct.unpack_from('<2I', e7, 0x14)
    if not 0 <= idx < count:
        raise SystemExit(f'image-store: Entry 7 has no record {idx} (it has {count})')
    return table + RECORD * idx


def item(e8, idx):
    """(offset, length) of Entry 8's item idx."""
    count, table = struct.unpack_from('<2I', e8, 8)
    if not 0 <= idx < count:
        raise SystemExit(f'image-store: Entry 8 has no item {idx} (it has {count})')
    ln, off = struct.unpack_from('<2I', e8, table + 8 * idx)
    return off, ln


def _image(e7, e8, rec):
    check(e7, e8)
    idx, _, _, h, w, bpp = struct.unpack_from('<6I', e7, rec + 8)
    return Image(idx, w, h, bpp, *item(e8, idx))


def image(e7, e8, name):
    return _image(e7, e8, record(e7, name))


def image_at(e7, e8, idx):
    """The image of Entry 7's record idx, the index an image widget takes."""
    return _image(e7, e8, record_at(e7, idx))


def font(e7, name):
    """(glyph count, offset of the glyph table in Entry 7) of the font named name."""
    return struct.unpack_from('<2I', e7, record(e7, name) + 40)


def glyph(e7, table, slot):
    """(height, width, Entry 8 item) of a font's glyph slot."""
    return struct.unpack_from('<3I', e7, table + 12 * slot)


def cell_height(e7, name):
    """The height every drawn glyph of the font has."""
    count, table = font(e7, name)
    heights = {glyph(e7, table, s)[0] for s in range(count) if glyph(e7, table, s)[2] != EMPTY_GLYPH}
    if len(heights) != 1:
        raise SystemExit(f'image-store: the glyphs of {name.decode()} have heights {sorted(heights)}, not one cell height')
    return heights.pop()


def pixel(r, g, b):
    """A pixel as the screen takes it: blue in the top 5 bits, red in the bottom 5 (stock Play_Red is 0x001f)."""
    return ((b * 31 + 127) // 255) << 11 | ((g * 63 + 127) // 255) << 5 | (r * 31 + 127) // 255


def pixel_rgb(v):
    return ((v & 31) * 255 // 31, (v >> 5 & 63) * 255 // 63, (v >> 11) * 255 // 31)


def append_items(e8, items):
    """Entry 8 with items added after its end and a copy of the item table after them: no byte of the original moves."""
    magic, ver, count, table, doff, _ = struct.unpack_from('<6I', e8, 0)
    recs = [struct.unpack_from('<2I', e8, table + 8 * i) for i in range(count)]
    out = bytearray(e8)
    for data in items:
        out += b'\0' * (-len(out) % 4)
        recs.append((len(data), len(out)))
        out += data
    out += b'\0' * (-len(out) % 4)
    new_table = len(out)
    out += b''.join(struct.pack('<2I', ln, off) for ln, off in recs)
    struct.pack_into('<6I', out, 0, magic, ver, len(recs), new_table, doff, len(out))
    return bytes(out)


def append_records(e7, records):
    """Entry 7 with a copy of its records and then records (48 bytes each) after its end, the header pointing at the copy: no byte
    of the original moves, so every name, font and glyph table stays where it was."""
    table, count = struct.unpack_from('<2I', e7, 0x14)
    out = bytearray(e7) + b'\0' * (-len(e7) % 4)
    new_table = len(out)
    out += e7[table:table + RECORD * count] + b''.join(records)
    struct.pack_into('<I', out, 8, len(out))
    struct.pack_into('<2I', out, 0x14, new_table, count + len(records))
    return bytes(out)


def peak(pixels):
    """The brightest channel of RGB565 pixels, 0..1."""
    vs = struct.unpack(f'<{len(pixels) // 2}H', pixels)
    return max((max((v & 31) / 31, (v >> 5 & 63) / 63, (v >> 11) / 31) for v in vs), default=0)


def scaled(pixels, k):
    """RGB565 pixels with each channel times k, rounded and capped at its maximum."""
    def one(v):
        return min(31, round((v >> 11) * k)) << 11 | min(63, round((v >> 5 & 63) * k)) << 5 | min(31, round((v & 31) * k))
    vs = struct.unpack(f'<{len(pixels) // 2}H', pixels)
    return struct.pack(f'<{len(vs)}H', *(one(v) for v in vs))


def _channels(v):
    return v >> 11, v >> 5 & 63, v & 31


def trimmed(pixels, w, h):
    """(pixels, w, h) of an image (column by column from the bottom) without its all-black border rows and columns."""
    vs = struct.unpack(f'<{w * h}H', pixels)
    cols = [x for x in range(w) if any(vs[x * h:(x + 1) * h])]
    rows = [y for y in range(h) if any(vs[x * h + y] for x in range(w))]
    if not cols:
        return pixels, w, h
    x0, x1, y0, y1 = cols[0], cols[-1] + 1, rows[0], rows[-1] + 1
    out = [vs[x * h + y] for x in range(x0, x1) for y in range(y0, y1)]
    return struct.pack(f'<{len(out)}H', *out), x1 - x0, y1 - y0


def resized(pixels, w, h, nw, nh):
    """An image (column by column from the bottom) at nw x nh, each new pixel the average of the old ones it covers, by area."""
    vs = [_channels(v) for v in struct.unpack(f'<{w * h}H', pixels)]
    sx, sy = w / nw, h / nh
    out = []
    for x in range(nw):
        x0, x1 = x * sx, (x + 1) * sx
        for y in range(nh):
            y0, y1 = y * sy, (y + 1) * sy
            acc, total = [0, 0, 0], 0
            for xx in range(int(x0), min(w, math.ceil(x1))):
                for yy in range(int(y0), min(h, math.ceil(y1))):
                    a = (min(x1, xx + 1) - max(x0, xx)) * (min(y1, yy + 1) - max(y0, yy))
                    if a > 0:
                        acc = [s + a * c for s, c in zip(acc, vs[xx * h + yy])]
                        total += a
            b, g, r = (round(s / total) for s in acc)
            out.append(b << 11 | g << 5 | r)
    return struct.pack(f'<{len(out)}H', *out)
