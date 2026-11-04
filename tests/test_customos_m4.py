"""The M4 code tools/patch_menu.py generates, run in unicorn (tests/m4emu.py): the shared-hook stub and each kind of chain
(function pointer, bl call, function entry) with two features on one site, customos_setting_get, and the value text of CustomOS
settings, including values above a setting's max."""
import struct

import pytest

import features
import patch_menu as pm
import setting_ids
from features import Setting

CAVE = 0x28e60000                   # where the code under test runs; the real code cave starts after the code segment
ARGS = (0x11111111, 0x22222222, 0x33333333, 0x44444444)
PUSH_R4_LR, POP_R4_PC = struct.pack('<H', 0xb510), struct.pack('<H', 0xbd10)


def clobber(m):
    """A handler that leaves r0-r3 as junk, as a real one may."""
    for i in range(4):
        m.reg(f'r{i}', 0xdead0000 + i)


def returns(r0, r1):
    def handler(m):
        m.reg('r0', r0)
        m.reg('r1', r1)
    return handler


def aligned(log):
    """A handler that notes whether SP is 8-byte aligned at the call, as the AAPCS asks."""
    def handler(m):
        log.append(m.reg('sp') % 8 == 0)
        clobber(m)
    return handler


ORIG, B1, B2, A1, A2 = 0x28d90000, 0x28d91000, 0x28d92000, 0x28d93000, 0x28d94000


def test_chain_stub_calls_each_handler_in_order_with_the_hook_arguments(m4emu):
    m = m4emu.M4(pm.chain_cave(CAVE, ORIG, [B1, B2], [A1, A2]), CAVE)
    sp_ok = []
    for h in (B1, B2, A1, A2):
        m.stub(h, aligned(sp_ok))
    m.stub(ORIG, returns(0x1234, 0x5678))
    assert m.call(CAVE, *ARGS) == 0x1234
    assert m.reg('r1') == 0x5678, "the stub must return the original's r1 too (64-bit results)"
    assert [at for at, _ in m.log] == [B1, B2, ORIG, A1, A2]
    assert all(args == ARGS for _, args in m.log), 'every handler and the original get the hook\'s r0-r3'
    assert sp_ok == [True] * 4


def test_chain_stub_with_no_handlers_is_the_original(m4emu):
    m = m4emu.M4(pm.chain_cave(CAVE, ORIG, [], []), CAVE)
    m.stub(ORIG, returns(7, 8))
    assert m.call(CAVE, *ARGS) == 7 and m.reg('r1') == 8
    assert m.log == [(ORIG, ARGS)]


def test_chain_stub_does_not_forward_stack_arguments(m4emu):
    """The 4-argument limit: a hooked function's 5th argument is 32 bytes further up the stack than it expects, so only functions
    with register arguments may be hooked."""
    m = m4emu.M4(pm.chain_cave(CAVE, ORIG, [B1], []), CAVE)
    m.stub(B1, clobber)
    seen = []
    m.stub(ORIG, lambda m: seen.append(m.stack_args(9)))
    m.u32(m4emu.STACK_TOP, 0x55555555)  # the caller's 5th argument, at its SP
    m.call(CAVE, *ARGS)
    assert seen[0][0] != 0x55555555 and seen[0][8] == 0x55555555


BASE = 0x28d8fa80
FN, CALLER, LIT = BASE + 0x1000, BASE + 0x600, BASE + 0x200
HANDLERS = {('a', 'before'): BASE + 0xa000, ('a', 'after'): BASE + 0xa100,
            ('b', 'before'): BASE + 0xa200, ('b', 'after'): BASE + 0xa300}
IN_ORDER = [HANDLERS['a', 'before'], HANDLERS['b', 'before'], FN, HANDLERS['a', 'after'], HANDLERS['b', 'after']]


def patch():
    """A Patch over 32 KB of zeros mapped at BASE, without firmware (as in test_customos.py)."""
    p = pm.Patch.__new__(pm.Patch)
    p.e0, p.mods, p.ids = bytearray(0x10000), [], {}
    p.segs = [(0, 0, 0x8000, BASE, 0x8000)] * 7
    p.cave, p.owner, p.written, p.chains = pm.Cave(BASE + 0x8000), 'CustomOS', [], {}
    return p


