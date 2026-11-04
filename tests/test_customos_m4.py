"""The M4 code tools/patch_menu.py generates, run in unicorn (tests/m4emu.py): the shared-hook stub, an entry chain through its
moved prologue, customos_setting_get, and the value text of CustomOS settings, including values above a setting's max."""
import pytest

import m4emu
import features
import patch_menu as pm
import setting_ids
from features import Setting
from m4emu import M4, RETURN, STACK_TOP

CAVE = 0x28e60000                   # where the code under test runs; the real code cave starts after the code segment
ARGS = (0x11111111, 0x22222222, 0x33333333, 0x44444444)


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


def test_chain_stub_calls_each_handler_in_order_with_the_hook_arguments():
    m = M4(pm.chain_cave(CAVE, ORIG, [B1, B2], [A1, A2]), CAVE)
    sp_ok = []
    for h in (B1, B2, A1, A2):
        m.stub(h, aligned(sp_ok))
    m.stub(ORIG, returns(0x1234, 0x5678))
    assert m.call(CAVE, *ARGS) == 0x1234
    assert m.reg('r1') == 0x5678, "the stub must return the original's r1 too (64-bit results)"
    assert [at for at, _ in m.log] == [B1, B2, ORIG, A1, A2]
    assert all(args == ARGS for _, args in m.log), 'every handler and the original get the hook\'s r0-r3'
    assert sp_ok == [True] * 4


def test_chain_stub_with_no_handlers_is_the_original():
    m = M4(pm.chain_cave(CAVE, ORIG, [], []), CAVE)
    m.stub(ORIG, returns(7, 8))
    assert m.call(CAVE, *ARGS) == 7 and m.reg('r1') == 8
    assert m.log == [(ORIG, ARGS)]


BASE = 0x28d8fa80
# push {r4,lr}; sub sp,#24; adds r0,r0,r1; add sp,#24; pop {r4,pc}: r0 + r1, with a prologue the entry chain has to move
ADD_FN = bytes.fromhex('10b5 86b0 4018 06b0 10bd')


def patch():
    """A Patch over 32 KB of zeros mapped at BASE, without firmware (as in test_customos.py)."""
    p = pm.Patch.__new__(pm.Patch)
    p.e0, p.mods, p.ids = bytearray(0x10000), [], {}
    p.segs = [(0, 0, 0x8000, BASE, 0x8000)] * 7
    p.cave, p.owner, p.written, p.chains = pm.Cave(BASE + 0x8000), 'CustomOS', [], {}
    return p


def test_entry_chain_runs_the_handlers_and_the_moved_prologue():
    fn, before, after = BASE + 0x400, BASE + 0xa000, BASE + 0xb000
    p = patch()
    p.put(fn, ADD_FN)
    p.written.clear()
    p.chain_entry(fn, ADD_FN[:4], before=before, after=after)
    p.finish_chains()
    m = M4(p.read(BASE, 0x8000), BASE)
    m.write(p.cave.va, p.cave.buf)
    m.stub(before, clobber)
    m.stub(after, clobber)
    assert m.call(fn, 3, 4) == 7
    assert [at for at, _ in m.log] == [before, after]
    assert [args[:2] for _, args in m.log] == [(3, 4), (3, 4)]


GET_VALUE = pm.GET_VALUE
UNSET = object()


def setting_get(stored):
    """customos_setting_get assembled as a module, with GET_VALUE answering stored (UNSET: the ID has no value)."""
    def get_value(m):
        if stored is UNSET:
            m.reg('r0', -1)
        else:
            m.u32(m.reg('r1') + 4, stored)
            m.reg('r0', 0)
    return get_value


@pytest.fixture(scope='module')
def get_module(tmp_path_factory):
    src = tmp_path_factory.mktemp('m4') / 'get.s'
    src.write_text('.syntax unified\n.thumb\n.include "customos.inc"\nCUSTOMOS_SETTING_GET\n')
    return m4emu.assemble(str(src), [], {})


@m4emu.CLANG
@pytest.mark.parametrize('stored, value', [(UNSET, 2), (0, 0), (3, 3), (4, 4), (5, 2), (255, 2), (0xffffffff, 2)])
def test_setting_get_returns_the_default_when_unset_or_above_max(get_module, stored, value):
    code, sym = get_module
    m = M4(code, CAVE)
    m.stub(GET_VALUE, setting_get(stored))
    assert m.call(CAVE + sym['customos_setting_get'], 104, 4, 2) == value
    assert [args[0] for args in m.calls(GET_VALUE)] == [104]


TABLES, VALUE, DST = 0x28e70000, 0x28e80000, 0x28e81000
DEMO = Setting('pos', b'Demo\nPosition', (b'Middle', b'Top', b'Left', b'Bottom', b'Right'), default=2)


def text_fn(settings):
    """The value-text cave for {ID: Setting}, its tables in memory, and STRCPY copying the chosen string."""
    tables, at = {}, TABLES
    for pid, s in settings.items():
        tables[pid] = (at, s.max, s.default)
        at += pm.VALUE_LEN * len(s.values)
    m = M4(pm.text_cave(CAVE, tables), CAVE)
    for pid, s in settings.items():
        m.write(tables[pid][0], b''.join(pm.padded(v) for v in s.values))
    m.stub(pm.STRCPY, lambda m: m.write(m.reg('r0'), m.read(m.reg('r1'), pm.VALUE_LEN)))
    return m, tables


def text(m, pid, value):
    m.u32(VALUE + 4, value)
    m.write(DST, b'\xff' * pm.VALUE_LEN)
    assert m.call(CAVE, pid, VALUE, DST, pm.VALUE_LEN) == 0
    return m.read(DST, pm.VALUE_LEN).split(b'\0')[0]


def settings():
    """Every feature's settings at their IDs, and a 0..4 one with a default of 2 at the first ID none of them uses."""
    ids = setting_ids.by_name()
    real = {ids[f'{features.name(f)}.{s.key}']: s for f in features.load() for s in getattr(f, 'SETTINGS', ())}
    return {**real, next(pid for pid in pm.MAIN_STORE_IDS if pid not in real): DEMO}


@pytest.mark.parametrize('pid', sorted(settings()))
def test_value_text_shows_each_value(pid):
    s = settings()[pid]
    m, tables = text_fn(settings())
    for v, want in enumerate(s.values):
        assert text(m, pid, v) == want
    assert [args[1] for args in m.calls(pm.STRCPY)] == [tables[pid][0] + pm.VALUE_LEN * v for v in range(len(s.values))]


@pytest.mark.parametrize('pid', sorted(settings()))
@pytest.mark.parametrize('value', [lambda s: s.max + 1, lambda s: 255, lambda s: 0x80000000, lambda s: 0xffffffff])
def test_value_text_above_max_shows_the_default(pid, value):
    s = settings()[pid]
    m, _ = text_fn(settings())
    assert text(m, pid, value(s)) == s.values[s.default]


def test_value_text_leaves_other_ids_to_the_stock_function():
    m, _ = text_fn(settings())
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
    assert m.call(CAVE, 22, VALUE, DST, pm.VALUE_LEN) == 0x77
    assert seen == [((22, VALUE, DST, pm.VALUE_LEN), STACK_TOP - 0x20, [0x1004, 0x1005, RETURN | 1])]
    assert m.calls(pm.STRCPY) == []
