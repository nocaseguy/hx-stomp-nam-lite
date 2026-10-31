#!/usr/bin/env python3
"""patch_menu.py - Global Settings additions for the HX Stomp 3.80.0 firmware (a CustomOS section with Tuner Activation and Lock Tuner Settings), not the XL."""
import argparse
import struct

import l6ia
import patch_amp as pa

STOCK_BASE = 0x28d8fa80          # Entry 0 code segment of the HX Stomp 3.80.0 (the XL's differs)
NAMES_LONG, NAMES_SHORT, NAME_LEN = 0x28e25624, 0x28e26498, 27   # 'Page\nName' char[27] per parameter ID, shown name first
EMPTY_SLOT = 0x17e

# Parameter IDs of the CustomOS settings (stock labels stay within 8 characters before the newline and 9 after it); limits come from the tbh table at 0x28e1ead4 (ID 18's entry is an enum 0..1).
TUNER_ID, TUNER_LABEL, TUNER_VALUES = 29, b'Activate\nTuner', (b'Hold', b'Press')
LOCK_ID, LOCK_LABEL, LOCK_VALUES = 104, b'Settings\nLock Tnr', (b'Off', b'On')
LIMITS_TAB_LOW, LIMITS_TAB_HIGH = 0x28e1ebbc, 0x28e1eaf0         # tbh bases for IDs 1..0x37 and 0x3f..0x9a
ENUM01_TARGET = 0x28e1ec66       # limits code for an integer 0..1, default 0
TEXT_FN, TEXT_FN_STOCK, TEXT_FN_CONT = 0x28d9775c, bytes.fromhex('30b5 85b0'), 0x28d97760   # (ID, value) -> text; push {r4,r5,lr}; sub sp,#0x14
STRCPY, VALUE_LEN = 0x28e24c78, 20                               # the function's own copy, and its string stride

# The tap in the footswitch case for function TAP/Tunr is a tail call; Press mode turns it into a tuner request.
TAP_SITE, TAP_SITE_STOCK, TAP_CORE = 0x28dd1656, bytes.fromhex('caf7 a7bc'), 0x28d9bfa8
GUARD, REQUEST_TUNER, GET_VALUE = 0x28d96134, 0x28d96588, 0x28e1f844

# The tuner's settings (Output, Refrnc, Type, Trails, Offsets): knob turns are handled at TURN_FN, and a knob press resets the
# item to its default in one of three cases of the event handler. Lock Tuner Settings On skips both; page changes stay.
TURN_FN, TURN_FN_STOCK, TURN_FN_CONT = 0x28d916d4, bytes.fromhex('f8b5 4678'), 0x28d916d8      # push {r3-r7,lr}; ldrb r6,[r0,#1]
RESET_SITES, RESET_STOCK, RESET_RET = (0x28d917fa, 0x28d9183e, 0x28d91854), bytes.fromhex('91f8 7430'), 0x28d9176e   # ldrb.w r3,[r1,#0x74]; pop {r3,r4,r5,pc}

# CustomOS is category 6; the icon strip stays at six, so no icon is lit there. Each array below has one entry per category.
NAV_CMP, NAV_CMP_STOCK = 0x28dcf162, bytes.fromhex('052b')       # cmp r3,#5 (last category)
NAV_WRAP, NAV_WRAP_STOCK = 0x28dcf1a8, bytes.fromhex('0521')     # movs r1,#5 (going left of the first)
ARRAYS = {   # name: (stock address, new entry, literal pool words that point at it)
    'pages': (0x28e3b588, 1, (0x28dce99c, 0x28dcf408)),
    'vals': (0x28e3b5b8, 0x48, (0x28dce9a8, 0x28dcea8c)),
    'names': (0x28e3b5d0, None, (0x28dce9a4, 0x28dcea84)),
}
CAT_NAME = b'CustomOS'
CAT_PAGES = (TUNER_ID, LOCK_ID, EMPTY_SLOT)                      # page 0 of CustomOS
# Sites that switch on the category with `cmp rN,#5; bhi exit; tbb`: (hook, cat reg, page reg, table reg, tbb, exit, stub).
# The stub is category 2's generic case entered after its table load: it sets the slot in r4 itself, which some cases leave to the category.
SITES = {
    'lookup': (0x28dce652, 3, 3, 2, 0x28dce656, 0x28dce6c0, 0x28dce664),
    'touch': (0x28dceb44, 4, 3, 2, 0x28dceb48, 0x28dceb74, 0x28dcebd0),
    'touch0': (0x28dcec2a, 4, 2, 3, 0x28dcec2e, 0x28dcece0, 0x28dcec44),
    'click': (0x28dcee68, 3, 3, 2, 0x28dcee6c, 0x28dceebc, 0x28dcee7a),
    'turn': (0x28dcef58, 4, 3, 2, 0x28dcef5c, 0x28dcef8e, 0x28dcef96),
}


