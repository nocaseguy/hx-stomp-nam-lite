#!/usr/bin/env python3
"""patch_menu.py - the CustomOS section of Global Settings and the features of tools/features for the HX Stomp 3.80.0 firmware, not the XL.

The features say what they add (settings, code, hooks, inputs); this builds their pages, labels, limits and value text, places their
code and M4 modules in the code cave, and refuses two writes to the same bytes of any entry, so two features that hook one place
without sharing it fail the build instead of the last one winning."""
import argparse
import hashlib
import os
import struct
import tempfile

import features
import image_store
import l6ia
import patch_amp as pa
import setting_ids

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STOCK_BASE = 0x28d8fa80          # Entry 0 code segment of the HX Stomp 3.80.0 (the XL's differs)
NAMES_LONG, NAMES_SHORT, NAME_LEN = 0x28e25624, 0x28e26498, 27   # 'Page\nName' char[27] per parameter ID, shown name first
EMPTY_SLOT = 0x17e
GET_VALUE = 0x28e1f844           # (ID, out): the value at out + 4

# Limits come from the tbh tables at 0x28e1ead4 (ID 18's entry is an enum 0..1). The settings reader keeps IDs up to 0x95 in one store.
LIMITS_TAB_LOW, LIMITS_TAB_HIGH = 0x28e1ebbc, 0x28e1eaf0         # tbh bases for IDs 1..0x37 and 0x3f..0x9a
MAIN_STORE_IDS = (*range(1, 0x38), *range(0x3f, 0x96))
ENUM01_TARGET = 0x28e1ec66       # limits code for an integer 0..1, default 0
LIMITS_TAIL, LIMITS_TAIL_STOCK = 0x28e1ed36, bytes.fromhex('0372')     # stores type r3, default r2, min r1, max r4; strb r3,[r0,#8]
TEXT_FN, TEXT_FN_STOCK, TEXT_FN_CONT = 0x28d9775c, bytes.fromhex('30b5 85b0'), 0x28d97760   # (ID, value) -> text; push {r4,r5,lr}; sub sp,#0x14
STRCPY, VALUE_LEN = 0x28e24c78, 20                               # the function's own copy, and its string stride

# CustomOS is category 6; the icon strip stays at six, so no icon is lit there. Each array below has one entry per category.
NAV_CMP, NAV_CMP_STOCK = 0x28dcf162, bytes.fromhex('052b')       # cmp r3,#5 (last category)
NAV_WRAP, NAV_WRAP_STOCK = 0x28dcf1a8, bytes.fromhex('0521')     # movs r1,#5 (going left of the first)
ARRAYS = {   # name: (stock address, new entry, literal pool words that point at it)
    'pages': (0x28e3b588, None, (0x28dce99c, 0x28dcf408)),
    'vals': (0x28e3b5b8, 0x48, (0x28dce9a8, 0x28dcea8c)),
    'names': (0x28e3b5d0, None, (0x28dce9a4, 0x28dcea84)),
}
CAT_NAME = b'CustomOS'
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

    def b16(self, kind, target):    # kind: 'eq', 'ne', 'lo', 'hi', 'ls' or 'b'
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


thumb_bw = pa.thumb_bw


def bl(at, target):
    hw1, hw2 = struct.unpack('<2H', pa.thumb_bw(at, target))
    return struct.pack('<2H', hw1, hw2 | 0x4000)


def cmp_imm(r, i):
    return 0x2800 | (r << 8) | i


