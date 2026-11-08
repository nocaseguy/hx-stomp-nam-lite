"""Virtual settings (tools/setting_ids.py VIRTUAL, src/m4/virtual_settings.s): the ledger, the engine's handlers run in unicorn against
fake container records, the stock facts they rest on (emulating the stock store write), and a build with virtual settings run end to
end in unicorn: the owned settings functions, and a knob turn through the stock turn handler and the stock step arithmetic."""
import os
import struct
import tempfile
import types

import pytest

import features
import m4asm
import patch_amp as pa
import patch_menu as pm
import setting_ids
from features import Setting
from firmware import branch_target, reader, stock_e0

MODS = features.load()
SETTINGS = {f'{features.name(m)}.{s.key}': s for m in MODS for s in getattr(m, 'SETTINGS', ())}
CLANG = pytest.mark.skipif(not os.path.exists(m4asm.CLANG), reason='no Command Line Tools clang')

RECORDS, DIRTY, STORE_LOCK = 0x2845ee9c, 0x2845ee95, 0x2845ee88
MUTEX_LOCK, MUTEX_UNLOCK, MEMCPY = 0x28e24c00, 0x28e24bb0, 0x28e24c78
SETTINGS_CTX, STEP_MATH, CHANGED = 0x28e007ec, 0x28dfe6a8, 0x28dceb30
CLASS_ABOVE, CLASS_BELOW = 0x28e20254, 0x28e20260
TURN_STUB, TURN_EXIT, CLICK_STUB, CLICK_DONE = 0x28dcef96, 0x28dcef8e, 0x28dcee7a, 0x28dceeaa
FLOAT_ONE = 0x3f800000              # what an unset container holds, as type 3

POS = Setting('pos', b'Demo\nPosition', tuple(b'P%d' % i for i in range(5)), default=2)
DIR = Setting('dir', b'Demo\nDirection', (b'Normal', b'Reverse'))
WIDE = Setting('wide', b'Demo\nWide', tuple(b'%d' % i for i in range(200)), default=7)
VIRT = [(0xcc, POS), (0xcd, DIR), (0xce, WIDE)]
PACKING = {0xcc: (105, 0, 3), 0xcd: (105, 3, 1), 0xce: (116, 24, 8)}


def record(cid):
    return RECORDS + 40 * cid


# the ledger

def test_ledger_is_sound():
    assert setting_ids.virtual_problems() == []
    names = [name for *_, name, _ in setting_ids.VIRTUAL if name]
    assert len(names) == len(set(names)) and not set(names) & {name for _, name, _ in setting_ids.IDS}
    for vid, cid, bit, bits, name, _ in setting_ids.VIRTUAL:
        if name:
            assert name in SETTINGS and SETTINGS[name].max < 1 << bits, f'{name}: {bits} bits cannot hold its values'


def test_virtual_problems_finds_each_mistake():
    bad = [(0xcb, 105, 0, 4, 'a', ''), (0xcc, 104, 0, 4, 'b', ''), (0xcd, 105, 30, 4, 'c', ''),
           (0xce, 106, 0, 4, 'd', ''), (0xcf, 106, 3, 2, 'e', ''), (0xcf, 107, 0, 1, 'f', '')]
    problems = setting_ids.virtual_problems(bad)
    assert any('0xcb is not a virtual ID' in s for s in problems)
    assert any('104 is not a container' in s for s in problems)
    assert any('bits 30..33' in s for s in problems)
    assert any('bit 3 of 106' in s for s in problems)
    assert any('0xcf is listed twice' in s for s in problems)
    assert setting_ids.virtual_problems([(0xcc, 105, 0, 32, 'a', ''), (0xf9, 116, 31, 1, None, '')]) == []


def test_packing_and_by_name_take_virtual_lines():
    entries = [(0xcc, 105, 0, 3, 'demo.pos', ''), (0xcd, 105, 3, 1, None, 'demo.dir until a72c76a')]
    assert setting_ids.packing(entries) == {0xcc: (105, 0, 3)}
    assert set(setting_ids.by_name().values()) >= {vid for vid, *_, name, _ in setting_ids.VIRTUAL if name}