def two_features(p, chain, *where):
    """Features a and b each put a before and an after handler on one site, a first."""
    for owner in ('a', 'b'):
        p.owner = owner
        chain(*where, before=HANDLERS[owner, 'before'], after=HANDLERS[owner, 'after'])
    p.finish_chains()


def emulate(m4emu, p, *code):
    """The cave as the module, the given (va, length) of the patched segment as code, and stubs for the handlers."""
    m = m4emu.M4(p.cave.buf, p.cave.va)
    for va, n in code:
        m.load(va, p.read(va, n))
    for h in HANDLERS.values():
        m.stub(h, clobber)
    return m


def test_chain_ptr_wraps_the_function_a_pointer_calls(m4emu):
    p = patch()
    p.put(LIT, struct.pack('<I', FN | 1))
    p.written.clear()
    two_features(p, p.chain_ptr, LIT, FN | 1)
    a = pm.Asm(CALLER)                  # push {r4,lr}; r4 = LIT; ldr r4,[r4]; blx r4; pop {r4,pc}
    a.raw(PUSH_R4_LR)
    a.movw_movt(4, LIT)
    a.h(0x6824, 0x47a0)
    a.raw(POP_R4_PC)
    m = emulate(m4emu, p)
    m.load(CALLER, a.bytes())
    m.write(LIT, p.read(LIT, 4))
    m.stub(FN, returns(0x1234, 0))
    assert m.call(CALLER, *ARGS) == 0x1234
    assert [at for at, _ in m.log] == IN_ORDER
    assert all(args == ARGS for _, args in m.log)


def test_chain_bl_wraps_the_call(m4emu):
    p = patch()
    p.put(CALLER, PUSH_R4_LR + pm.bl(CALLER + 2, FN) + POP_R4_PC)
    p.written.clear()
    two_features(p, p.chain_bl, CALLER + 2, FN)
    m = emulate(m4emu, p, (CALLER, 8))
    m.stub(FN, returns(0x1234, 0))
    assert m.call(CALLER, *ARGS) == 0x1234      # and the caller's own pop {r4,pc} ran, or SP would be off
    assert [at for at, _ in m.log] == IN_ORDER
    assert all(args == ARGS for _, args in m.log)


# push {r4,lr}; sub sp,#24; adds r0,r0,r1; add sp,#24; pop {r4,pc}: r0 + r1, with a prologue the entry chain has to move
ADD_FN = bytes.fromhex('10b5 86b0 4018 06b0 10bd')


def test_entry_chain_runs_the_handlers_and_the_moved_prologue(m4emu):
    p = patch()
    p.put(FN, ADD_FN)
    p.written.clear()
    two_features(p, p.chain_entry, FN, ADD_FN[:4])
    m = emulate(m4emu, p, (FN, len(ADD_FN)))
    assert m.call(FN, 3, 4) == 7
    assert [at for at, _ in m.log] == [h for h in IN_ORDER if h != FN]
    assert [args[:2] for _, args in m.log] == [(3, 4)] * 4


UNSET = object()


def setting_get(stored):
    """GET_VALUE answering stored (UNSET: the ID has no value)."""
    def get_value(m):
        if stored is UNSET:
            m.reg('r0', -1)
        else:
            m.u32(m.reg('r1') + 4, stored)
            m.reg('r0', 0)
    return get_value


@pytest.mark.parametrize('stored, value', [(UNSET, 2), (0, 0), (3, 3), (4, 4), (5, 2), (255, 2), (0xffffffff, 2)])
def test_setting_get_returns_the_default_when_unset_or_above_max(m4emu, tmp_path, stored, value):
    src = tmp_path / 'get.s'
    src.write_text('.syntax unified\n.thumb\n.include "customos.inc"\nCUSTOMOS_SETTING_GET\n')
    code, sym = m4emu.assemble(str(src), [], {})
    m = m4emu.M4(code, CAVE)
    m.stub(pm.GET_VALUE, setting_get(stored))
    assert m.call(CAVE + sym['customos_setting_get'], 104, 4, 2) == value
    assert [args[0] for args in m.calls(pm.GET_VALUE)] == [104]