class Asm:
    """Thumb halfwords with labels, 16-bit conditional/unconditional branches and 32-bit B.W/BL."""

    def __init__(self, base):
        self.base, self.items, self.labels = base, [], {}

    def pos(self):
        return sum(len(x) if isinstance(x, bytes) else x[1] for x in self.items)

    def h(self, *hws):
        self.items.append(b''.join(struct.pack('<H', x) for x in hws))

    def raw(self, data):
        self.items.append(bytes(data))

    def label(self, name):
        self.labels[name] = self.base + self.pos()

    def b16(self, kind, target):    # kind: 'eq', 'ne', 'hi' or 'b'
        self.items.append((kind, 2, target))

    def bw(self, target):
        self.items.append(('bw', 4, target))

    def bl(self, target):
        self.items.append(('bl', 4, target))

    def movw_movt(self, rd, value):
        self.raw(pa._encode_thumb_movw(rd, value & 0xffff))
        hw1, hw2 = struct.unpack('<2H', pa._encode_thumb_movw(rd, value >> 16))
        self.raw(struct.pack('<2H', hw1 | 0x80, hw2))

    def bytes(self):
        out, at = b'', self.base
        for x in self.items:
            if isinstance(x, bytes):
                out += x
                at += len(x)
                continue
            kind, n, target = x
            dst = self.labels[target] if isinstance(target, str) else target
            if kind in ('bw', 'bl'):
                hw1, hw2 = struct.unpack('<2H', pa.thumb_bw(at, dst))
                out += struct.pack('<2H', hw1, hw2 | (0x4000 if kind == 'bl' else 0))
            else:
                off = (dst - (at + 4)) // 2
                if kind == 'b':
                    assert -1024 <= off < 1024, 'branch out of range'
                    out += struct.pack('<H', 0xe000 | (off & 0x7ff))
                else:
                    assert 0 <= off < 128, 'conditional branch out of range'
                    out += struct.pack('<H', 0xd000 | ({'eq': 0, 'ne': 1, 'hi': 8}[kind] << 8) | off)
            at += n
        return out


class Cave:
    """Bytes appended to the end of the code segment."""

    def __init__(self, va):
        self.va, self.buf = va, bytearray()

    def next(self, align=4):
        return self.va + len(self.buf) + (-len(self.buf)) % align

    def add(self, data, align=4):
        at = self.next(align)
        self.buf += b'\0' * (at - self.va - len(self.buf)) + data
        return at


def cmp_imm(r, i):
    return 0x2800 | (r << 8) | i


def dispatch_cave(at, site, table):
    """cmp reg,#6 -> CustomOS case: page and table into the generic case's registers, then into that case."""
    _, reg, page, tab, tbb, exit_, stub = site
    a = Asm(at)
    a.h(cmp_imm(reg, 6))
    a.b16('eq', 'mine')
    a.h(cmp_imm(reg, 5))
    a.b16('hi', 'exit')
    a.bw(tbb)
    a.label('exit')
    a.bw(exit_)
    a.label('mine')
    a.h(0x7ac0 | page)                      # ldrb page,[r0,#0xb]
    a.movw_movt(tab, table)
    a.bw(stub)
    return a.bytes()


def text_cave(at, tables):
    """Runs the two instructions the hook replaced, then answers our IDs with their value strings and leaves other IDs to stock."""
    a = Asm(at)
    a.raw(bytes.fromhex('30b5 85b0'))       # push {r4,r5,lr}; sub sp,#0x14
    for pid in tables:
        a.h(cmp_imm(0, pid))
        a.b16('eq', f'id{pid}')
    a.bw(TEXT_FN_CONT)
    for pid, table in tables.items():
        a.label(f'id{pid}')
        a.h(0x684c)                         # ldr r4,[r1,#4]: the value
        a.movw_movt(1, table)
        a.b16('b', 'common')
    a.label('common')
    a.h(0x4610, 0x461a)                     # mov r0,r2 (dst); mov r2,r3 (len)
    a.h(0xeb04, 0x0484, 0xeb01, 0x0184)     # r4 *= 5; r1 += r4 * 4: table + 20 * value
    a.bl(STRCPY)
    a.h(0x2000, 0xb005, 0xbd30)             # movs r0,#0; add sp,#0x14; pop {r4,r5,pc}
    return a.bytes()