def limits_entry(pid):
    """(tbh base, address of the ID's entry) of a main-store ID."""
    if pid not in MAIN_STORE_IDS:
        raise SystemExit(f'patch-menu: setting ID {pid} is not in the settings reader\'s main store (1..0x37, 0x3f..0x95)')
    return (LIMITS_TAB_LOW, LIMITS_TAB_LOW + 2 * (pid - 1)) if pid < 0x38 else (LIMITS_TAB_HIGH, LIMITS_TAB_HIGH + 2 * (pid - 0x3f))


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
    """Runs the two instructions the hook replaced, then answers our IDs (ID -> (strings, max, default)) and leaves others to stock."""
    a = Asm(at)
    a.raw(bytes.fromhex('30b5 85b0'))       # push {r4,r5,lr}; sub sp,#0x14
    for pid, (table, max_, default) in tables.items():    # each ID's test next to its case, as a 16-bit bne reaches only 254 bytes
        a.h(cmp_imm(0, pid))
        a.b16('ne', f'not{pid}')
        a.h(0x684c, cmp_imm(4, max_))       # ldr r4,[r1,#4]: the value; cmp r4,#max
        a.b16('ls', f'in{pid}')
        a.h(0x2400 | default)               # movs r4,#default
        a.label(f'in{pid}')
        a.movw_movt(1, table)
        a.bw('common')
        a.label(f'not{pid}')
    a.bw(TEXT_FN_CONT)
    a.label('common')
    a.h(0x4610, 0x461a)                     # mov r0,r2 (dst); mov r2,r3 (len)
    a.h(0xeb04, 0x0484, 0xeb01, 0x0184)     # r4 *= 5; r1 += r4 * 4: table + 20 * value
    a.bl(STRCPY)
    a.h(0x2000, 0xb005, 0xbd30)             # movs r0,#0; add sp,#0x14; pop {r4,r5,pc}
    return a.bytes()


def cut(code):
    """The offset of an instruction of Thumb code that its end cuts in two, else None."""
    i = 0
    while i < len(code):
        n = 4 if struct.unpack_from('<H', code, i)[0] >> 11 >= 0x1d else 2
        if i + n > len(code):
            return i
        i += n
    return None


def unmovable(code):
    """Why Thumb code cannot run at another address, as (offset of the instruction, reason), else None: an instruction that
    reads the PC (a literal load, adr, a branch, tbb), one the end cuts in two, or an IT block that runs past the end."""
    if cut(code) is not None:
        return cut(code), 'is cut in two by the end of the bytes'
    i, it_at, it_left = 0, 0, 0
    while i < len(code):
        hw = struct.unpack_from('<H', code, i)[0]
        wide = hw >> 11 >= 0x1d
        hw2 = struct.unpack_from('<H', code, i + 2)[0] if wide else 0
        if not wide and (hw & 0xf800 in (0x4800, 0xa000, 0xe000) or hw & 0xf500 == 0xb100
                         or hw & 0xf000 == 0xd000 and hw >> 9 & 7 != 7 or hw & 0xfc00 == 0x4400 and hw >> 3 & 0xf == 15):
            return i, 'reads the PC'
        if wide and (hw & 0xf800 == 0xf000 and hw2 & 0x8000 and (hw2 & 0x5000 or hw & 0x0380 != 0x0380)   # b.w, bl, blx, b<c>.w
                     or hw & 0xfe1f == 0xf81f or hw & 0xfe5f == 0xe85f or hw == 0xe8df    # literal loads, ldrd, tbb/tbh
                     or hw & 0xfe1f == 0xec1f                                              # vldr, ldc and vldm from the PC
                     or hw & 0xfbff in (0xf20f, 0xf2af) and not hw2 & 0x8000):            # adr.w
            return i, 'reads the PC'
        it_left = max(it_left - 1, 0)
        if not wide and hw & 0xff00 == 0xbf00 and hw & 0xf:
            it_at, it_left = i, 4 - ((hw & 0xf) & -(hw & 0xf)).bit_length() + 1
        i += 4 if wide else 2
    return (it_at, 'starts an IT block that runs past the end') if it_left else None


def chain_cave(at, original, before, after):
    """Before handlers, the original, after handlers, each with the hook's r0-r3 (no stack arguments); returns the original's r0, r1."""
    a = Asm(at)
    a.h(0xb57f)                             # push {r0-r6,lr}: the arguments, r4 and r5 for the result, r6 to keep 8-byte alignment
    for h in before:
        a.h(0xe89d, 0x000f)                 # ldm sp,{r0-r3}
        a.bl(h)
    a.h(0xe89d, 0x000f)
    a.movw_movt(12, original | 1)
    a.h(0x47e0, 0x4604, 0x460d)             # blx r12; mov r4,r0; mov r5,r1
    for h in after:
        a.h(0xe89d, 0x000f)
        a.bl(h)
    a.h(0x4620, 0x4629, 0xb004, 0xbd70)     # mov r0,r4; mov r1,r5; add sp,#16; pop {r4-r6,pc}
    return a.bytes()


