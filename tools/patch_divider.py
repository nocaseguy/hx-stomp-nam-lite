#!/usr/bin/env python3
"""patch_divider.py - the Home screen's divider line on the HX Stomp 3.80.0 firmware (experiment: 2 px thick, green), not the XL."""
import argparse
import struct

import l6ia
import patch_amp as pa
from patch_menu import STOCK_BASE

# The divider is four 80 px segments: the selected one is white and 2 px, the others grey (0x666666, a literal) and 1 px.
GREEN = 0x00ff00
THICKNESS_SITE, THICKNESS_STOCK = 0x28dc8808, bytes.fromhex('4ff00108')      # mov.w r8,#1: the height of an unselected segment
SELECTED_SITE, SELECTED_STOCK = 0x28dc8b22, bytes.fromhex('6ff07f41')        # mvn r1,#0xff000000: white for the selected segment
GREY_LITERAL, GREY_STOCK = 0x28dc8b58, struct.pack('<I', 0x666666)
THICKNESS = 2


def divider_entry0(e0):
    """Entry 0 with the divider drawn 2 px thick in green, edited in place."""
    e0 = bytearray(e0)
    segs = pa._parse_e0_segments(e0)
    if segs[6][3] != STOCK_BASE:
        raise SystemExit(f'patch-divider: Entry 0 code is at {segs[6][3]:#x}; this patch is for the HX Stomp 3.80.0 '
                         f'({STOCK_BASE:#x}), not the XL')

    def put(va, stock, new, what):
        o = pa._e0_vaddr_to_foff(segs, va, len(stock))
        if bytes(e0[o:o + len(stock)]) != stock:
            raise SystemExit(f'patch-divider: {what} is not at its stock address')
        e0[o:o + len(new)] = new

    put(THICKNESS_SITE, THICKNESS_STOCK, struct.pack('<2H', 0xf04f, 0x0800 | THICKNESS), 'the divider height')
    put(SELECTED_SITE, SELECTED_STOCK, bytes.fromhex('4ff47f41'), 'the selected segment colour')    # mov.w r1,#0xff00
    put(GREY_LITERAL, GREY_STOCK, struct.pack('<I', GREEN), 'the divider colour')
    return bytes(l6ia.fix_internal_crcs(bytes(e0)))


def patch_divider(l6ia_bytes, log=print):
    e0 = pa.get_entry_swapped(l6ia_bytes, 0)
    new_l6ia, _, _ = l6ia.rebuild_archive(l6ia_bytes, {0: divider_entry0(e0)})
    log('[+] Entry 0: Home screen divider line (2 px, green)')
    return new_l6ia


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('input', help='.hxf or L6IA')
    ap.add_argument('output')
    ap.add_argument('--donor', help='Stock .hxf of the unit, when input is a raw L6IA and output a .hxf')
    a = ap.parse_args()
    data, is_hxf = pa.load_l6ia_from_any(a.input)
    pa.save_l6ia_to_any(patch_divider(data), a.output, donor_hxf=a.input if is_hxf else a.donor)
    print(f'[+] Wrote {a.output}')


if __name__ == '__main__':
    main()
