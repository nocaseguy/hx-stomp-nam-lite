"""Features beyond Entry 0 and on/off flags: p.entry(n) and Entry 8 items (tools/image_store.py), p.add_glyph, inputs that take
values (features.Input, p.input), and hooks one feature owns (p.own_entry)."""
import hashlib
import os
import struct
import subprocess
import sys
import types

import pytest

import features
import image_store as ims
import l6ia
import patch_amp as pa
import patch_menu as pm
from features import Input

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = 0x28d8fa80
FONT = b'hx21_regularFont'


def fake(name, **attrs):
    m = types.ModuleType(f'features.{name}')
    m.__dict__.update(attrs)
    return m


def store():
    """A tiny image store: Entry 7 with an image Pic (3x2) and a 4-slot font with slot 0 drawn; Entry 8 with their two items."""
    names = [b'Pic', FONT]
    e7 = bytearray(0xf0)
    struct.pack_into('<I', e7, 0, ims.E7_MAGIC)
    struct.pack_into('<2I', e7, 0x10, len(names), 0x60)
    at = 0x34
    for i, n in enumerate(names):
        struct.pack_into('<2I', e7, 0x24 + 8 * i, at, len(n))
        e7[at:at + len(n)] = n
        at += len(n)
    struct.pack_into('<6I', e7, 0x60 + 8, 0, 0, 0, 2, 3, 16)
    struct.pack_into('<2I', e7, 0x60 + ims.RECORD + 40, 4, 0xc0)
    struct.pack_into('<3I', e7, 0xc0, 21, 9, 1)
    for slot in (1, 2, 3):
        struct.pack_into('<3I', e7, 0xc0 + 12 * slot, 0, 0, ims.EMPTY_GLYPH)
    items = [b'\x11\x22' * 6, b'\x33\x44' * 9 * 21]
    e8 = bytearray(struct.pack('<6I', ims.E8_MAGIC, 1, len(items), 0x18, 0x28, 0))
    e8 += b'\0' * 16
    for i, data in enumerate(items):
        struct.pack_into('<2I', e8, 0x18 + 8 * i, len(data), len(e8))
        e8 += data
    struct.pack_into('<I', e8, 20, len(e8))
    return bytes(e7), bytes(e8)


def patch(env=None, mods=(), entries=None):
    """A Patch over 64 KB of zeros mapped at BASE, with the tiny image store as Entries 7 and 8."""
    p = pm.Patch.__new__(pm.Patch)
    p.e0, p.mods, p.ids = bytearray(0x10000), list(mods), {}
    p.segs = [(0, 0, 0x8000, BASE, 0x8000)] * 7
    p.cave, p.owner, p.written, p.chains = pm.Cave(BASE + 0x8000), 'CustomOS', [], {}
    e7, e8 = store()
    p.load, p.entries, p.owned = (entries or {7: e7, 8: e8}).__getitem__, {}, {}
    p.values = {features.name(m): features.values(m, env or {}) for m in mods}
    return p


# Inputs

def test_a_flag_tuple_turns_a_feature_on_with_any_of_them():
    a, b = fake('a', FLAG=('HX_A', 'HX_A_TEXT')), fake('b', FLAG='HX_B')
    assert features.enabled([a, b], {}) == []
    assert features.enabled([a, b], {'HX_A_TEXT': 'hi'}) == [a]
    assert features.enabled([a, b], {'HX_A': '', 'HX_B': '1'}) == [b]