def padded(s):
    return s.ljust(VALUE_LEN, b'\0')


def check_setting(feature, s):
    head, _, tail = s.label.partition(b'\n')
    if len(head) > 8 or len(tail) > 9:
        raise SystemExit(f'patch-menu: {feature}.{s.key}: label {s.label!r} is longer than 8 characters, newline, 9 characters')
    if not 1 <= len(s.values) <= 256 or any(len(v) >= VALUE_LEN for v in s.values):
        raise SystemExit(f'patch-menu: {feature}.{s.key}: 1..256 values of at most {VALUE_LEN - 1} bytes')
    if not 0 <= s.default <= s.max:
        raise SystemExit(f'patch-menu: {feature}.{s.key}: default {s.default} is not a value')


def customos_inc(mods, ids):
    """The text of customos.inc: every setting's ID, max and default, and the CUSTOMOS_SETTING_GET macro."""
    lines = ['@ customos.inc - generated by tools/patch_menu.py from tools/features and tools/setting_ids.py']
    for m in mods:
        for s in getattr(m, 'SETTINGS', ()):
            name = f'{features.name(m)}.{s.key}'
            if name in ids:
                sym = 'SETTING_' + name.replace('.', '_').upper()
                lines += [f'.equ {sym}, {ids[name]}', f'.equ {sym}_MAX, {s.max}', f'.equ {sym}_DEFAULT, {s.default}']
    get = GET_VALUE | 1
    lines += [
        '.macro CUSTOMOS_SETTING_GET',
        '.thumb_func',
        'customos_setting_get:              @ r0 ID, r1 max, r2 default -> r0 the value, the default when it is unset or above max',
        '    push {r1, r2, r4, lr}',
        '    sub sp, #8',
        '    mov r1, sp',
        f'    movw r3, #{get & 0xffff:#x}',
        f'    movt r3, #{get >> 16:#x}',
        '    blx r3                          @ GET_VALUE: r0 < 0 when the ID has no value',
        '    ldr r1, [sp, #4]',
        '    add sp, #8',
        '    pop {r2, r3}                    @ max, default',
        '    cmp r0, #0',
        '    blt 1f',
        '    cmp r1, r2',
        '    it ls',
        '    movls r3, r1',
        '1:  mov r0, r3',
        '    pop {r4, pc}',
        '.endm',
    ]
    return '\n'.join(lines) + '\n'


class Module:
    """An M4 module placed in the code cave: m['symbol'] is the symbol's address."""

    def __init__(self, va, symbols):
        self.va, self.symbols = va, symbols

    def __getitem__(self, sym):
        return self.va + self.symbols[sym]


def overlap(written, start, end):
    """The first (start, end, owner, what) of written that overlaps start..end, else None."""
    return next((w for w in written if start < w[1] and w[0] < end), None)