def tap_cave(at):
    """In Press mode the tap becomes a tuner request; otherwise the stock tap-tempo core runs."""
    a = Asm(at)
    a.h(0xb510, 0xb082, 0x201d, 0x4669)     # push {r4,lr}; sub sp,#8; Tuner Activation into [sp+4]
    a.bl(GET_VALUE)
    a.h(0x9801, 0xb002, 0x2801)             # ldr r0,[sp,#4]; add sp,#8; cmp r0,#1
    a.b16('ne', 'stock')
    a.h(0x2005)                             # movs r0,#5
    a.bl(GUARD)
    a.h(0x2800)                             # cmp r0,#0
    a.b16('ne', 'done')
    a.bl(REQUEST_TUNER)
    a.label('done')
    a.h(0xbd10)                             # pop {r4,pc}
    a.label('stock')
    a.raw(bytes.fromhex('bde8 1040'))       # pop.w {r4,lr}
    a.bw(TAP_CORE)
    return a.bytes()


def turn_cave(at):
    """Knob turns on the tuner's settings: nothing happens while Lock Tuner Settings is On."""
    a = Asm(at)
    a.h(0xb507, 0xb082, 0x2000 | LOCK_ID, 0x4669)       # push {r0-r2,lr}; sub sp,#8; Lock Tuner Settings into [sp+4]
    a.bl(GET_VALUE)
    a.h(0x9b01, 0xb002)                                 # ldr r3,[sp,#4]; add sp,#8
    a.raw(bytes.fromhex('bde8 0740'))                   # pop.w {r0-r2,lr}
    a.h(0x2b01)                                         # cmp r3,#1
    a.b16('eq', 'locked')
    a.raw(TURN_FN_STOCK)
    a.bw(TURN_FN_CONT)
    a.label('locked')
    a.h(0x4770)                                         # bx lr
    return a.bytes()


def reset_cave(at, site):
    """A knob press that resets a tuner setting to its default: skipped while Lock Tuner Settings is On."""
    a = Asm(at)
    a.h(0xb082, 0x2000 | LOCK_ID, 0x4669)               # sub sp,#8; Lock Tuner Settings into [sp+4]
    a.bl(GET_VALUE)
    a.h(0x9b01, 0xb002, 0x4621, 0x2b01)                 # ldr r3,[sp,#4]; add sp,#8; mov r1,r4; cmp r3,#1
    a.b16('eq', 'locked')
    a.raw(RESET_STOCK)
    a.bw(site + 4)
    a.label('locked')
    a.bw(RESET_RET)
    return a.bytes()


def padded(s):
    return s.ljust(VALUE_LEN, b'\0')