def test_inputs_take_text_choices_paths_and_mappings(tmp_path):
    (tmp_path / 'pic.png').write_bytes(b'x')
    (tmp_path / 'g.png').write_bytes(b'y')
    f = fake('splash', FLAG=('HX_SPLASH', 'HX_SPLASH_TEXT'), INPUTS=(
        Input('HX_SPLASH', path=True), Input('HX_SPLASH_FIT', choices=('fill', 'fit'), default='fill'),
        Input('HX_SPLASH_GLYPHS', path=True, mapping=True)))
    env = {'HX_SPLASH': 'pic.png', 'HX_SPLASH_TEXT': 'HXS OS \U0001f3b8', 'HX_SPLASH_GLYPHS': '\U0001f3b8=g.png,\U0001f525=pic.png'}
    assert features.values(f, env, str(tmp_path)) == {
        'HX_SPLASH': str(tmp_path / 'pic.png'), 'HX_SPLASH_TEXT': 'HXS OS \U0001f3b8', 'HX_SPLASH_FIT': 'fill',
        'HX_SPLASH_GLYPHS': {'\U0001f3b8': str(tmp_path / 'g.png'), '\U0001f525': str(tmp_path / 'pic.png')}}
    assert features.values(f, {}, str(tmp_path)) == {'HX_SPLASH': None, 'HX_SPLASH_TEXT': None, 'HX_SPLASH_FIT': 'fill',
                                                    'HX_SPLASH_GLYPHS': {}}


@pytest.mark.parametrize('env, error', [
    ({'HX_SPLASH_FIT': 'stretch'}, "HX_SPLASH_FIT is one of fill, fit, not 'stretch'"),
    ({'HX_SPLASH': 'missing.png'}, 'HX_SPLASH: no file'),
    ({'HX_SPLASH_GLYPHS': 'g.png'}, 'HX_SPLASH_GLYPHS takes key=value pairs'),
    ({'HX_SPLASH_GLYPHS': 'a=g.png,b='}, 'HX_SPLASH_GLYPHS takes key=value pairs'),
])
def test_a_wrong_input_fails_the_build(tmp_path, env, error):
    (tmp_path / 'g.png').write_bytes(b'y')
    f = fake('splash', FLAG='HX_SPLASH', INPUTS=(
        Input('HX_SPLASH', path=True), Input('HX_SPLASH_FIT', choices=('fill', 'fit'), default='fill'),
        Input('HX_SPLASH_GLYPHS', path=True, mapping=True)))
    with pytest.raises(SystemExit, match=error):
        features.values(f, env, str(tmp_path))


def test_p_input_reads_only_the_features_own_inputs():
    f = fake('bpm', FLAG='HX_BPM', INPUTS=(Input('HX_BPM_STYLE', default='dots'),))
    p = patch({'HX_BPM': '1', 'HX_OTHER': 'x'}, [f])
    p.owner = 'bpm'
    assert (p.input('HX_BPM'), p.input('HX_BPM_STYLE')) == ('1', 'dots')
    with pytest.raises(SystemExit, match='bpm reads HX_OTHER, which is not its FLAG or in its INPUTS'):
        p.input('HX_OTHER')


def test_build_py_resolves_input_paths_from_where_it_started():
    src = open(os.path.join(ROOT, 'build.py')).read()
    assert '"tools/patch_menu.py", base, titled, "--cwd", os.getcwd()' in src


# Entries 7 and 8

def test_image_store_reads_images_fonts_and_items():
    e7, e8 = store()
    assert ims.image(e7, e8, b'Pic') == ims.Image(0, 3, 2, 16, 0x28, 12)
    assert ims.font(e7, FONT) == (4, 0xc0)
    assert ims.cell_height(e7, FONT) == 21
    with pytest.raises(SystemExit, match='no Nope in the image store'):
        ims.record(e7, b'Nope')
    with pytest.raises(SystemExit, match='Entry 8 has no item 2'):
        ims.item(e8, 2)


def test_pixel_puts_blue_in_the_top_bits():
    assert (ims.pixel(255, 0, 0), ims.pixel(0, 255, 0), ims.pixel(0, 0, 255)) == (0x001f, 0x07e0, 0xf800)
    assert ims.pixel_rgb(0x001f) == (255, 0, 0)