class Entry:
    """An entry other than 0 being patched, addressed by offset: writes checked for overlap as Patch.put; Entry 8 also takes items."""

    MAX = {7: pa.E7_MAX, 8: pa.E8_MAX}

    def __init__(self, p, n, data):
        self.p, self.n, self.stock, self.data = p, n, bytes(data), bytearray(data)
        self.written, self.items = [], []

    def read(self, off, n):
        if off < 0 or off + n > len(self.data):
            raise SystemExit(f'patch-menu: Entry {self.n} has no bytes {off:#x}..{off + n:#x} (it is {len(self.data):#x} long)')
        return bytes(self.data[off:off + n])

    def u32(self, off):
        return struct.unpack('<I', self.read(off, 4))[0]

    def expect(self, off, stock, what):
        if self.read(off, len(stock)) != stock:
            self._written_by_another(off, len(stock), what)
            raise SystemExit(f'patch-menu: {what} is not the stock one (Entry {self.n} at {off:#x})')

    def expect_md5(self, off, n, md5, what):
        if hashlib.md5(self.read(off, n)).hexdigest() != md5:
            self._written_by_another(off, n, what)
            raise SystemExit(f'patch-menu: {what} is not the stock one (Entry {self.n} at {off:#x}, {n} bytes)')

    def _written_by_another(self, off, n, what):
        clash = overlap([w for w in self.written if w[2] != self.p.owner], off, off + n)
        if clash:
            raise SystemExit(f'patch-menu: {self.p.owner} ({what}) and {clash[2]} ({clash[3] or "a write"}) both patch '
                             f'Entry {self.n} at {max(off, clash[0]):#x}')

    def put(self, off, data, what=''):
        """Writes data at off; the bytes must be ones no feature has written yet."""
        self.read(off, len(data))
        clash = overlap(self.written, off, off + len(data))
        if clash:
            raise SystemExit(f'patch-menu: {self.p.owner} ({what or "a write"}) and {clash[2]} ({clash[3] or "a write"}) both patch '
                             f'Entry {self.n} at {max(off, clash[0]):#x}')
        self.written.append((off, off + len(data), self.p.owner, what))
        self.data[off:off + len(data)] = data

    def add_item(self, data):
        """Entry 8: data as a new item after the entry's end; returns its index (an Entry 7 record or glyph refers to it by that)."""
        if self.n != 8:
            raise SystemExit(f'patch-menu: only Entry 8 (the image store) takes items, not Entry {self.n}')
        if not self.items:
            self.put(8, self.read(8, 8), "Entry 8's item count and table offset, which add_item rewrites")
            self.put(20, self.read(20, 4), "Entry 8's size, which add_item rewrites")
        self.items.append(bytes(data))
        return struct.unpack_from('<I', self.data, 8)[0] + len(self.items) - 1

    def bytes(self):
        out = image_store.append_items(bytes(self.data), self.items) if self.items else bytes(self.data)
        if len(out) > self.MAX.get(self.n, len(out)):
            raise SystemExit(f'patch-menu: Entry {self.n} would be {len(out):#x} bytes; its partition holds {self.MAX[self.n]:#x}')
        return out


