#!/usr/bin/env python3
"""patch_menu.py - Global Settings additions for the HX Stomp 3.80.0 firmware (a CustomOS section with Tuner Activation and Lock Tuner Settings), not the XL."""
import argparse
import os
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
    'pages': (0x28e3b588, None, (0x28dce99c, 0x28dcf408)),
    'vals': (0x28e3b5b8, 0x48, (0x28dce9a8, 0x28dcea8c)),
    'names': (0x28e3b5d0, None, (0x28dce9a4, 0x28dcea84)),
}
CAT_NAME = b'CustomOS'

# Experiment (HX_PROBE=1): the two settings become a probe of the frames the DSP sends: Probe Page 0..3 is a block of 64 words and Probe Word
# 0..60 shows a mask of its words that were ever non-zero (0) or changed (1), resets (2) or shows a word (3..) as hex. No tuner features then.
PROBE = bool(os.environ.get('HX_PROBE'))
PROBE_PAGE_LABEL, PROBE_PAGE_LIMITS = b'Probe\nPage', 0x28e1ed1c    # limits: integer 0..3
PROBE_WORD_LABEL, PROBE_WORD_LIMITS = b'Probe\nWord', 0x28e1ed56    # limits: integer 0..60
# Experiment (HX_GR=1): the gain-reduction meter on the Home screen (src/m4/gr_meter.s), set by the compressor block's own GR knobs
# (tools/patch_comp.py), with no Global Settings of its own.
GR = bool(os.environ.get('HX_GR'))
if GR and PROBE:
    raise SystemExit('patch-menu: HX_GR and HX_PROBE both take the DSP stream callback')