def test_entry_writes_are_checked_for_overlap_per_entry():
    p = patch()
    p.owner = 'splash'
    p.entry(8).put(0x28, b'\0' * 12, 'the splash')
    p.put(BASE + 0x28, b'\1' * 4, 'an Entry 0 write at the same number')
    p.entry(7).put(0x28, b'\2' * 4, 'an Entry 7 write at the same number')
    p.owner = 'emoji'
    with pytest.raises(SystemExit, match=r'emoji \(a glyph\) and splash \(the splash\) both patch Entry 8 at 0x30'):
        p.entry(8).put(0x30, b'\0' * 2, 'a glyph')
    with pytest.raises(SystemExit, match='Entry 8 has no bytes'):
        p.entry(8).put(len(store()[1]) - 2, b'\0' * 4)
    with pytest.raises(SystemExit, match='Entry 0 is the Patch itself'):
        p.entry(0)


def test_entry_expect_and_expect_md5():
    p = patch()
    e8 = p.entry(8)
    e8.expect(0x28, b'\x11\x22', 'Pic')
    e8.expect_md5(0x28, 12, hashlib.md5(b'\x11\x22' * 6).hexdigest(), 'Pic')
    with pytest.raises(SystemExit, match=r'Pic is not the stock one \(Entry 8 at 0x28, 12 bytes\)'):
        e8.expect_md5(0x28, 12, '0' * 32, 'Pic')


def test_entry8_items_go_after_its_end_with_a_copy_of_the_table():
    p = patch()
    e8 = p.entry(8)
    stock = e8.stock
    assert (e8.add_item(b'\xaa' * 6), e8.add_item(b'\xbb' * 4)) == (2, 3)
    out = e8.bytes()
    assert out[len(stock):len(stock) + 2] == b'\0' * 2 and out[16:20] == stock[16:20] and out[0x18:len(stock)] == stock[0x18:]
    assert out.startswith(stock[:8]) and struct.unpack_from('<I', out, 20)[0] == len(out)
    assert [ims.item(out, i) for i in range(4)] == [ims.item(stock, 0), ims.item(stock, 1), (0x1b0, 6), (0x1b8, 4)]
    assert out[0x1b0:0x1b6] == b'\xaa' * 6 and out[0x1b8:0x1bc] == b'\xbb' * 4
    assert struct.unpack_from('<I', out, 12)[0] == 0x1bc
    again = ims.append_items(out, [b'\xcc' * 2])     # a store whose table has already moved
    assert ims.item(again, 4)[1] == 2 and ims.item(again, 3) == (0x1b8, 4)
    with pytest.raises(SystemExit, match='only Entry 8'):
        p.entry(7).add_item(b'x')


def test_entry_output_is_entry0_and_the_entries_that_changed():
    p = patch()
    p.entry(7).put(0x30, b'\0' * 4)
    p.entry(8)
    p.entry0 = lambda: b'e0'
    assert sorted(p.output()) == [0, 7]


def test_an_entry_outgrowing_its_partition_fails(monkeypatch):
    monkeypatch.setitem(pm.Entry.MAX, 8, 0x200)
    p = patch()
    p.entry(8).add_item(b'\0' * 0x100)
    with pytest.raises(SystemExit, match='Entry 8 would be 0x2c8 bytes; its partition holds 0x200'):
        p.entry(8).bytes()


def test_add_glyph_fills_an_empty_slot_with_a_new_item():
    p = patch()
    p.owner = 'emoji'
    px = b'\x01\x00' * 2 * 21
    p.add_glyph(FONT, 2, 2, px)
    e7, e8 = p.entry(7).bytes(), p.entry(8).bytes()
    assert ims.glyph(e7, 0xc0, 2) == (21, 2, 2)
    off, ln = ims.item(e8, 2)
    assert e8[off:off + ln] == px
    with pytest.raises(SystemExit, match='slot 0x0 of hx21_regularFont is not an empty slot'):
        p.add_glyph(FONT, 0, 2, px)
    with pytest.raises(SystemExit, match='slot 0x4 of hx21_regularFont is not an empty slot'):
        p.add_glyph(FONT, 4, 2, px)
    with pytest.raises(SystemExit, match='a 3 wide glyph of hx21_regularFont is 126 bytes, not 84'):
        p.add_glyph(FONT, 3, 3, px)


