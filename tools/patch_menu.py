#!/usr/bin/env python3
"""patch_menu.py - new Global Settings entries (a test setting, Tuner Activation) in the HX Stomp 3.80.0 firmware, not the XL."""
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
# The LED page's knob handler finds the slot by comparing the ID with 0x19 and 0x1a, so a third ID needs a cave.
HOOK, HOOK_STOCK = 0x28dceb7e, bytes.fromhex('1a29 f8d1')   # cmp r1,#0x1a; bne EXIT
SLOT1, SLOT2, EXIT = 0x28dceb82, 0x28dcec66, 0x28dceb74

# Tuner Activation: labels are 'Page\nName' char[27] per ID, shown name first; limits come from the tbh table at 0x28e1ead4
TUNER_ID = 29
TUNER_LABEL = b'Activation\nTuner'
TUNER_SLOT = 0x28e3b558          # page 1, slot 1 of the Footswitches table {17, 97, 98, 99, 0x17e, 0x17e}
LIMITS_TAB = 0x28e1ebbc          # tbh table at 0x28e1ead4: halfword (ID - 1), target = LIMITS_TAB + 2 * h
LIMITS_STOCK, LIMITS_ENUM2 = 0x00a3, 0x0055   # ID 29's stock entry; ID 18's (integer 0..1)
TEXT_FN, TEXT_FN_STOCK = 0x28d9775c, bytes.fromhex('30b5 85b0')   # push {r4,r5,lr}; sub sp,#0x14
TEXT_FN_CONT = 0x28d97760        # the next instruction (movs r4,#0)
STRCPY = 0x28e24c78              # the copy the function's own cases use: (dst r0, src r1, len r2)
TUNER_VALUES = (b'Hold', b'Press')
VALUE_LEN = 20                   # the function's string tables have 20 bytes per value


# The footswitch case for function TAP/Tunr ends in a tail call to the tap-tempo core; the guard test is the one the tuner case uses.
TAP_SITE, TAP_SITE_STOCK, TAP_CORE = 0x28dd1656, bytes.fromhex('caf7 a7bc'), 0x28d9bfa8
FS_GUARD, REQUEST_TUNER, GET_VALUE = 0x28d96134, 0x28d96588, 0x28e1f844
TAP_CAVE_LEN = 0x2c


def thumb_bl(src, dst):
    hw1, hw2 = struct.unpack('<2H', pa.thumb_bw(src, dst))
    return struct.pack('<2H', hw1, hw2 | 0x4000)


def thumb_movt(rd, imm16):
    hw1, hw2 = struct.unpack('<2H', pa._encode_thumb_movw(rd, imm16))
    return struct.pack('<2H', hw1 | 0x80, hw2)


def tap_cave(cave_va):
    """In Press mode the tap becomes a tuner request; otherwise the stock tap-tempo core runs."""
    h = lambda *hws: b''.join(struct.pack('<H', x) for x in hws)
    code = (h(0xb510, 0xb082, 0x201d, 0x4669) + thumb_bl(cave_va + 8, GET_VALUE)   # push {r4,lr}; Tuner Activation into [sp+4]
            + h(0x9801, 0xb002, 0x2801, 0xd107)                                    # Press? else to stock
            + h(0x2005) + thumb_bl(cave_va + 0x16, FS_GUARD) + h(0x2800, 0xd101)   # the tuner case's guard
            + thumb_bl(cave_va + 0x1e, REQUEST_TUNER) + h(0xbd10)                  # request the tuner; pop {r4,pc}
            + bytes.fromhex('bde8 1040') + pa.thumb_bw(cave_va + 0x28, TAP_CORE))  # stock: pop.w {r4,lr}; b.w tap core
    assert len(code) == TAP_CAVE_LEN, hex(len(code))
    return code


def text_cave(cave_va):
    """Runs the two instructions the hook replaced, then answers TUNER_ID with its value string and leaves other IDs to stock."""
    table = cave_va + 0x2c
    code = (bytes.fromhex('30b5 85b0')           # push {r4,r5,lr}; sub sp,#0x14
            + struct.pack('<H', 0x2800 | TUNER_ID) + bytes.fromhex('01d0')    # cmp r0,#ID; beq mine
            + pa.thumb_bw(cave_va + 8, TEXT_FN_CONT)
            + bytes.fromhex('4c68 1046 1a46')    # mine: ldr r4,[r1,#4]; mov r0,r2 (dst); mov r2,r3 (len)
            + pa._encode_thumb_movw(1, table & 0xffff) + thumb_movt(1, table >> 16)
            + bytes.fromhex('04eb8404 01eb8401')  # add r4,r4,r4,lsl #2; add r1,r1,r4,lsl #2 (table + 20 * value)
            + thumb_bl(cave_va + 0x22, STRCPY)
            + bytes.fromhex('0020 05b0 30bd'))   # movs r0,#0; add sp,#0x14; pop {r4,r5,pc}
    assert len(code) == 0x2c
    return code + b''.join(v.ljust(VALUE_LEN, b'\0') for v in TUNER_VALUES)


