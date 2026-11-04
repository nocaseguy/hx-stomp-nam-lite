"""tools/patch_menu.py's CustomOS engine, tools/features and tools/setting_ids.py: IDs claimed once, settings that fit the menu,
writes that may not overlap, shared hooks, and the generated customos.inc."""
import os
import struct
import types

import pytest

import features
import m4asm
import patch_amp as pa
import patch_menu as pm
import setting_ids
from features import Setting

MODS = features.load()
SETTINGS = {f'{features.name(m)}.{s.key}': s for m in MODS for s in getattr(m, 'SETTINGS', ())}
CLANG = pytest.mark.skipif(not os.path.exists(m4asm.CLANG), reason='no Command Line Tools clang')


def test_ids_claimed_once():
    pids = [pid for pid, _, _ in setting_ids.IDS]
    names = [name for _, name, _ in setting_ids.IDS if name]
    assert len(pids) == len(set(pids)), 'an ID is listed twice in tools/setting_ids.py'
    assert len(names) == len(set(names)), 'a setting has two IDs in tools/setting_ids.py'
    assert all(pid in pm.MAIN_STORE_IDS for pid in pids)


def test_no_avoided_id_is_claimed():
    assert [pid for pid, name, note in setting_ids.IDS if name and note.startswith('avoid')] == []


def test_every_setting_has_an_id_and_every_claim_a_setting():
    ids = setting_ids.by_name()
    assert set(SETTINGS) - set(ids) == set(), 'settings with no line in tools/setting_ids.py'
    assert set(ids) - set(SETTINGS) == set(), 'IDs claimed by no feature setting: set them to None, keeping the note'


@pytest.mark.parametrize('name', sorted(SETTINGS))
def test_setting_fits_the_menu(name):
    pm.check_setting(name.split('.')[0], SETTINGS[name])


def test_feature_names_are_unique_and_conflicts_known():
    names = [features.name(m) for m in MODS]
    assert len(names) == len(set(names))
    for m in MODS:
        assert set(getattr(m, 'CONFLICTS', ())) <= set(names), f'{features.name(m)} conflicts with an unknown feature'


def fake(name, **attrs):
    m = types.ModuleType(f'features.{name}')
    m.__dict__.update(attrs)
    return m


def test_enabled_by_flag_and_conflicts():
    a, b, c = fake('a'), fake('b', FLAG='HX_B'), fake('c', FLAG='HX_C', CONFLICTS=('b',))
    assert features.enabled([a, b, c], {}) == [a]
    assert features.enabled([a, b, c], {'HX_B': '1'}) == [a, b]
    with pytest.raises(SystemExit, match='c cannot be built with b'):
        features.enabled([a, b, c], {'HX_B': '1', 'HX_C': '1'})


def test_check_setting_refuses_long_labels_and_values():
    pm.check_setting('f', Setting('k', b'Activate\nLock Tnr1', (b'Off', b'On')))
    with pytest.raises(SystemExit, match='label'):
        pm.check_setting('f', Setting('k', b'Activate1\nTuner', (b'Off', b'On')))
    with pytest.raises(SystemExit, match='values'):
        pm.check_setting('f', Setting('k', b'A\nB', (b'x' * 20,)))
    with pytest.raises(SystemExit, match='default'):
        pm.check_setting('f', Setting('k', b'A\nB', (b'Off', b'On'), default=2))


BASE = 0x28d8fa80


def patch():
    """A Patch over 64 KB of zeros mapped at BASE, without firmware."""
    p = pm.Patch.__new__(pm.Patch)
    p.e0, p.mods, p.ids = bytearray(0x10000), [], {}
    p.segs = [(0, 0, 0x8000, BASE, 0x8000)] * 7
    p.cave, p.owner, p.written, p.chains = pm.Cave(BASE + 0x8000), 'CustomOS', [], {}
    return p


def test_put_refuses_overlapping_writes():
    p = patch()
    p.owner = 'gr'
    p.put(BASE + 0x100, b'\0' * 4, 'the Home paint')
    p.put(BASE + 0x104, b'\1' * 4)
    p.owner = 'bpm'
    with pytest.raises(SystemExit, match=r'bpm \(the Home paint\) and gr \(the Home paint\) both patch 0x28d8fb82'):
        p.put(BASE + 0x102, b'\0' * 2, 'the Home paint')


def test_chains_share_a_site_in_feature_order():
    p = patch()
    lit, fn = BASE + 0x200, 0x10001095
    p.put(lit, struct.pack('<I', fn))
    p.written.clear()
    p.owner = 'gr'
    p.chain_ptr(lit, fn, before=BASE + 0x9000)
    p.owner = 'bpm'
    p.chain_ptr(lit, fn, before=BASE + 0x9100, after=BASE + 0x9200)
    with pytest.raises(SystemExit, match='bpm and gr hook 0x28d8fc80 in different ways'):
        p.chain_entry(lit, struct.pack('<I', fn))
    p.finish_chains()
    stub = p.u32(lit) - 1
    assert stub == BASE + 0x8000
    assert p.cave.buf.startswith(pm.chain_cave(stub, fn & ~1, [BASE + 0x9000, BASE + 0x9100], [BASE + 0x9200]))


def test_a_shared_hook_and_a_plain_write_to_it_fail():
    p = patch()
    site, target = BASE + 0x300, BASE + 0x5000
    p.put(site, pm.bl(site, target))
    p.written.clear()
    p.owner = 'dsp_meter'
    p.chain_bl(site, target, after=BASE + 0x9000)
    p.owner = 'bpm'
    p.put(site, b'\0' * 4, 'its own hook')
    with pytest.raises(SystemExit, match='both patch'):
        p.finish_chains()