def test_two_features_taking_one_glyph_slot_fail():
    p = patch()
    p.owner = 'emoji'
    p.add_glyph(FONT, 1, 2, b'\0' * 84, 'the guitar')
    p.owner = 'splash'
    with pytest.raises(SystemExit, match='splash: slot 0x1 of hx21_regularFont is not an empty slot'):
        p.add_glyph(FONT, 1, 2, b'\0' * 84)
    with pytest.raises(SystemExit, match=r'splash \(its slot\) and emoji \(the guitar\) both patch Entry 7 at 0xd4'):
        p.entry(7).put(0xc0 + 20, struct.pack('<I', 9), 'its slot')


# Owned hooks

FN = BASE + 0x400
PROLOGUE = bytes.fromhex('82b0 2de9f04f')        # sub sp,#8; push.w {r4-r11,lr}, as the text renderer's


def test_own_entry_jumps_to_the_handler_and_keeps_the_prologue_for_stock():
    p = patch()
    p.put(FN, PROLOGUE)
    p.written.clear()
    p.owner = 'splash'
    hook = p.own_entry(FN, PROLOGUE, 'the text renderer')
    tramp = hook.stock
    hook.to(BASE + 0x9000)
    assert p.read(FN, 6) == pm.thumb_bw(FN, BASE + 0x9000) + b'\x00\xbf'
    assert tramp == BASE + 0x8000 and p.cave.buf[:10] == PROLOGUE + pm.thumb_bw(tramp + 6, FN + 6)
    p.finish_chains()


def test_a_second_owner_a_chain_or_a_write_on_an_owned_hook_fails():
    p = patch()
    p.put(FN, PROLOGUE)
    p.written.clear()
    p.owner = 'splash'
    p.own_entry(FN, PROLOGUE, 'the text renderer', BASE + 0x9000)
    p.owner = 'emoji'
    with pytest.raises(SystemExit, match=r'emoji \(its renderer\) and splash \(the text renderer\) both own 0x28d8fe80'):
        p.own_entry(FN, PROLOGUE, 'its renderer')
    with pytest.raises(SystemExit, match='emoji chains 0x28d8fe80, which splash owns'):
        p.chain_entry(FN, PROLOGUE[:6], before=BASE + 0x9100)
    with pytest.raises(SystemExit, match=r'emoji \(a write\) and splash \(the text renderer\) both patch 0x28d8fe84'):
        p.put(FN + 4, b'\0\0')


def test_owning_a_chained_hook_fails():
    p = patch()
    p.put(FN, PROLOGUE)
    p.written.clear()
    p.owner = 'bpm'
    p.chain_entry(FN, PROLOGUE[:6], before=BASE + 0x9100)
    p.owner = 'splash'
    with pytest.raises(SystemExit, match=r'splash owns 0x28d8fe80 \(the text renderer\), which bpm chain'):
        p.own_entry(FN, PROLOGUE, 'the text renderer')


def test_an_owned_hook_needs_its_handler():
    p = patch()
    p.put(FN, PROLOGUE)
    p.written.clear()
    p.owner = 'splash'
    p.own_entry(FN, PROLOGUE, 'the text renderer')
    with pytest.raises(SystemExit, match='splash owns 0x28d8fe80 \\(the text renderer\\) but gave no handler'):
        p.finish_chains()


def test_a_pc_relative_prologue_can_be_owned_but_not_moved():
    p = patch()
    led = bytes.fromhex('00b5 234b')               # push {lr}; ldr r3,[pc,#0x8c]: the BPM's LED send
    p.put(FN, led)
    p.written.clear()
    p.owner = 'bpm'
    hook = p.own_entry(FN, led, 'the LED send', BASE + 0x9000)
    assert p.read(FN, 4) == pm.thumb_bw(FN, BASE + 0x9000)
    with pytest.raises(SystemExit, match='the instruction at 0x28d8fe82 reads the PC'):
        hook.stock
    p.put(FN + 0x100, led)
    p.written.pop()
    with pytest.raises(SystemExit, match='reads the PC, so it cannot run from the code cave'):
        p.chain_entry(FN + 0x100, led)


