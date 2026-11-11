#!/usr/bin/env python3
"""icon_library.py - the icon library: a page that draws every icon-like image of your stock firmware, grouped by whether Global
Settings shows it, with each image's size and index, for picking a feature's ICON (docs/icons.md).

usage:
  icon_library.py <stock.hxf|.l6ia> [out.html]      # default build/icons.html

The pictures are Line 6's, so the page is made on your computer from your own firmware file and never committed.
"""
import argparse
import base64
import html
import os
import struct
import zlib

import features
import image_store
import patch_amp as pa
import patch_menu as pm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(ROOT, 'tools', 'icon_library.html')
SECTIONS = ('InsOuts', 'Prefs', 'Footswitches', 'EXPPedals', 'MIDITempo', 'Displays')
FIT = (30, 29)      # the stock section icons' largest width and height: a bigger icon may run into the title


def groups(names):
    """{group: [image name]}: the section icons by the title and the section strip, which Global Settings draws; the section-style
    pictures it never draws; and every other Icon_ image."""
    title = [f'Icon_{s}' for s in SECTIONS]
    strip = [f'Global_{s}{v}' for s in SECTIONS for v in ('', 'Sel')]
    unused = [f'Icon_{s}Sel' for s in SECTIONS] + sorted(n for n in names if n.startswith('Setup_'))
    shown = set(title + strip + unused)
    return {'title': title, 'strip': strip, 'unused': unused,
            'others': sorted(n for n in names if n.startswith('Icon_') and n not in shown)}


def png(width, height, pixels):
    """An RGBA PNG of image-store pixels (column by column, each from the bottom up); pixel 0 is transparent, as on the screen."""
    rows = []
    for y in range(height):
        row = bytearray(b'\0')
        for x in range(width):
            v = pixels[x * height + height - 1 - y]
            row += bytes((*image_store.pixel_rgb(v), 255 if v else 0))
        rows.append(bytes(row))
    chunk = lambda kind, body: struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>2I5B', width, height, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(b''.join(rows), 9)) + chunk(b'IEND', b''))


def tags(mods):
    """Image name -> what CustomOS uses it for: the default page icon and each feature's ICON."""
    out = {'Icon_Displays': ['CustomOS default']}
    for m in mods:
        if getattr(m, 'ICON', None):
            out.setdefault(m.ICON, []).append(pm.check_title(m).decode())
    return out


def page(l6ia, mods=None):
    e7, e8 = pa.get_entry_swapped(l6ia, 7), pa.get_entry_swapped(l6ia, 8)
    names = [n.decode() for n in image_store.names(e7)]
    used = tags(features.load() if mods is None else mods)
    fits = 0

    def tile(name, count=False):
        nonlocal fits
        im = image_store.image(e7, e8, name.encode())
        px = struct.unpack_from(f'<{im.width * im.height}H', e8, im.offset)
        fit = im.width <= FIT[0] and im.height <= FIT[1]
        fits += fit and count
        uri = 'data:image/png;base64,' + base64.b64encode(png(im.width, im.height, px)).decode()
        marks = ''.join(f'<span class="tag">{html.escape(t)}</span>' for t in used.get(name, ()))
        if name in pm.ICONS:
            marks += '<span class="tag in">in ICONS</span>'
        return (f'<figure class="tile{" fits" if fit else ""}" data-name="{html.escape(name.lower())}"><div class="lcd">'
                f'<img src="{uri}" width="{im.width * 2}" height="{im.height * 2}" alt="{html.escape(name)}"></div><figcaption>'
                f'<span class="nm">{html.escape(name)}</span><span class="meta">{im.width}×{im.height} · #{names.index(name):#x}</span>'
                f'{marks}</figcaption></figure>')

    out = open(TEMPLATE).read()
    for key, group in groups(names).items():
        out = out.replace('{{%s}}' % key.upper(), '<div class="grid">' + ''.join(tile(n, key == 'others') for n in group) + '</div>')
        if key == 'others':
            out = out.replace('{{N_OTHERS}}', str(len(group)))
    return out.replace('{{N_FITS}}', str(fits)).replace('{{N_IMAGES}}', str(len(names)))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('input', help='stock .hxf or L6IA')
    ap.add_argument('output', nargs='?', default=os.path.join(ROOT, 'build', 'icons.html'))
    a = ap.parse_args()
    data, _ = pa.load_l6ia_from_any(a.input)
    os.makedirs(os.path.dirname(os.path.abspath(a.output)), exist_ok=True)
    with open(a.output, 'w') as f:
        f.write(page(data))
    print(f'[+] Wrote {a.output}')


if __name__ == '__main__':
    main()