def test_add_virtual_refuses_a_field_too_narrow_and_a_long_label():
    with pytest.raises(SystemExit, match='3 bits cannot hold its 200 values'):
        pm.add_virtual(None, [(0xce, WIDE)], {0xce: (116, 0, 3)})
    with pytest.raises(SystemExit, match='label is longer'):
        pm.add_virtual(None, [(0xcc, Setting('x', b'L' * 40, (b'a',)))], {0xcc: (105, 0, 1)})
    with pytest.raises(SystemExit, match='bit 0 of 105'):
        pm.add_virtual(None, [(0xcc, POS), (0xcd, DIR)], {0xcc: (105, 0, 3), 0xcd: (105, 0, 1)})
    assert pm.add_virtual(None, [], {}) is None


def test_virtual_inc_lists_the_table_and_labels():
    inc = pm.virtual_inc(VIRT, PACKING, {'get': 0x28e60000, 'limits': 0x28e60010, 'label': 0x28e60020})
    assert '.equ VIRT_FIRST, 0xcc\n' in inc and '.equ VIRT_LAST, 0xf9\n' in inc and '.equ VIRT_COUNT, 3\n' in inc
    assert '.equ GET_STOCK, 0x28e60001\n' in inc and '.equ LABEL_STOCK, 0x28e60021\n' in inc
    assert '    .hword 0xce\n    .byte 116, 24, 8, 199, 7, 2\n' in inc
    assert inc.count('    .byte 68, 101, 109, 111, 10') == 3     # b'Demo\n', each label padded to 36 bytes


# the engine in unicorn

CODE, TABLE, VIEW, DST, OUT, LIMITS = 0x28e60000, 0x28e70000, 0x28e71000, 0x28e72000, 0x28e73000, 0x28e74000
GET_STOCK, LIMITS_STOCK, LABEL_STOCK, TRAMPOLINE, DELTA = 0x28d90000, 0x28d90100, 0x28d90200, 0x28e78000, 0x28e79000


def assemble(virt=VIRT, packing=PACKING, stocks=None):
    if not os.path.exists(m4asm.CLANG):
        pytest.skip('no Command Line Tools clang')
    stocks = stocks or {'get': GET_STOCK, 'limits': LIMITS_STOCK, 'label': LABEL_STOCK}
    with tempfile.TemporaryDirectory() as d:
        for name, text in (('customos.inc', pm.customos_inc(MODS, setting_ids.by_name())),
                           ('virtual.inc', pm.virtual_inc(virt, packing, stocks))):
            with open(os.path.join(d, name), 'w') as f:
                f.write(text)
        return m4asm.assemble_module(os.path.join(pm.ROOT, 'src/m4/virtual_settings.s'), include=(d,))