@pytest.mark.parametrize('code, at', [
    ('82b0 2de9f04f', None), ('10b5 86b0', None), ('f8b5 4678', None), ('30b5 85b0', None),
    ('00b5 234b', 2), ('10b5 03a0', 2), ('00b1 0000', 0), ('fee7', 0), ('01d0', 0), ('7844', 0),
    ('10b5 dff80c00', 2), ('10b5 5ff80c00', 2), ('10b5 fff7febf', 2), ('10b5 fff7feff', 2), ('10b5 dfe800f0', 2),
    ('10b5 0ff20400', 2), ('10b5 eff30080', None), ('10b5 4df8044d', None),
])
def test_pc_relative_finds_literal_loads_and_branches(code, at):
    assert pm.pc_relative(bytes.fromhex(code)) == at


def test_an_owned_hook_runs_the_handler_then_the_stock_function_with_its_stack_argument_rewritten():
    """In unicorn: a 9-argument function whose 9th ([sp,#0x10] on entry) the handler sets to 1 before the stock body reads it."""
    unicorn = pytest.importorskip('unicorn', reason='no unicorn (pip install unicorn)')
    from unicorn import arm_const as A
    p = patch()
    # the stock function: the prologue, r0 = the 9th argument, the epilogue
    p.put(FN, PROLOGUE + bytes.fromhex('0f98 bde8f04f 02b0 7047'))
    p.written.clear()
    p.owner = 'splash'
    hook = p.own_entry(FN, PROLOGUE, 'the text renderer')
    a = pm.Asm(p.next())
    a.h(0xf04f, 0x0c01, 0xf8cd, 0xc010)    # mov.w r12,#1; str.w r12,[sp,#0x10]
    a.bw(hook.stock)
    hook.to(p.add(a.bytes()))
    p.finish_chains()

    def run(code):
        uc = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_THUMB | unicorn.UC_MODE_MCLASS)
        uc.mem_map(BASE & ~0xfff, 0x20000)
        uc.mem_map(0x20000000, 0x1000)
        uc.mem_write(BASE, code)
        uc.mem_write(BASE + 0x8000, bytes(p.cave.buf))
        sp, stop = 0x20000800, BASE + 0x7000
        uc.mem_write(sp, struct.pack('<5I', 5, 6, 7, 8, 9))
        for reg, v in ((A.UC_ARM_REG_SP, sp), (A.UC_ARM_REG_LR, stop | 1), (A.UC_ARM_REG_R4, 0x44)):
            uc.reg_write(reg, v)
        uc.emu_start(FN | 1, stop, count=100)
        return uc.reg_read(A.UC_ARM_REG_R0), uc.reg_read(A.UC_ARM_REG_SP) == sp, uc.reg_read(A.UC_ARM_REG_R4)

    stock = bytearray(p.e0[:0x8000])
    stock[FN - BASE:FN - BASE + 6] = PROLOGUE
    assert run(bytes(stock)) == (9, True, 0x44)
    assert run(bytes(p.e0[:0x8000])) == (1, True, 0x44)


# On the stock firmware

RENDER_FN, RENDER_STOCK = 0x28db7aa4, bytes.fromhex('82b02de9f04f')
SPLASH_MD5 = '102fdff9f8738b232273a27d581c49ae'