GR_METER = bytes.fromhex(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gr_meter.hex')).read().strip()) if GR else None
RX_CB_LIT, RX_CB_ROM = 0x28da6134, 0x10001095                       # the receive callback of the DSP stream (frames of 256 words)
HOME_CTOR_CALL, HOME_CTOR = 0x28d96c44, 0x28dc91d0                   # bl to the Home view's constructor at boot
HOME_PAINT_LIT, HOME_PAINT = 0x28d96e28, 0x28dc8d39                  # the Home view's paint function, as registered
CAT_PAGES = (TUNER_ID, LOCK_ID, EMPTY_SLOT)                      # three slots a page
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
                    assert -128 <= off < 128, 'conditional branch out of range'
                    out += struct.pack('<H', 0xd000 | ({'eq': 0, 'ne': 1, 'lo': 3, 'hi': 8, 'ls': 9}[kind] << 8) | (off & 0xff))
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


def bl(at, target):
    hw1, hw2 = struct.unpack('<2H', pa.thumb_bw(at, target))
    return struct.pack('<2H', hw1, hw2 | 0x4000)


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


def text_cave(at, tables, latched=None):
    """Runs the two instructions the hook replaced, then answers our IDs with their value strings and leaves other IDs to stock."""
    a = Asm(at)
    a.raw(bytes.fromhex('30b5 85b0'))       # push {r4,r5,lr}; sub sp,#0x14
    if latched:
        a.h(cmp_imm(0, LOCK_ID))
        a.b16('eq', 'probe')
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
    if latched:
        a.label('probe')                    # Probe Word: 0 mask of the words that were ever non-zero, 1 mask of those that changed, 2 reset, 3.. a word
        a.h(0x684c, 0x4615)                 # ldr r4,[r1,#4]: the mode; mov r5,r2: dst
        a.h(0x2056, 0x2c02)                 # the text starts with the mode: movs r0,#'V'; cmp r4,#2
        a.b16('hi', 'prefix')
        a.h(0x2052, 0x2c02)                 # movs r0,#'R'; cmp r4,#2
        a.b16('eq', 'prefix')
        a.h(0x2043, 0x2c01)                 # movs r0,#'C'; cmp r4,#1
        a.b16('eq', 'prefix')
        a.h(0x204e)                         # movs r0,#'N'
        a.label('prefix')
        a.h(0x7028)                         # strb r0,[r5]
        a.h(0x2000 | TUNER_ID, 0x4669)      # movs r0,#id; mov r1,sp
        a.bl(GET_VALUE)
        a.h(0x9901, 0x4608, 0x3030, 0x7068)  # ldr r1,[sp,#4]: the page; mov r0,r1; adds r0,#'0'; strb r0,[r5,#1]
        a.h(0x203a, 0x70a8)                 # movs r0,#':'; strb r0,[r5,#2]
        a.h(0x0209, 0xb4c0)                 # lsls r1,r1,#8: byte offset of the page; push {r6,r7}
        a.movw_movt(2, latched)
        a.h(0x2c02)                         # cmp r4,#2
        a.b16('hi', 'value')
        a.b16('ne', 'mask')
        a.h(0x2000)                         # movs r0,#0: reset clears the three arrays of 256 words
        a.raw(pa._encode_thumb_movw(3, 768))
        a.label('clear')
        a.h(0x3b01, 0xf842, 0x0023)         # subs r3,#1; str.w r0,[r2,r3,lsl #2]
        a.b16('ne', 'clear')
        a.h(0x2400)                         # movs r4,#0
        a.label('mask')
        a.h(0x02a0, 0x1812, 0x1852)         # lsls r0,r4,#10; adds r2,r2,r0; adds r2,r2,r1: array (latched or changed) of the page
        for half, move in (('lo', 0x4606), ('hi', 0x4607)):
            a.h(0x2000, 0x2300)             # movs r0,#0; movs r3,#0
            a.label(f'bit{half}')
            a.h(0xf852, 0xc023, 0xf1bc, 0x0f00)    # ldr.w r12,[r2,r3,lsl #2]; cmp.w r12,#0
            a.b16('eq', f'skip{half}')
            a.h(0xf04f, 0x0c01, 0xfa0c, 0xfc03, 0xea40, 0x000c)    # mov.w r12,#1; lsl.w r12,r12,r3; orr.w r0,r0,r12
            a.label(f'skip{half}')
            a.h(0x3301, 0x2b20)             # adds r3,#1; cmp r3,#32
            a.b16('ne', f'bit{half}')
            a.h(move)                       # mov r6,r0 / mov r7,r0
            if half == 'lo':
                a.h(0x3280)                 # adds r2,#128: words 32..63
        a.h(0x463c, 0x2101)                 # mov r4,r7: high half first; movs r1,#1: two passes
        a.b16('b', 'format')
        a.label('value')
        a.h(0x3c03, 0x0888, 0x1900)         # subs r4,#3; lsrs r0,r1,#2; adds r0,r0,r4: the word's number in the frame
        a.h(0x0903)                         # lsrs r3,r0,#4: its high digit, then the low one
        for slot in (1, 2):
            a.h(0x3330, 0x2b39)             # adds r3,#'0'; cmp r3,#'9'
            a.b16('ls', f'num{slot}')
            a.h(0x3307)                     # adds r3,#7
            a.label(f'num{slot}')
            a.h(0x706b + ((slot - 1) << 6))  # strb r3,[r5,#slot]
            if slot == 1:
                a.h(0x230f, 0x4003)         # movs r3,#15; ands r3,r0
        a.h(0x233a, 0x70eb)                 # movs r3,#':'; strb r3,[r5,#3]
        a.h(0x1852)                         # adds r2,r2,r1
        a.h(0xf852, 0x4024, 0xea4f, 0x4434) # ldr.w r4,[r2,r4,lsl #2]; ror.w r4,r4,#16: the stream swaps halfwords
        a.h(0x2100, 0x1d2b)                 # movs r1,#0: one pass; adds r3,r5,#4: after the number
        a.b16('b', 'pass')
        a.label('format')
        a.h(0x1ceb)                         # adds r3,r5,#3: after the mode and page
        a.label('pass')
        a.h(0x2208)                         # movs r2,#8
        a.label('digit')
        a.h(0x0f20, 0x3030, 0x2839)         # lsrs r0,r4,#28; adds r0,#'0'; cmp r0,#'9'
        a.b16('hi', 'letter')
        a.label('store')
        a.h(0x7018, 0x3301, 0x0124, 0x3a01) # strb r0,[r3]; adds r3,#1; lsls r4,r4,#4; subs r2,#1
        a.b16('ne', 'digit')
        a.h(0x2900)                         # cmp r1,#0
        a.b16('eq', 'end')
        a.h(0x2100, 0x4634)                 # movs r1,#0; mov r4,r6: low half
        a.b16('b', 'pass')
        a.label('letter')
        a.h(0x3007)                         # adds r0,#7
        a.b16('b', 'store')
        a.label('end')
        a.h(0x2000, 0x7018, 0xbcc0, 0xb005, 0xbd30)    # movs r0,#0; strb r0,[r3]; pop {r6,r7}; add sp,#0x14; pop {r4,r5,pc}
    return a.bytes()


def rx_cave(at, latched):
    """The DSP stream's receive callback, after counting the frames (r1) and keeping the first two with messages since the reset."""
    a = Asm(at)
    a.h(0xb470)                             # push {r4,r5,r6}
    a.movw_movt(4, latched)
    a.h(0xf8d4, 0x63c0, 0x3601, 0xf8c4, 0x63c0)    # ldr.w r6,[r4,#0x3c0]; adds r6,#1; str.w r6,[r4,#0x3c0]: all frames, as word 0xf0
    for k in range(16):                     # words 200..215 of the frame, kept as words 200..215: where the DSP writes
        a.h(0xf8d1, 0x3000 | (800 + 4 * k), 0xf8c4, 0x3000 | (800 + 4 * k))
    a.h(0x684a, 0x0c12)                     # ldr r2,[r1,#4]; lsrs r2,r2,#16: the message count of the frame
    a.b16('eq', 'done')
    a.h(0xf8d4, 0x63c4, 0x3601, 0xf8c4, 0x63c4)    # the same for the frames with messages, as word 0xf1
    a.h(0xf8d4, 0x33c8, 0x2b01)             # ldr.w r3,[r4,#0x3c8]: frames kept so far, word 0xf2; cmp r3,#1
    a.b16('hi', 'done')
    a.h(0x1c5a, 0xf8c4, 0x23c8)             # adds r2,r3,#1; str.w r2,[r4,#0x3c8]
    a.h(0x021a, 0x019e, 0x1992, 0x18a6)     # r6 = r4 + r3 * 320: the slot of 80 words
    a.h(0x2500)                             # movs r5,#0
    a.label('word')
    a.h(0xf851, 0x2025, 0xf846, 0x2025)     # ldr.w r2,[r1,r5,lsl #2]; str.w r2,[r6,r5,lsl #2]
    a.h(0x3501, 0x2d50)                     # adds r5,#1; cmp r5,#80
    a.b16('ne', 'word')
    a.label('done')
    a.h(0xbc70)                             # pop {r4,r5,r6}
    if a.pos() % 4:
        a.h(0xbf00)
    a.h(0xf8df, 0xf000)                     # ldr.w pc,[pc,#0]: on to the stock callback
    a.raw(struct.pack('<I', RX_CB_ROM))
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
        labels = ((TUNER_ID, PROBE_PAGE_LABEL if PROBE else TUNER_LABEL), (LOCK_ID, PROBE_WORD_LABEL if PROBE else LOCK_LABEL))
        for pid, label in labels:
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

    if PROBE:
        put(LIMITS_TAB_LOW + 2 * (TUNER_ID - 1), struct.pack('<H', (PROBE_PAGE_LIMITS - LIMITS_TAB_LOW) // 2))
        put(LIMITS_TAB_HIGH + 2 * (LOCK_ID - 0x3f), struct.pack('<H', (PROBE_WORD_LIMITS - LIMITS_TAB_HIGH) // 2))
    if PROBE or GR:
        if u32(RX_CB_LIT) != RX_CB_ROM:
            raise SystemExit('patch-menu: the DSP stream callback is not the stock one')
    if GR:
        expect(HOME_CTOR_CALL, bl(HOME_CTOR_CALL, HOME_CTOR), 'the Home view constructor call')
        if u32(HOME_PAINT_LIT) != HOME_PAINT:
            raise SystemExit('patch-menu: the Home view paint function is not the stock one')
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
        entries = [u32(stock + 4 * i) for i in range(6)] + [{'names': name_va, 'pages': len(CAT_PAGES) // 3}.get(key, new)]
        array_va = cave.add(b''.join(struct.pack('<I', x) for x in entries))
        for lit in lits:
            put(lit, struct.pack('<I', array_va))
    table_va = cave.add(b''.join(struct.pack('<H', x) for x in CAT_PAGES))
    if PROBE:
        values = {TUNER_ID: cave.add(b''.join(padded(v) for v in (b'0', b'1', b'2', b'3')))}
        latched = cave.add(bytes(3072))
    else:
        values = {TUNER_ID: cave.add(b''.join(padded(v) for v in TUNER_VALUES)),
                  LOCK_ID: cave.add(b''.join(padded(v) for v in LOCK_VALUES))}
        latched = None

    put(NAV_CMP, b'\x06\x2b')
    put(NAV_WRAP, b'\x06\x21')
    for site in SITES.values():
        va = cave.add(dispatch_cave(cave.next(), site, table_va))
        put(site[0], pa.thumb_bw(site[0], va))
    put(TEXT_FN, pa.thumb_bw(TEXT_FN, cave.add(text_cave(cave.next(), values, latched))))
    if GR:
        gr_va = cave.add(GR_METER)          # +0 receive callback, +4 Home constructor, +8 Home paint
        put(RX_CB_LIT, struct.pack('<I', gr_va | 1))
        put(HOME_CTOR_CALL, bl(HOME_CTOR_CALL, gr_va + 4))
        put(HOME_PAINT_LIT, struct.pack('<I', (gr_va + 8) | 1))
    if PROBE:
        put(RX_CB_LIT, struct.pack('<I', cave.add(rx_cave(cave.next(), latched)) | 1))
    else:
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
    log('[+] Entry 0: Global Settings > CustomOS (Tuner Activation, Lock Tuner Settings' + (', GR meter hooks' if GR else '') + ')')
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