class Engine:
    """virtual_settings.s in unicorn: fake container records, a step that adds the delta, and the stock exits as stubs."""

    def __init__(self, m4emu):
        code, self.sym = assemble()
        self.m = m = m4emu.M4(code, CODE)
        for cid in (105, 116):
            self.set(cid, 3, FLOAT_ONE)
        m.write(TABLE, struct.pack('<6H', 0xcc, 0xcd, 0x40, 0xce, 0xd0, pm.EMPTY_SLOT))     # pages 0 and 1
        for fn in (MUTEX_LOCK, MUTEX_UNLOCK, CHANGED, SETTINGS_CTX, GET_STOCK, LIMITS_STOCK, LABEL_STOCK, CLASS_ABOVE, CLASS_BELOW,
                   TURN_STUB, TURN_EXIT, CLICK_STUB, CLICK_DONE):
            m.stub(fn)
        m.stub(MEMCPY, lambda m: m.write(m.reg('r0'), m.read(m.reg('r1'), m.reg('r2'))))
        m.stub(STEP_MATH, self._step)
        a = pm.Asm(TRAMPOLINE)              # the stock turn hands the delta over in r5
        a.h(0xb520)                         # push {r5,lr}
        a.movw_movt(5, DELTA)
        a.h(0x682d)                         # ldr r5,[r5]
        a.bl(self.va('virt_turn'))
        a.h(0xbd20)                         # pop {r5,pc}
        m.load(TRAMPOLINE, a.bytes())

    def _step(self, m):
        lim, cur, delta = m.reg('r1'), m.reg('r2'), m.reg('r3')
        out = m.stack_args(1)[0]
        lo, hi = m.u32(lim + 0x14), m.u32(lim + 0x1c)
        v = m.u32(cur + 4) + (delta - (1 << 32) if delta >> 31 else delta)
        m.write(out, struct.pack('<BxxxI', 2, max(lo, min(hi, v))))
        m.reg('r0', 0)

    def va(self, sym):
        return CODE + self.sym[sym]

    def set(self, cid, kind, word):
        self.m.write(record(cid) + 8, struct.pack('<BxxxI', kind, word))

    def container(self, cid):
        return struct.unpack('<BxxxI', self.m.read(record(cid) + 8, 8))

    def get(self, pid):
        self.m.write(OUT, b'\xee' * 8)
        r0 = self.m.call(self.va('virt_get'), pid, OUT)
        return r0 - (1 << 32) if r0 >> 31 else r0, struct.unpack('<BxxxI', self.m.read(OUT, 8))

    def turn(self, slot, delta, page=0):
        self.m.u32(DELTA, delta)
        self.m.log.clear()
        self.m.call(TRAMPOLINE, VIEW, slot, TABLE, page)
        return [at for at, _ in self.m.log]


def test_get_reads_defaults_while_the_container_is_unset(m4emu):
    e = Engine(m4emu)
    assert e.get(0xcc) == (0, (2, 2)) and e.get(0xcd) == (0, (2, 0)) and e.get(0xce) == (0, (2, 7))
    assert e.m.log == []
    for kind, word in ((3, 0x40400000), (1, 1), (0, 0)):    # a float or a bool, as a restore with another type could leave
        e.set(105, kind, word)
        assert e.get(0xcc) == (0, (2, 2)), kind


def test_get_reads_each_field_and_the_default_above_max(m4emu):
    e = Engine(m4emu)
    e.set(105, 2, 4 | 1 << 3 | 0xfffffff0)
    e.set(116, 2, 199 << 24 | 0xffffff)
    assert e.get(0xcc)[1] == (2, 4) and e.get(0xcd)[1] == (2, 1) and e.get(0xce)[1] == (2, 199)
    e.set(105, 2, 7)                        # 7 > Position's max 4: a value from another build
    assert e.get(0xcc)[1] == (2, 2)
    e.set(116, 2, 0xff << 24)
    assert e.get(0xce)[1] == (2, 7)


def test_get_leaves_other_ids_to_stock_and_unused_virtual_ids_unknown(m4emu):
    e = Engine(m4emu)
    for pid in (0x40, 0xcb, 0xfa, 0x17d):
        e.m.log.clear()
        e.m.call(e.va('virt_get'), pid, OUT)
        assert [at for at, _ in e.m.log] == [GET_STOCK] and e.m.reg('r0') == pid and e.m.reg('r1') == OUT
    assert e.get(0xd0)[0] == -3 and e.get(0xf9)[0] == -3


def test_limits_fill_a_main_store_record(m4emu):
    e = Engine(m4emu)
    e.set(105, 2, 3)
    e.m.write(LIMITS, b'\xee' * 40)
    assert e.m.call(e.va('virt_limits'), 0xcc, LIMITS) == 0
    words = struct.unpack('<10I', e.m.read(LIMITS, 40))
    assert words[:2] == (0, 0xcc) and [w & 0xff for w in words[2::2]] == [2, 2, 2, 2]
    assert words[3::2] == (3, 0, 4, 2)      # value, min, max, default
    e.m.call(e.va('virt_limits'), 0x40, LIMITS)
    assert [at for at, _ in e.m.log] == [LIMITS_STOCK]
    assert e.m.call(e.va('virt_limits'), 0xd0, LIMITS) == 0xfffffffd