@pytest.mark.firmware
def test_a_feature_over_entries_0_7_and_8_builds(tmp_path):
    """A demo feature turned on by either of two variables: it repaints HXStomp_Splash in place, adds a glyph to hx21_regularFont
    and owns the text renderer's start; the stock features stay as they were."""
    stock = os.environ.get('HX_STOMP_HXF')
    if not stock:
        pytest.skip('HX_STOMP_HXF is not set')
    data, _ = pa.load_l6ia_from_any(stock)
    load = lambda n: pa.get_entry_swapped(data, n)
    seen = {}

    def apply(p):
        e7, e8 = p.entry(7), p.entry(8)
        img = ims.image(e7.data, e8.data, b'HXStomp_Splash')
        e8.expect_md5(img.offset, img.length, SPLASH_MD5, 'HXStomp_Splash')
        e8.put(img.offset, struct.pack('<H', ims.pixel(255, 0, 0)) * (img.length // 2), 'the splash')
        p.add_glyph(FONT, 1, 3, b'\x01\x00' * 3 * 21, 'a glyph')
        hook = p.own_entry(RENDER_FN, RENDER_STOCK, 'the text renderer')
        a = pm.Asm(p.next())
        a.bw(hook.stock)
        hook.to(p.add(a.bytes()))
        seen.update(text=p.input('HX_DEMO_TEXT'), pic=p.input('HX_DEMO'))

    demo = fake('demo', FLAG=('HX_DEMO', 'HX_DEMO_TEXT'), apply=apply)
    plain, _ = pm.menu_entries(load, env={})
    assert sorted(plain) == [0]
    assert plain[0] == pm.menu_entry0(load(0), env={})[0]

    entries, on = pm.menu_entries(load, features.load() + [demo], {'HX_DEMO_TEXT': 'HXS OS \U0001f3b8'})
    assert [features.name(m) for m in on] == ['tuner', 'demo'] and sorted(entries) == [0, 7, 8]
    assert seen == {'text': 'HXS OS \U0001f3b8', 'pic': None}
    new, _, _ = l6ia.rebuild_archive(data, entries)
    path = tmp_path / 'demo.l6ia'
    path.write_bytes(new)
    report = subprocess.run([sys.executable, os.path.join(ROOT, 'tools/l6ia_verify.py'), str(path)], capture_output=True, text=True)
    assert 'ALL OK' in report.stdout

    e7, e8 = (pa.get_entry_swapped(new, n) for n in (7, 8))
    s7, s8 = load(7), load(8)
    img = ims.image(e7, e8, b'HXStomp_Splash')
    assert e8[img.offset:img.offset + 4] == b'\x1f\x00\x1f\x00'
    boot = ims.image(e7, e8, b'Screen_Boot')
    assert e8[boot.offset:boot.offset + boot.length] == s8[boot.offset:boot.offset + boot.length]
    count = struct.unpack_from('<I', s8, 8)[0]
    _, table = ims.font(e7, FONT)
    assert ims.glyph(e7, table, 1) == (21, 3, count)
    off, ln = ims.item(e8, count)
    assert e8[off:off + ln] == b'\x01\x00' * 63 and off >= len(s8)
    changed = [i for i in range(0, len(s8), 4) if e8[i:i + 4] != s8[i:i + 4]]
    assert {i for i in changed if not img.offset <= i < img.offset + img.length} == {8, 12, 20}
    assert table + 20 in {i for i in range(0, len(s7), 4) if e7[i:i + 4] != s7[i:i + 4]} <= {table + 12, table + 16, table + 20}
    segs = pa._parse_e0_segments(entries[0])
    o = pa._e0_vaddr_to_foff(segs, RENDER_FN, 6)
    assert entries[0][o + 4:o + 6] == b'\x00\xbf'


@pytest.mark.firmware
def test_menu_entry0_refuses_a_feature_that_needs_another_entry():
    stock = os.environ.get('HX_STOMP_HXF')
    if not stock:
        pytest.skip('HX_STOMP_HXF is not set')
    data, _ = pa.load_l6ia_from_any(stock)
    with pytest.raises(SystemExit, match='a feature needs Entry 8: build with menu_entries'):
        pm.menu_entry0(pa.get_entry_swapped(data, 0), [fake('x', apply=lambda p: p.entry(8))], {}, {})