TABLES, VALUE, DST = 0x28e70000, 0x28e80000, 0x28e81000
DEMO = Setting('pos', b'Demo\nPosition', (b'Middle', b'Top', b'Left', b'Bottom', b'Right'), default=2)


def settings():
    """Every feature's settings at their IDs, and a 0..4 one with a default of 2 at the first ID none of them uses."""
    ids = setting_ids.by_name()
    real = {ids[f'{features.name(f)}.{s.key}']: s for f in features.load() for s in getattr(f, 'SETTINGS', ())}
    return {**real, next(pid for pid in pm.MAIN_STORE_IDS if pid not in real): DEMO}


def text_fn(m4emu, settings):
    """The value-text cave for {ID: Setting}, its tables in memory, and STRCPY copying the chosen string."""
    tables, at = {}, TABLES
    for pid, s in settings.items():
        tables[pid] = (at, s.max, s.default)
        at += pm.VALUE_LEN * len(s.values)
    m = m4emu.M4(pm.text_cave(CAVE, tables), CAVE)
    for pid, s in settings.items():
        m.write(tables[pid][0], b''.join(pm.padded(v) for v in s.values))
    m.stub(pm.STRCPY, lambda m: m.write(m.reg('r0'), m.read(m.reg('r1'), pm.VALUE_LEN)))
    return m, tables


def text(m, pid, value):
    m.u32(VALUE + 4, value)
    m.write(DST, b'\xff' * pm.VALUE_LEN)
    assert m.call(CAVE, pid, VALUE, DST, pm.VALUE_LEN) == 0
    return m.read(DST, pm.VALUE_LEN).split(b'\0')[0]


@pytest.mark.parametrize('pid', sorted(settings()))
def test_value_text_shows_each_value(m4emu, pid):
    s = settings()[pid]
    m, tables = text_fn(m4emu, settings())
    for v, want in enumerate(s.values):
        assert text(m, pid, v) == want
    assert [args[1] for args in m.calls(pm.STRCPY)] == [tables[pid][0] + pm.VALUE_LEN * v for v in range(len(s.values))]


@pytest.mark.parametrize('pid', sorted(settings()))
@pytest.mark.parametrize('value', [lambda s: s.max + 1, lambda s: 255, lambda s: 0x80000000, lambda s: 0xffffffff])
def test_value_text_above_max_shows_the_default(m4emu, pid, value):
    s = settings()[pid]
    m, _ = text_fn(m4emu, settings())
    assert text(m, pid, value(s)) == s.values[s.default]


def test_value_text_leaves_other_ids_to_the_stock_function(m4emu):
    m, _ = text_fn(m4emu, settings())
    other = next(pid for pid in range(1, 256) if pid not in settings())
    seen = []

    def stock_rest(m):
        """TEXT_FN_CONT: check the frame the cave built is the stock prologue's, then run the stock epilogue."""
        sp = m.reg('sp')
        seen.append((tuple(m.reg(f'r{i}') for i in range(4)), sp, m.stack_args(8)[5:]))
        m.reg('r4', m.u32(sp + 0x14))
        m.reg('r5', m.u32(sp + 0x18))
        m.reg('lr', m.u32(sp + 0x1c))
        m.reg('sp', sp + 0x20)
        m.reg('r0', 0x77)
    m.stub(pm.TEXT_FN_CONT, stock_rest)
    assert m.call(CAVE, other, VALUE, DST, pm.VALUE_LEN) == 0x77
    assert seen == [((other, VALUE, DST, pm.VALUE_LEN), m4emu.STACK_TOP - 0x20, [0x1004, 0x1005, m4emu.RETURN | 1])]
    assert m.calls(pm.STRCPY) == []