def test_class_is_the_main_store_and_other_ids_go_back_to_stock(m4emu):
    e = Engine(m4emu)
    e.m.write(DST, b'\xee')
    assert e.m.call(e.va('virt_class'), 0xcd, DST) == 0 and e.m.read(DST, 1) == b'\0'
    assert e.m.call(e.va('virt_class'), 0xd0, DST) == 0xfffffffd
    for pid, to in ((0x10, CLASS_BELOW), (0xcb, CLASS_BELOW), (0xfa, CLASS_ABOVE), (0x17d, CLASS_ABOVE)):
        e.m.log.clear()
        e.m.call(e.va('virt_class'), pid, DST)
        assert [at for at, _ in e.m.log] == [to] and e.m.reg('r0') == pid


def test_label_copies_the_asked_length(m4emu):
    e = Engine(m4emu)
    e.m.write(DST, b'\xee' * 40)
    assert e.m.call(e.va('virt_label'), 0xcd, DST, 0x21) == 0
    assert e.m.read(DST, 40) == b'Demo\nDirection'.ljust(0x21, b'\0') + b'\xee' * 7
    e.m.call(e.va('virt_label'), 0xcc, DST, 100)
    assert e.m.read(DST, 37) == b'Demo\nPosition'.ljust(36, b'\0') + b'\xee'
    e.m.log.clear()
    e.m.call(e.va('virt_label'), 0x30, DST, 0x21)
    assert [at for at, _ in e.m.log] == [LABEL_STOCK]
    assert e.m.call(e.va('virt_label'), 0xd0, DST, 0x21) == 0xfffffffd


def test_turn_steps_stores_and_repaints(m4emu):
    e = Engine(m4emu)
    calls = e.turn(0, 1)
    assert e.container(105) == (2, 3)       # Position 2 -> 3; Direction keeps its default, 0, in bit 3
    assert e.m.read(DIRTY, 1) == b'\1'
    assert calls == [SETTINGS_CTX, STEP_MATH, MUTEX_LOCK, MUTEX_UNLOCK, CHANGED, TURN_EXIT]
    assert e.m.calls(MUTEX_LOCK)[0][0] == STORE_LOCK and e.m.calls(CHANGED)[0][:2] == (VIEW, 0xcc)
    e.turn(1, 1)
    assert e.container(105) == (2, 3 | 1 << 3)
    e.m.write(DIRTY, b'\0')
    assert e.turn(1, 5) == [SETTINGS_CTX, STEP_MATH, TURN_EXIT]        # at its max: no store, no repaint
    assert e.m.read(DIRTY, 1) == b'\0'
    e.turn(0, -9)
    assert e.container(105) == (2, 0 | 1 << 3)


def test_turn_of_a_wide_field_keeps_the_others(m4emu):
    e = Engine(m4emu)
    e.set(116, 2, 0x00abcdef)
    e.turn(0, 100, page=1)
    assert e.container(116) == (2, 100 << 24 | 0xabcdef)


def test_turn_on_a_stock_or_empty_slot_is_the_stock_turn(m4emu):
    e = Engine(m4emu)
    for slot, page in ((2, 0), (1, 1), (2, 1)):     # ID 0x40, an unused virtual ID, an empty slot
        assert e.turn(slot, 1, page) == [TURN_STUB]
        assert e.m.calls(TURN_STUB) == [(VIEW, slot, TABLE, page)]
    assert e.container(105) == (3, FLOAT_ONE)


def test_click_resets_to_the_default(m4emu):
    e = Engine(m4emu)
    e.set(105, 2, 4)
    e.m.call(e.va('virt_click'), VIEW, 0, TABLE, 0)
    assert e.container(105) == (2, 2) and [at for at, _ in e.m.log] == [MUTEX_LOCK, MUTEX_UNLOCK, CLICK_DONE]
    e.m.log.clear()
    e.m.call(e.va('virt_click'), VIEW, 2, TABLE, 0)
    assert [at for at, _ in e.m.log] == [CLICK_STUB] and [e.m.reg(f'r{i}') for i in range(4)] == [VIEW, 2, TABLE, 0]