def menu_entry0(e0):
    """Entry 0 with the settings: edits in place, plus code and data appended to the code segment."""
    e0 = bytearray(e0)
    segs = pa._parse_e0_segments(e0)
    if segs[6][3] != STOCK_BASE:
        raise SystemExit(f'patch-menu: Entry 0 code is at {segs[6][3]:#x}; this patch is for the HX Stomp 3.80.0 '
                         f'({STOCK_BASE:#x}), not the XL')

    def off(va, n):
        return pa._e0_vaddr_to_foff(segs, va, n)

    def u32(va):
        return struct.unpack_from('<I', e0, off(va, 4))[0]

    def put(va, data):
        o = off(va, len(data))
        e0[o:o + len(data)] = data

    def expect(va, stock, what):
        o = off(va, len(stock))
        if bytes(e0[o:o + len(stock)]) != stock:
            raise SystemExit(f'patch-menu: {what} is not at its stock address')

    for tab in (NAMES_LONG, NAMES_SHORT):
        if e0[off(tab + NAME_LEN * 22, 8):][:8] != b'Main LCD':
            raise SystemExit(f'patch-menu: label array at {tab:#x} is not the stock one')
        for pid, label in ((TUNER_ID, TUNER_LABEL), (LOCK_ID, LOCK_LABEL)):
            o = off(tab + NAME_LEN * pid, NAME_LEN)
            if any(e0[o:o + NAME_LEN]):
                raise SystemExit(f'patch-menu: label {pid} at {tab:#x} is not empty (the patch is already applied?)')
            e0[o:o + len(label)] = label

    enum01 = struct.unpack_from('<H', e0, off(LIMITS_TAB_LOW + 2 * 17, 2))[0]    # ID 18's entry
    if LIMITS_TAB_LOW + 2 * enum01 != ENUM01_TARGET:
        raise SystemExit('patch-menu: the limits table is not at its stock address')
    if struct.unpack_from('<H', e0, off(LIMITS_TAB_LOW + 2 * (TUNER_ID - 1), 2))[0] != 0x00a3:
        raise SystemExit('patch-menu: the limits entry of the tuner setting is not the stock one')
    put(LIMITS_TAB_LOW + 2 * (TUNER_ID - 1), struct.pack('<H', enum01))
    lock_entry = struct.unpack_from('<H', e0, off(LIMITS_TAB_HIGH + 2 * (LOCK_ID - 0x3f), 2))[0]
    if LIMITS_TAB_HIGH + 2 * lock_entry != ENUM01_TARGET:
        raise SystemExit('patch-menu: the lock setting has no enum limits entry')

    expect(TEXT_FN, TEXT_FN_STOCK, 'the value-text function')
    expect(TAP_SITE, TAP_SITE_STOCK, 'the tap-tempo call')
    expect(NAV_CMP, NAV_CMP_STOCK, 'the category navigation')
    expect(NAV_WRAP, NAV_WRAP_STOCK, 'the category navigation')
    expect(TURN_FN, TURN_FN_STOCK, 'the tuner settings knob handler')
    expect(RESET_RET, b'\x38\xbd', 'the tuner event handler epilogue')
    for site in RESET_SITES:
        expect(site, RESET_STOCK, 'a tuner settings reset case')
    for site in SITES.values():
        expect(site[0], bytes([5, 0x2b if site[1] == 3 else 0x2c]) + b'', 'a category dispatch')

    hdr, poff, slen, dst, nxt = segs[6]
    cave = Cave(dst + slen)

    # CustomOS data: the per-category arrays with a seventh entry, its page table and its value strings
    name_va = cave.add(CAT_NAME + b'\0')
    for key, (stock, new, lits) in ARRAYS.items():
        for lit in lits:
            if u32(lit) != stock:
                raise SystemExit(f'patch-menu: a category array pointer at {lit:#x} is not the stock one')
        entries = [u32(stock + 4 * i) for i in range(6)] + [name_va if key == 'names' else new]
        array_va = cave.add(b''.join(struct.pack('<I', x) for x in entries))
        for lit in lits:
            put(lit, struct.pack('<I', array_va))
    table_va = cave.add(b''.join(struct.pack('<H', x) for x in CAT_PAGES))
    values = {TUNER_ID: cave.add(b''.join(padded(v) for v in TUNER_VALUES)),
              LOCK_ID: cave.add(b''.join(padded(v) for v in LOCK_VALUES))}

    put(NAV_CMP, b'\x06\x2b')
    put(NAV_WRAP, b'\x06\x21')
    for site in SITES.values():
        va = cave.add(dispatch_cave(cave.next(), site, table_va))
        put(site[0], pa.thumb_bw(site[0], va))
    put(TEXT_FN, pa.thumb_bw(TEXT_FN, cave.add(text_cave(cave.next(), values))))
    put(TAP_SITE, pa.thumb_bw(TAP_SITE, cave.add(tap_cave(cave.next()))))
    put(TURN_FN, pa.thumb_bw(TURN_FN, cave.add(turn_cave(cave.next()))))
    for site in RESET_SITES:
        put(site, pa.thumb_bw(site, cave.add(reset_cave(cave.next(), site))))

    out = bytearray(e0[:nxt]) + cave.buf
    out += b'\x00' * ((-len(out)) & 3)
    struct.pack_into('<3I', out, hdr, slen + len(cave.buf), dst, poff + slen + len(cave.buf))
    struct.pack_into('<I', out, 4, len(out))
    if len(out) > pa.E0_MAX:
        raise SystemExit(f'patch-menu: Entry 0 would be {len(out):#x} bytes; its partition holds {pa.E0_MAX:#x}')
    return bytes(l6ia.fix_internal_crcs(bytes(out)))


def patch_menu(l6ia_bytes, log=print):
    e0 = pa.get_entry_swapped(l6ia_bytes, 0)
    new_l6ia, _, _ = l6ia.rebuild_archive(l6ia_bytes, {0: menu_entry0(e0)})
    log('[+] Entry 0: Global Settings > CustomOS (Tuner Activation, Lock Tuner Settings)')
    return new_l6ia


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('input', help='.hxf or L6IA')
    ap.add_argument('output')
    ap.add_argument('--donor', help='Stock .hxf of the unit, when input is a raw L6IA and output a .hxf')
    a = ap.parse_args()
    data, is_hxf = pa.load_l6ia_from_any(a.input)
    pa.save_l6ia_to_any(patch_menu(data), a.output, donor_hxf=a.input if is_hxf else a.donor)
    print(f'[+] Wrote {a.output}')


if __name__ == '__main__':
    main()