class Hook:
    """A function start one feature owns: to(handler) jumps from there to the handler, stock is the stock function."""

    def __init__(self, p, fn, prologue, owner, what):
        self.p, self.fn, self.prologue, self.owner, self.what = p, fn, prologue, owner, what
        self.handler = self._stock = None
        if unmovable(prologue) is None:       # takes the cave's next bytes: code laid out at p.next() before own_entry would move
            self._stock = p.add(prologue + thumb_bw(p.next() + len(prologue), fn + len(prologue)))

    @property
    def stock(self):
        """The stock function for a b.w (or a blx with bit 0 set): its prologue in the code cave, then a b.w past it in fn."""
        if self._stock is None:
            at, why = unmovable(self.prologue)
            raise SystemExit(f'patch-menu: {self.owner} ({self.what}): the instruction at {self.fn + at:#x} {why}, so the '
                             f'prologue cannot run elsewhere; redo it in the handler and branch to {self.fn + len(self.prologue):#x}')
        return self._stock

    def to(self, handler):
        """A b.w from fn to handler, so the handler starts with the caller's lr, sp and stack arguments."""
        if self.handler is not None:
            raise SystemExit(f'patch-menu: {self.owner} ({self.what}) set the handler of {self.fn:#x} twice')
        self.handler = handler
        o = self.p.off(self.fn, len(self.prologue))
        self.p.e0[o:o + len(self.prologue)] = thumb_bw(self.fn, handler) + b'\x00\xbf' * ((len(self.prologue) - 4) // 2)
        return self


class Patch:
    """Entry 0 being patched: writes checked for overlap, the code cave, the features' setting IDs, their inputs, the shared and
    owned hooks, and the other entries (p.entry(n))."""

    load, values = None, {}         # load(n): an entry's stock (swapped) bytes; values: feature -> {var: value}, never mutated

    def __init__(self, e0, mods, ids, load=None, values=None):
        self.e0, self.mods, self.ids = bytearray(e0), mods, ids
        self.load, self.values = load, values or {}
        self.segs = pa._parse_e0_segments(self.e0)
        if self.segs[6][3] != STOCK_BASE:
            raise SystemExit(f'patch-menu: Entry 0 code is at {self.segs[6][3]:#x}; this patch is for the HX Stomp 3.80.0 '
                             f'({STOCK_BASE:#x}), not the XL')
        _, _, slen, dst, _ = self.segs[6]
        self.cave = Cave(dst + slen)
        self.owner = 'CustomOS'
        self.written = []           # (start, end, owner, what)
        self.chains = {}            # site: [kind, original, before, after, owners]

    @property
    def entries(self):              # created on first use, so a Patch built without __init__ (as tests do) has them too
        return self.__dict__.setdefault('_entries', {})

    @property
    def owned(self):
        return self.__dict__.setdefault('_owned', {})

    def off(self, va, n):
        return pa._e0_vaddr_to_foff(self.segs, va, n)

    def read(self, va, n):
        o = self.off(va, n)
        return bytes(self.e0[o:o + n])

    def u32(self, va):
        return struct.unpack('<I', self.read(va, 4))[0]

    def u16(self, va):
        return struct.unpack('<H', self.read(va, 2))[0]

    def expect(self, va, stock, what):
        if self.read(va, len(stock)) != stock:
            clash = overlap([w for w in self.written if w[2] != self.owner], va, va + len(stock))
            if clash:
                raise SystemExit(f'patch-menu: {self.owner} ({what}) and {clash[2]} ({clash[3] or "a write"}) both patch '
                                 f'{max(va, clash[0]):#x}: share it with chain_ptr, chain_bl or chain_entry, or drop one')
            raise SystemExit(f'patch-menu: {what} is not at its stock address')

    def put(self, va, data, what=''):
        """Writes data at va; the bytes must be ones no feature has written yet."""
        clash = overlap(self.written, va, va + len(data))
        if clash:
            start, _, owner, other = clash
            raise SystemExit(f'patch-menu: {self.owner} ({what or "a write"}) and {owner} ({other or "a write"}) both patch '
                             f'{max(va, start):#x}: share it with chain_ptr, chain_bl or chain_entry, or drop one')
        self.written.append((va, va + len(data), self.owner, what))
        o = self.off(va, len(data))
        self.e0[o:o + len(data)] = data

    def next(self, align=4):
        return self.cave.next(align)

    def add(self, data, align=4):
        return self.cave.add(data, align)

    def entry(self, n):
        """Entry n (not 0, which is this Patch's own put/read) to read and write by offset."""
        if n == 0:
            raise SystemExit('patch-menu: Entry 0 is the Patch itself: p.put(), p.read() by address')
        if n not in self.entries:
            self.entries[n] = Entry(self, n, self.load(n))
        return self.entries[n]

    def add_glyph(self, font, slot, width, pixels, what=''):
        """A glyph in an empty slot of an Entry 7 font: its pixels (RGB565, column by column from the bottom, the font's cell
        height; 0 is transparent, so opaque black is 1) as a new Entry 8 item. Two features that take one slot fail."""
        e7, e8 = self.entry(7), self.entry(8)
        image_store.check(e7.data, e8.data)
        count, table = image_store.font(e7.data, font)
        h = image_store.cell_height(e7.data, font)
        if not 0 <= slot < count or image_store.glyph(e7.data, table, slot)[2] != image_store.EMPTY_GLYPH:
            raise SystemExit(f'patch-menu: {self.owner}: slot {slot:#x} of {font.decode()} is not an empty slot')
        if len(pixels) != 2 * width * h:
            raise SystemExit(f'patch-menu: {self.owner}: a {width} wide glyph of {font.decode()} is {2 * width * h} bytes, '
                             f'not {len(pixels)}')
        e7.put(table + 12 * slot, struct.pack('<3I', h, width, e8.add_item(pixels)),
               what or f'the glyph {slot:#x} of {font.decode()}')

    def input(self, var):
        """The value of one of this feature's inputs (FLAG or INPUTS), as tools/features checked it."""
        mine = self.values.get(self.owner, {})
        if var not in mine:
            raise SystemExit(f'patch-menu: {self.owner} reads {var}, which is not its FLAG or in its INPUTS')
        return mine[var]

    def id(self, name):
        if name not in self.ids:
            raise SystemExit(f'patch-menu: {name} has no ID in tools/setting_ids.py')
        return self.ids[name]

    def module(self, path):
        """Assembles an M4 .s (relative to the repository) with customos.inc on its include path, into the code cave."""
        import m4asm
        src = os.path.join(ROOT, path)
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, 'customos.inc'), 'w') as f:
                f.write(customos_inc(self.mods, self.ids))
            code, symbols = m4asm.assemble_module(src, include=(d, os.path.dirname(src)))
        return Module(self.add(code), symbols)

    def _not_owned(self, site):
        if site in self.owned:
            o = self.owned[site]
            raise SystemExit(f'patch-menu: {self.owner} chains {site:#x}, which {o.owner} owns ({o.what}): it cannot be shared')

    def _chain(self, site, kind, original, before, after):
        c = self.chains.setdefault(site, [kind, original, [], [], []])
        if c[:2] != [kind, original]:
            others = [o for o in dict.fromkeys(c[4]) if o != self.owner] or [self.owner]
            raise SystemExit(f'patch-menu: {self.owner} and {", ".join(others)} hook {site:#x} in different ways')
        c[2] += [before] if before is not None else []
        c[3] += [after] if after is not None else []
        c[4].append(self.owner)

    def chain_ptr(self, lit, stock, before=None, after=None):
        """Handlers around the function whose pointer (Thumb, with bit 0) is the literal at lit."""
        self._not_owned(lit)
        if self.u32(lit) != stock:
            raise SystemExit(f'patch-menu: the function pointer at {lit:#x} is not the stock one')
        self._chain(lit, 'ptr', stock, before, after)

    def chain_bl(self, site, stock, before=None, after=None):
        """Handlers around the call of the bl at site to stock."""
        self._not_owned(site)
        self.expect(site, bl(site, stock), f'the call at {site:#x}')
        self._chain(site, 'bl', stock, before, after)

    def chain_entry(self, fn, stock, before=None, after=None):
        """Handlers around every call of fn, whose first instructions (at least 4 bytes, whole, movable) are stock."""
        self._not_owned(fn)
        if len(stock) < 4:
            raise SystemExit(f'patch-menu: {self.owner}: give at least the 4 bytes a b.w takes of the start of {fn:#x}')
        self.expect(fn, stock, f'the start of the function at {fn:#x}')
        if unmovable(stock) is not None:
            at, why = unmovable(stock)
            raise SystemExit(f'patch-menu: {self.owner}: the instruction at {fn + at:#x} {why}, so it cannot run from the code cave')
        self._chain(fn, 'entry', stock, before, after)

    def own_entry(self, fn, stock, what, handler=None):
        """The start of fn (its first instructions, at least 4 bytes, are stock) for this feature alone, for a handler no chain
        can take: one with stack arguments, or one that rewrites them. Returns a Hook: hook.to(handler) (or handler=) puts a b.w
        to the handler at fn, hook.stock is the stock function to branch to; lay out code at p.next() only after this call,
        as hook.stock takes the cave's next bytes. Another feature that owns, chains or writes over it fails the build."""
        if fn in self.owned:
            o = self.owned[fn]
            raise SystemExit(f'patch-menu: {self.owner} ({what}) and {o.owner} ({o.what}) both own {fn:#x}: only one feature '
                             'can take a hook that cannot be chained')
        if fn in self.chains:
            others = ', '.join(dict.fromkeys(self.chains[fn][4]))
            raise SystemExit(f'patch-menu: {self.owner} owns {fn:#x} ({what}), which {others} chain: it cannot be shared')
        if len(stock) < 4 or len(stock) % 2 or cut(stock) is not None:
            raise SystemExit(f'patch-menu: {self.owner} ({what}): give at least the 4 bytes a b.w takes, whole instructions')
        self.expect(fn, stock, f'the start of the function at {fn:#x}')
        self.put(fn, stock, what)       # reserves the bytes the b.w replaces
        hook = self.owned[fn] = Hook(self, fn, stock, self.owner, what)
        return hook.to(handler) if handler is not None else hook

    def finish_chains(self):
        for hook in self.owned.values():
            if hook.handler is None:
                raise SystemExit(f'patch-menu: {hook.owner} owns {hook.fn:#x} ({hook.what}) but gave no handler: hook.to(handler)')
        self.owner = 'CustomOS'
        for site, (kind, original, before, after, owners) in sorted(self.chains.items()):
            what = 'the shared hook of ' + ', '.join(dict.fromkeys(owners))
            if kind == 'entry':
                tramp = self.add(original + thumb_bw(self.next() + len(original), site + len(original)))
                stub = self.add(chain_cave(self.next(), tramp, before, after))
                self.put(site, thumb_bw(site, stub), what)
            else:
                stub = self.add(chain_cave(self.next(), original & ~1, before, after))
                self.put(site, struct.pack('<I', stub | 1) if kind == 'ptr' else bl(site, stub), what)

    def entry0(self):
        hdr, poff, slen, dst, nxt = self.segs[6]
        out = bytearray(self.e0[:nxt]) + self.cave.buf
        out += b'\x00' * ((-len(out)) & 3)
        struct.pack_into('<3I', out, hdr, slen + len(self.cave.buf), dst, poff + slen + len(self.cave.buf))
        struct.pack_into('<I', out, 4, len(out))
        if len(out) > pa.E0_MAX:
            raise SystemExit(f'patch-menu: Entry 0 would be {len(out):#x} bytes; its partition holds {pa.E0_MAX:#x}')
        return bytes(l6ia.fix_internal_crcs(bytes(out)))

    def output(self):
        """{entry: bytes}: Entry 0, and every other entry the features changed."""
        out = {0: self.entry0()}
        for n, e in sorted(self.entries.items()):
            data = e.bytes()
            if data != e.stock:
                out[n] = data
        return out


