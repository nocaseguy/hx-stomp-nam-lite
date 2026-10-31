#!/usr/bin/env python3
"""patch_menu.py - a new setting in the HX Stomp's Global Settings menu (HX Stomp 3.80.0 only).

A first step towards a custom firmware: the page that holds Rings LED and Tap Tempo LED has
an empty third slot. This puts parameter ID 28 there, named "Setting Test". ID 28 already has
a limits entry in the stock firmware (an integer, 0..127) and no name, so the unit never showed it.
The setting does nothing yet.

How the menu is built (Entry 0, the Cortex-M4 application, found by disassembly):
  - A category's page is u16[3] parameter IDs at page*3 + slot; 0x17e is an empty slot.
    This category's table is at 0x28e3b540: {25, 26, 0x17e}.
  - A parameter's label is "Page\\nName" in a char[27] array indexed by ID: the long names at
    0x28e25624 and the short ones at 0x28e26498 (the getter is 0x28d97634).
  - The limits of an ID are a jump table at 0x28e1ead4 (ID 28: integer 0..127).
  - The handler for a touched knob (0x28dceb30) tests this page's IDs one by one (`cmp r1, #0x19`,
    `cmp r1, #0x1a`) to find the slot, so a third ID is ignored. A cave added to the end of the
    code segment recognises ID 28 too and sends it down the slot-2 path the handler already has.

usage: patch_menu.py <in .hxf | .l6ia> <out .hxf | .l6ia> [--donor stock.hxf]
"""
import argparse
import struct
import sys

import l6ia
import patch_amp as pa

STOCK_BASE = 0x28d8fa80          # Entry 0 code segment of the HX Stomp 3.80.0 (the XL's differs)
NAMES_LONG, NAMES_SHORT, NAME_LEN = 0x28e25624, 0x28e26498, 27
PAGE_SLOT = 0x28e3b544           # third slot of the {25, 26, 0x17e} page
EMPTY_SLOT = 0x17e
NEW_ID = 28
LABEL = b'Setting\nTest'   # the menu shows the part after the newline first
# The knob handler's slot test: `cmp r1,#0x1a; bne exit` at HOOK; SLOT1 is the code after it for Tap LED,
# SLOT2 the handler's own "slot 2" path (movs r4,#2 ...), EXIT its return.
HOOK, HOOK_STOCK = 0x28dceb7e, bytes.fromhex('1a29 f8d1')   # cmp r1,#0x1a; bne EXIT
SLOT1, SLOT2, EXIT = 0x28dceb82, 0x28dcec66, 0x28dceb74


def menu_entry0(e0):
    """Entry 0 with the new setting: three edits in place, plus a 20-byte cave at the end of the code segment."""
    e0 = bytearray(e0)
    segs = pa._parse_e0_segments(e0)
    if segs[6][3] != STOCK_BASE:
        raise SystemExit(f'patch-menu: Entry 0 code is at {segs[6][3]:#x}; this patch is for the HX Stomp 3.80.0 '
                         f'({STOCK_BASE:#x}), not the XL')

    def off(va, n):
        return pa._e0_vaddr_to_foff(segs, va, n)

    for tab in (NAMES_LONG, NAMES_SHORT):
        o = off(tab + NAME_LEN * NEW_ID, NAME_LEN)
        if any(e0[o:o + NAME_LEN]):
            raise SystemExit(f'patch-menu: label {NEW_ID} at {tab:#x} is not empty (the patch is already applied?)')
        # sanity: the neighbours are real labels, so the arrays are where we think
        if e0[off(tab + NAME_LEN * 22, 8):][:8] != b'Main LCD':
            raise SystemExit(f'patch-menu: label array at {tab:#x} is not the stock one')
        e0[o:o + len(LABEL)] = LABEL
    o = off(PAGE_SLOT, 2)
    if struct.unpack_from('<H', e0, o)[0] != EMPTY_SLOT or struct.unpack_from('<2H', e0, o - 4) != (25, 26):
        raise SystemExit('patch-menu: the {25, 26, 0x17e} page is not at its stock address')
    struct.pack_into('<H', e0, o, NEW_ID)

    ho = off(HOOK, 4)
    if bytes(e0[ho:ho + 4]) != HOOK_STOCK or bytes(e0[off(SLOT2, 2):][:2]) != b'\x02\x24':
        raise SystemExit('patch-menu: the knob handler is not at its stock address')
    hdr, poff, slen, dst, nxt = segs[6]
    cave_va = dst + slen
    cave = (bytes.fromhex('1a29 01d1') + pa.thumb_bw(cave_va + 4, SLOT1)      # Tap LED: as stock
            + bytes.fromhex('1c29 01d1') + pa.thumb_bw(cave_va + 12, SLOT2)    # the new ID: slot 2
            + pa.thumb_bw(cave_va + 16, EXIT))                                 # anything else: as stock
    e0[ho:ho + 4] = pa.thumb_bw(HOOK, cave_va)
    out = bytearray(e0[:nxt]) + cave
    out += b'\x00' * ((-len(out)) & 3)
    struct.pack_into('<3I', out, hdr, slen + len(cave), dst, poff + slen + len(cave))
    struct.pack_into('<I', out, 4, len(out))
    if len(out) > pa.E0_MAX:
        raise SystemExit(f'patch-menu: Entry 0 would be {len(out):#x} bytes; its partition holds {pa.E0_MAX:#x}')
    return bytes(l6ia.fix_internal_crcs(bytes(out)))


def patch_menu(l6ia_bytes, log=print):
    e0 = pa.get_entry_swapped(l6ia_bytes, 0)
    new_l6ia, _, _ = l6ia.rebuild_archive(l6ia_bytes, {0: menu_entry0(e0)})
    log(f'[+] Entry 0: Global Settings > "Setting Test" (parameter {NEW_ID}) in the LED page')
    return new_l6ia


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('input')
    ap.add_argument('output')
    ap.add_argument('--donor', help='Stock .hxf of the unit, when input is a raw L6IA and output a .hxf')
    a = ap.parse_args()
    data, is_hxf = pa.load_l6ia_from_any(a.input)
    pa.save_l6ia_to_any(patch_menu(data), a.output, donor_hxf=a.input if is_hxf else a.donor)
    print(f'[+] Wrote {a.output}')


if __name__ == '__main__':
    main()