def menu_entry0(e0):
    """Entry 0 with the two new settings: edits in place, plus two caves at the end of the code segment."""
    e0 = bytearray(e0)
    segs = pa._parse_e0_segments(e0)
    if segs[6][3] != STOCK_BASE:
        raise SystemExit(f'patch-menu: Entry 0 code is at {segs[6][3]:#x}; this patch is for the HX Stomp 3.80.0 '
                         f'({STOCK_BASE:#x}), not the XL')

    def off(va, n):
        return pa._e0_vaddr_to_foff(segs, va, n)

    for tab in (NAMES_LONG, NAMES_SHORT):
        # sanity: the neighbours are real labels, so the arrays are where we think
        if e0[off(tab + NAME_LEN * 22, 8):][:8] != b'Main LCD':
            raise SystemExit(f'patch-menu: label array at {tab:#x} is not the stock one')
        for pid, label in ((NEW_ID, LABEL), (TUNER_ID, TUNER_LABEL)):
            o = off(tab + NAME_LEN * pid, NAME_LEN)
            if any(e0[o:o + NAME_LEN]):
                raise SystemExit(f'patch-menu: label {pid} at {tab:#x} is not empty (the patch is already applied?)')
            e0[o:o + len(label)] = label
    o = off(PAGE_SLOT, 2)
    if struct.unpack_from('<H', e0, o)[0] != EMPTY_SLOT or struct.unpack_from('<2H', e0, o - 4) != (25, 26):
        raise SystemExit('patch-menu: the {25, 26, 0x17e} page is not at its stock address')
    struct.pack_into('<H', e0, o, NEW_ID)

    o = off(TUNER_SLOT, 2)
    if struct.unpack_from('<3H', e0, o - 2) != (99, EMPTY_SLOT, EMPTY_SLOT):
        raise SystemExit('patch-menu: the Footswitches page is not at its stock address')
    struct.pack_into('<H', e0, o, TUNER_ID)
    o = off(LIMITS_TAB + 2 * (TUNER_ID - 1), 2)
    if struct.unpack_from('<H', e0, o)[0] != LIMITS_STOCK or \
            struct.unpack_from('<H', e0, off(LIMITS_TAB + 2 * 17, 2))[0] != LIMITS_ENUM2:
        raise SystemExit('patch-menu: the limits table is not at its stock address')
    struct.pack_into('<H', e0, o, LIMITS_ENUM2)
    fo = off(TEXT_FN, 4)
    if bytes(e0[fo:fo + 4]) != TEXT_FN_STOCK:
        raise SystemExit('patch-menu: the value-text function is not at its stock address')

    ho = off(HOOK, 4)
    if bytes(e0[ho:ho + 4]) != HOOK_STOCK or bytes(e0[off(SLOT2, 2):][:2]) != b'\x02\x24':
        raise SystemExit('patch-menu: the knob handler is not at its stock address')
    hdr, poff, slen, dst, nxt = segs[6]
    cave_va = dst + slen
    cave = (bytes.fromhex('1a29 01d1') + pa.thumb_bw(cave_va + 4, SLOT1)      # Tap LED: as stock
            + bytes.fromhex('1c29 01d1') + pa.thumb_bw(cave_va + 12, SLOT2)    # the new ID: slot 2
            + pa.thumb_bw(cave_va + 16, EXIT))                                 # anything else: as stock
    e0[ho:ho + 4] = pa.thumb_bw(HOOK, cave_va)
    text_va = cave_va + len(cave)
    cave += text_cave(text_va)
    e0[fo:fo + 4] = pa.thumb_bw(TEXT_FN, text_va)
    ts = off(TAP_SITE, 4)
    if bytes(e0[ts:ts + 4]) != TAP_SITE_STOCK:
        raise SystemExit('patch-menu: the tap-tempo call is not at its stock address')
    tap_va = cave_va + len(cave)
    cave += tap_cave(tap_va)
    e0[ts:ts + 4] = pa.thumb_bw(TAP_SITE, tap_va)
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
    log(f'[+] Entry 0: Global Settings > "Setting Test" (parameter {NEW_ID}) in the LED page; '
        f'Footswitches > "Tuner Activation" (parameter {TUNER_ID}): Hold / Press')
    return new_l6ia


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('input')
    ap.add_argument('output')
    ap.add_argument('--donor', help='Stock .hxf of the unit, when input is a raw L6IA and output a .hxf')
    a = ap.parse_args()
    data, is_hxf = pa.load_l6ia_from_any(a.input)
    pa.save_l6ia_to_any(patch_menu(data), a.output, donor_hxf=a.input if is_hxf else a.donor)
    print(f'[+] Wrote {a.output}')


if __name__ == '__main__':
    main()