def test_entry_chain_moves_the_prologue():
    p = patch()
    fn, stock = BASE + 0x400, bytes.fromhex('10b5 86b0')
    p.put(fn, stock)
    p.written.clear()
    p.chain_entry(fn, stock, before=BASE + 0x9000)
    p.finish_chains()
    tramp = BASE + 0x8000
    assert p.cave.buf[:8] == stock + pm.thumb_bw(tramp + 4, fn + 4)
    assert p.read(fn, 4) == pm.thumb_bw(fn, tramp + 8)


def test_customos_inc_lists_every_setting():
    inc = pm.customos_inc(MODS, setting_ids.by_name())
    for name, s in SETTINGS.items():
        sym = 'SETTING_' + name.replace('.', '_').upper()
        assert f'.equ {sym}, {setting_ids.by_name()[name]}\n' in inc
        assert f'.equ {sym}_MAX, {s.max}\n' in inc
        assert f'.equ {sym}_DEFAULT, {s.default}\n' in inc
    assert '.macro CUSTOMOS_SETTING_GET' in inc


@CLANG
def test_module_assembles_with_customos_inc(tmp_path):
    src = tmp_path / 'm.s'
    src.write_text('.syntax unified\n.thumb\n.include "customos.inc"\nentry:\n    movs r0, #SETTING_TUNER_LOCK\n'
                   '    movs r1, #SETTING_TUNER_LOCK_MAX\n    movs r2, #SETTING_TUNER_LOCK_DEFAULT\n    b customos_setting_get\n'
                   'CUSTOMOS_SETTING_GET\n')
    p = patch()
    p.mods, p.ids = MODS, setting_ids.by_name()
    m = p.module(str(src))
    assert m.va == BASE + 0x8000 and m['entry'] == m.va and m['customos_setting_get'] == m.va + 8
    assert p.cave.buf[:2] == struct.pack('<H', 0x2000 | setting_ids.by_name()['tuner.lock'])


@CLANG
def test_m4asm_refuses_relocations(tmp_path):
    src = tmp_path / 'r.s'
    src.write_text('.syntax unified\n.thumb\nf:\n    bl g\n.global g\n.thumb_func\ng:\n    bx lr\n')
    with pytest.raises(SystemExit, match='relocations'):
        m4asm.assemble_module(str(src))


@pytest.mark.firmware
def test_a_feature_with_settings_and_a_shared_hook_builds():
    """The tuner plus a feature with a 0..4 and a 0..1 setting on a second page, chaining the Home view's paint function."""
    stock = os.environ.get('HX_STOMP_HXF')
    if not stock:
        pytest.skip('HX_STOMP_HXF is not set')
    data, _ = pa.load_l6ia_from_any(stock)
    e0 = pa.get_entry_swapped(data, 0)
    paint_lit, paint = 0x28d96e28, 0x28dc8d39

    def apply(p):
        p.chain_ptr(paint_lit, paint, after=p.add(b'\x70\x47'))

    demo = fake('demo', SETTINGS=(Setting('pos', b'Demo\nPosition', (b'A', b'B', b'C', b'D', b'E'), default=2),
                                  Setting('dir', b'Demo\nDirection', (b'Normal', b'Reverse'))), apply=apply)
    ids = dict(setting_ids.by_name(), **{'demo.pos': 102, 'demo.dir': 128})
    new, on = pm.menu_entry0(e0, MODS + [demo], {}, ids)
    assert [features.name(m) for m in on] == ['tuner', 'demo']
    segs = pa._parse_e0_segments(new)

    def read(va, n):
        o = pa._e0_vaddr_to_foff(segs, va, n)
        return new[o:o + n]

    assert read(pm.NAMES_LONG + pm.NAME_LEN * 102, 13) == b'Demo\nPosition'
    tab, entry = pm.limits_entry(102)
    snippet = tab + 2 * struct.unpack('<H', read(entry, 2))[0]
    assert read(snippet, 8) == struct.pack('<4H', 0x2302, 0x2202, 0x2100, 0x2404)
    tab, entry = pm.limits_entry(128)
    assert tab + 2 * struct.unpack('<H', read(entry, 2))[0] == pm.ENUM01_TARGET
    stub = struct.unpack('<I', read(paint_lit, 4))[0]
    assert stub != paint and stub & 1


def test_stock_uses_finds_reads_writes_and_loops():
    base = 0x28d90000
    a = struct.pack('<H', 0x203f) + pm.bl(base + 2, pm.GET_VALUE)                      # movs r0,#63; bl GET_VALUE
    b = struct.pack('<H', 0x2155) + pm.bl(base + len(a) + 2, setting_ids.SETTERS[1])   # movs r1,#85; bl a setter
    c = struct.pack('<4H', 0x2469, 0x2c6c, 0x4620, 0xbf00)                             # movs r4,#105; cmp r4,#108; mov r0,r4; nop
    c += pm.bl(base + len(a) + len(b) + len(c), pm.GET_VALUE)
    blob = a + b + c
    uses = setting_ids.stock_uses(struct.unpack(f'<{len(blob) // 2}H', blob), base, pm.GET_VALUE)
    assert uses[63] == {'read': 1} and uses[85] == {'write': 1}
    assert [pid for pid in range(100, 112) if uses[pid]['loop']] == [105, 106, 107, 108]


def test_text_cave_takes_many_settings():
    tables = {pid: (BASE + 0x9000, 255, 0) for pid in pm.MAIN_STORE_IDS[:90]}
    assert len(pm.text_cave(BASE, tables)) > 90 * 20