def test_a_store_into_an_unset_container_starts_from_every_default(m4emu):
    e = Engine(m4emu)
    e.m.call(e.va('virt_click'), VIEW, 1, TABLE, 0)  # Direction's reset writes the container; Position must stay 2
    assert e.container(105) == (2, 2)


# stock facts the engine rests on

def stock_m4(m4emu):
    e0 = stock_e0()
    hdr, poff, slen, va, _ = pa._parse_e0_segments(e0)[6]
    m = m4emu.M4(e0[poff:poff + slen], va)
    return m


@pytest.mark.firmware
def test_stock_store_write_refuses_the_containers_and_the_variax_block(m4emu):
    """The store write 0x28e1f0d8 returns -21 and stores nothing for 32..56 and 105..116, so the engine writes containers itself."""
    m = stock_m4(m4emu)
    for pid in (23, 32, 56, 74, 105, 116, 120):
        m.write(record(pid) + 8, b'\0' * 8)
        m.write(DIRTY, b'\0')
        m.write(OUT, struct.pack('<BxxxI', 2, 7))
        r0 = m.call(0x28e1f0d8, pid, OUT, 8)
        refused = 32 <= pid <= 56 or 105 <= pid <= 116
        assert (r0 == 0xffffffeb) == refused, pid
        assert m.read(record(pid) + 8, 8) == (b'\0' * 8 if refused else struct.pack('<BxxxI', 2, 7))
        assert m.read(DIRTY, 1) == (b'\0' if refused else b'\1')


@pytest.mark.firmware
def test_stock_owned_sites_are_as_expected():
    read = reader(stock_e0())
    for fn, stock in pm.VIRTUAL_HOOKS.values():
        assert read(fn, len(stock)) == stock
    assert read(0x28e1efd8, 2) == bytes.fromhex('882c')      # the store's get stops at 0x88: 105..116 have records
    assert read(0x28de9ae6, 2) == bytes.fromhex('892a')      # the Globals loader wants exactly 137 main-store records
    assert branch_target(0x28e1cbda, read(0x28e1cbda, 4)) == 0x28de967c    # HX Edit's globals message has the main store...
    assert read(0x28de972e, 2) == bytes.fromhex('892d')      # ...every record of it, the containers' raw values among them


# a build with virtual settings, end to end

def demo_build():
    demo = types.ModuleType('features.demo')
    demo.SETTINGS = (POS, DIR, WIDE)
    ids = dict(setting_ids.by_name(), **{'demo.pos': 0xcc, 'demo.dir': 0xcd, 'demo.wide': 0xce})
    out, on = pm.menu_entries(lambda n: stock_e0(), MODS + [demo], {}, ids, virtual=PACKING)
    return out[0]


class Built:
    """The built Entry 0's code segment in unicorn: stock code and the cave run for real; locks and the repaint are stubs."""

    def __init__(self, m4emu, e0):
        hdr, poff, slen, va, _ = pa._parse_e0_segments(e0)[6]
        self.m = m = m4emu.M4(e0[poff:poff + slen], va)
        for fn in (MUTEX_LOCK, MUTEX_UNLOCK, CHANGED):
            m.stub(fn)
        m.stub(MEMCPY, lambda m: m.write(m.reg('r0'), m.read(m.reg('r1'), m.reg('r2'))))     # a veneer to the boot ROM's
        m.write(record(105) + 8, struct.pack('<BxxxI', 3, FLOAT_ONE))
        m.write(record(74) + 8, struct.pack('<BxxxI', 2, 3))

    def get(self, pid):
        r0 = self.m.call(pm.GET_VALUE, pid, OUT)
        return r0 - (1 << 32) if r0 >> 31 else r0, struct.unpack('<BxxxI', self.m.read(OUT, 8))