def set_limits(p, pid, s):
    """The 0..1 enum's limits code, or for other limits a snippet in the tail of the ID's long label slot that sets them."""
    tab, entry = limits_entry(pid)
    if (s.default, s.max) == (0, 1):
        if tab + 2 * p.u16(entry) != ENUM01_TARGET:
            p.put(entry, struct.pack('<H', (ENUM01_TARGET - tab) // 2), f'the limits entry of ID {pid}')
        return
    if s.max > 255:
        raise SystemExit(f'patch-menu: setting ID {pid}: at most 256 values')
    p.expect(LIMITS_TAIL, LIMITS_TAIL_STOCK, 'the limits code tail')
    at = NAMES_LONG + NAME_LEN * pid + len(s.label) + 1
    at += at & 1
    code = struct.pack('<4H', 0x2302, 0x2200 | s.default, 0x2100, 0x2400 | s.max) + thumb_bw(at + 8, LIMITS_TAIL)
    if at + len(code) > NAMES_LONG + NAME_LEN * (pid + 1):
        raise SystemExit(f'patch-menu: setting ID {pid}: the limits code does not fit after its label: shorten the label')
    p.put(at, code, f'the limits code of ID {pid}')
    p.put(entry, struct.pack('<H', (at - tab) // 2), f'the limits entry of ID {pid}')


def menu_entry0(e0, mods=None, env=os.environ, ids=None):
    """Entry 0 with CustomOS and the enabled features, for features that change only Entry 0."""
    def load(n):
        if n:
            raise SystemExit(f'patch-menu: a feature needs Entry {n}: build with menu_entries(), which gives every entry')
        return e0

    out, on = menu_entries(load, mods, env, ids)
    return out[0], on


def menu_entries(load, mods=None, env=os.environ, ids=None, cwd=None):
    """The entries CustomOS and the enabled features change, {n: bytes} (load(n) gives an entry's stock, swapped), and the
    features: Entry 0 is edited in place plus code and data appended to its code segment. Paths in inputs are relative to cwd."""
    mods = features.load() if mods is None else mods
    on = features.enabled(mods, env)
    values = {features.name(m): features.values(m, env, cwd) for m in on}
    p = Patch(load(0), mods, setting_ids.by_name() if ids is None else ids, load, values)
    settings = []            # (ID, setting) in page order
    for m in on:
        for s in getattr(m, 'SETTINGS', ()):
            check_setting(features.name(m), s)
            settings.append((p.id(f'{features.name(m)}.{s.key}'), s))
        settings += [(EMPTY_SLOT, None)] * (-len(settings) % 3)
    if not settings:
        settings = [(EMPTY_SLOT, None)] * 3

    for tab in (NAMES_LONG, NAMES_SHORT):
        if p.read(tab + NAME_LEN * 22, 8) != b'Main LCD':
            raise SystemExit(f'patch-menu: label array at {tab:#x} is not the stock one')
        for pid, s in settings:
            if s is None:
                continue
            if any(p.read(tab + NAME_LEN * pid, NAME_LEN)):
                raise SystemExit(f'patch-menu: the label of setting ID {pid} at {tab:#x} is not empty: a stock setting, or the patch '
                                 'is already applied')
            p.put(tab + NAME_LEN * pid, s.label, f'the label of ID {pid}')

    if LIMITS_TAB_LOW + 2 * p.u16(LIMITS_TAB_LOW + 2 * 17) != ENUM01_TARGET:     # ID 18's entry
        raise SystemExit('patch-menu: the limits table is not at its stock address')
    for pid, s in settings:
        if s is not None:
            set_limits(p, pid, s)

    p.expect(TEXT_FN, TEXT_FN_STOCK, 'the value-text function')
    p.expect(NAV_CMP, NAV_CMP_STOCK, 'the category navigation')
    p.expect(NAV_WRAP, NAV_WRAP_STOCK, 'the category navigation')
    for site in SITES.values():
        p.expect(site[0], bytes([5, 0x2b if site[1] == 3 else 0x2c]), 'a category dispatch')

    # CustomOS data: the per-category arrays with a seventh entry, its page table and its value strings
    name_va = p.add(CAT_NAME + b'\0')
    for key, (stock, new, lits) in ARRAYS.items():
        for lit in lits:
            if p.u32(lit) != stock:
                raise SystemExit(f'patch-menu: a category array pointer at {lit:#x} is not the stock one')
        entries = [p.u32(stock + 4 * i) for i in range(6)] + [{'names': name_va, 'pages': len(settings) // 3}.get(key, new)]
        array_va = p.add(b''.join(struct.pack('<I', x) for x in entries))
        for lit in lits:
            p.put(lit, struct.pack('<I', array_va), f'the category array {key}')
    table_va = p.add(b''.join(struct.pack('<H', pid) for pid, _ in settings))
    values = {pid: (p.add(b''.join(padded(v) for v in s.values)), s.max, s.default) for pid, s in settings if s is not None}

    p.put(NAV_CMP, b'\x06\x2b', 'the category navigation')
    p.put(NAV_WRAP, b'\x06\x21', 'the category navigation')
    for name, site in SITES.items():
        p.put(site[0], thumb_bw(site[0], p.add(dispatch_cave(p.next(), site, table_va))), f'the category dispatch {name}')
    p.put(TEXT_FN, thumb_bw(TEXT_FN, p.add(text_cave(p.next(), values))), 'the value-text function')

    for m in on:
        if hasattr(m, 'apply'):
            p.owner = features.name(m)
            m.apply(p)
    p.finish_chains()
    return p.output(), on


def patch_menu(l6ia_bytes, log=print, cwd=None):
    entries, on = menu_entries(lambda n: pa.get_entry_swapped(l6ia_bytes, n), cwd=cwd)
    new_l6ia, _, _ = l6ia.rebuild_archive(l6ia_bytes, entries)
    others = ''.join(f'; Entry {n}' for n in entries if n)
    log(f'[+] Entry 0: Global Settings > CustomOS ({", ".join(features.name(m) for m in on)}){others}')
    return new_l6ia


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('input', help='.hxf or L6IA')
    ap.add_argument('output')
    ap.add_argument('--donor', help='Stock .hxf of the unit, when input is a raw L6IA and output a .hxf')
    ap.add_argument('--cwd', help='The directory paths in feature inputs are relative to (default: this one)')
    a = ap.parse_args()
    data, is_hxf = pa.load_l6ia_from_any(a.input)
    pa.save_l6ia_to_any(patch_menu(data, cwd=a.cwd), a.output, donor_hxf=a.input if is_hxf else a.donor)
    print(f'[+] Wrote {a.output}')


if __name__ == '__main__':
    main()