@pytest.mark.firmware
def test_build_owns_the_four_settings_functions():
    e0 = demo_build()
    read = reader(e0)
    for name, (fn, stock) in pm.VIRTUAL_HOOKS.items():
        assert branch_target(fn, read(fn, 4)) > 0x28e3f000, name     # a b.w into the code cave
    assert read(pm.NAMES_LONG + pm.NAME_LEN * 0x88, 14) == b'Cabs\nLink Dual'     # no label slot written for a virtual ID


@pytest.mark.firmware
def test_default_build_has_no_virtual_engine():
    new, _ = pm.menu_entry0(stock_e0())
    read = reader(new)
    for fn, stock in pm.VIRTUAL_HOOKS.values():
        assert read(fn, len(stock)) == stock


@pytest.mark.firmware
def test_built_settings_functions_serve_virtual_and_stock_ids(m4emu):
    b = Built(m4emu, demo_build())
    assert b.get(0xcc) == (0, (2, 2)) and b.get(0xce) == (0, (2, 7))
    assert b.get(74) == (0, (2, 3))         # through the hook's copy of GET_VALUE's first instruction
    assert b.get(0xd0)[0] == -3 and b.get(0x89)[0] == -3
    m = b.m
    m.write(LIMITS, b'\xee' * 40)
    assert m.call(0x28e20280, 0xcd, LIMITS) == 0 and struct.unpack_from('<I', m.read(LIMITS, 40), 0x1c)[0] == 1
    assert m.call(0x28e20280, 74, LIMITS) == 0 and m.read(LIMITS + 8, 8) == struct.pack('<BxxxI', 2, 3)
    assert m.call(0x28d97634, 0xce, DST, 0x21) == 0 and m.read(DST, 11) == b'Demo\nWide\0\0'
    assert m.call(0x28d97634, 0x88, DST, 0x21) == 0 and m.read(DST, 14) == b'Cabs\nLink Dual'


@pytest.mark.firmware
def test_built_class_matches_stock_for_stock_ids(m4emu):
    built, stock = Built(m4emu, demo_build()).m, stock_m4(m4emu)
    for pid in (0, 0x10, 0x95, 0x96, 0xbd, 0xcb, 0xd0, 0xfa, 0x17d, 0x17e, 0x200):
        if 0xcc <= pid <= 0xf9:
            continue
        got = []
        for m in (built, stock):
            m.write(DST, b'\xee')
            got.append((m.call(0x28e20250, pid, DST), m.read(DST, 1)))
        assert got[0] == got[1], hex(pid)
    built.write(DST, b'\xee')
    assert built.call(0x28e20250, 0xcc, DST) == 0 and built.read(DST, 1) == b'\0'


@pytest.mark.firmware
def test_built_turn_steps_by_the_stock_knob_arithmetic(m4emu):
    """The stock turn handler 0x28dcef50 on CustomOS page 0, slot 0: the dispatch cave, virt_turn, the stock step (four encoder
    counts a step), the container written, the slot repainted through the view's change handler, and the stock exit."""
    b = Built(m4emu, demo_build())
    m = b.m
    m.write(VIEW, b'\0' * 0x50)
    m.write(VIEW + 0xa, bytes([6, 0]))      # category CustomOS, page 0
    for count in range(3):
        m.call(0x28dcef50, VIEW, 0, 1)
        assert m.read(record(105) + 8, 1) == b'\3' and m.calls(CHANGED) == [], count
    m.call(0x28dcef50, VIEW, 0, 1)
    assert m.read(record(105) + 8, 8) == struct.pack('<BxxxI', 2, 3)
    assert m.calls(CHANGED)[-1][:2] == (VIEW, 0xcc) and m.read(DIRTY, 1) == b'\1'
    m.call(0x28dcef50, VIEW, 0, 400)
    assert b.get(0xcc) == (0, (2, 4))       # clamped at Position's max
    m.call(0x28dcef50, VIEW, 1, 4)
    assert b.get(0xcd) == (0, (2, 1)) and b.get(0xcc) == (0, (2, 4))
