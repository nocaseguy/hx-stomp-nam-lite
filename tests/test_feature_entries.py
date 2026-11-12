"""Features beyond Entry 0 and on/off flags: p.entry(n) and Entry 8 items (tools/image_store.py), p.add_glyph, inputs that take
values (features.Input, p.input), and hooks one feature owns (p.own_entry, p.own_call)."""
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
import m4asm
import patch_amp as pa
import patch_menu as pm
from features import Input
from firmware import reader, stock as stock_l6ia, stock_e0

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = 0x28d8fa80
FONT = b'hx21_regularFont'


def fake(name, **attrs):
    m = types.ModuleType(f'features.{name}')
    m.__dict__.update(attrs)
    return m


def store(height=21):
    """A tiny image store: Entry 7 with an image Pic (3x2) and a 4-slot font with slot 0 drawn; Entry 8 with their two items."""
    names = [b'Pic', FONT]
    e7 = bytearray(0xf0)
    struct.pack_into('<I', e7, 0, ims.E7_MAGIC)
    struct.pack_into('<I', e7, 8, len(e7))
    struct.pack_into('<3I', e7, 0x10, len(names), 0x60, len(names))
    at = 0x34
    for i, n in enumerate(names):
        struct.pack_into('<2I', e7, 0x24 + 8 * i, at, len(n))
        e7[at:at + len(n)] = n
        at += len(n)
    struct.pack_into('<6I', e7, 0x60 + 8, 0, 0, 0, 2, 3, 16)
    struct.pack_into('<2I', e7, 0x60 + ims.RECORD + 40, 4, 0xc0)
    struct.pack_into('<3I', e7, 0xc0, height, 9, 1)
    for slot in (1, 2, 3):
        struct.pack_into('<3I', e7, 0xc0 + 12 * slot, 0, 0, ims.EMPTY_GLYPH)
    items = [b'\x11\x22' * 6, b'\x33\x44' * 9 * height]
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
    p.cave, p.owner, p.written, p.chains = pm.Cave(BASE + 0x8000), 'HXtra', [], {}
    e7, e8 = store()
    p.load = (entries or {7: e7, 8: e8}).__getitem__
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


@pytest.mark.parametrize('inp, value', [
    (Input('V', default='g.png', path=True), 'PATH/g.png'),
    (Input('V', default='a=g.png', path=True, mapping=True), {'a': 'PATH/g.png'}),
    (Input('V', default='fit', choices=('fill', 'fit')), 'fit'),
])
def test_an_input_default_is_read_as_a_set_value(tmp_path, inp, value):
    (tmp_path / 'g.png').write_bytes(b'y')
    f = fake('f', FLAG='HX_F', INPUTS=(inp,))
    got = features.values(f, {}, str(tmp_path))['V']
    assert got == (str(tmp_path / 'g.png') if value == 'PATH/g.png' else {'a': str(tmp_path / 'g.png')}
                   if isinstance(value, dict) else value)


@pytest.mark.parametrize('inp, error', [
    (Input('V', default='missing.png', path=True), 'V: no file'),
    (Input('V', default='stretch', choices=('fill', 'fit')), "V is one of fill, fit, not 'stretch'"),
    (Input('V', default='g.png', mapping=True), 'V takes key=value pairs'),
])
def test_a_wrong_input_default_fails_the_build(tmp_path, inp, error):
    with pytest.raises(SystemExit, match=error):
        features.values(fake('f', FLAG='HX_F', INPUTS=(inp,)), {}, str(tmp_path))


def test_inputs_are_checked_before_any_feature_applies():
    applied = []

    def load(n):
        raise AssertionError('Entry 0 was read before the inputs were checked')
    a = fake('a', ORDER=1, apply=lambda p: applied.append('a'))
    b = fake('b', ORDER=2, FLAG='HX_B', INPUTS=(Input('HX_B', choices=('on',)),), apply=lambda p: applied.append('b'))
    with pytest.raises(SystemExit, match="HX_B is one of on, not 'yes'"):
        pm.menu_entries(load, [a, b], {'HX_B': 'yes'}, {})
    assert applied == []


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


def test_an_expect_over_another_features_write_names_both():
    p = patch()
    p.owner = 'splash'
    p.entry(8).put(0x28, b'\0' * 12, 'the splash')
    p.put(BASE + 0x100, b'\1' * 4, 'its hook')
    p.owner = 'emoji'
    with pytest.raises(SystemExit, match=r'emoji \(Pic\) and splash \(the splash\) both patch Entry 8 at 0x2c'):
        p.entry(8).expect_md5(0x2c, 4, '0' * 32, 'Pic')
    with pytest.raises(SystemExit, match=r'emoji \(Pic\) and splash \(the splash\) both patch Entry 8 at 0x28'):
        p.entry(8).expect(0x20, b'\0' * 12, 'Pic')
    with pytest.raises(SystemExit, match=r'emoji \(the call\) and splash \(its hook\) both patch 0x28d8fb82'):
        p.expect(BASE + 0x102, b'\0\0', 'the call')
    p.owner = 'splash'
    with pytest.raises(SystemExit, match='the call is not at its stock address'):
        p.expect(BASE + 0x102, b'\0\0', 'the call')


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


def test_entry7_records_go_after_its_end_with_a_copy_of_the_stock_ones():
    p = patch()
    e7 = p.entry(7)
    stock = e7.stock
    assert (e7.add_record(b'\xaa' * ims.RECORD), e7.add_record(b'\xbb' * ims.RECORD)) == (2, 3)
    out = e7.bytes()
    assert out[:8] == stock[:8] and out[0xc:0x14] == stock[0xc:0x14] and out[0x1c:len(stock)] == stock[0x1c:]
    assert struct.unpack_from('<3I', out, 0x10) == (2, len(stock), 4) and struct.unpack_from('<I', out, 8)[0] == len(out)
    assert [out[ims.record_at(out, i):][:ims.RECORD] for i in range(2)] == [stock[0x60 + ims.RECORD * i:][:ims.RECORD] for i in range(2)]
    assert out[ims.record_at(out, 3):] == b'\xbb' * ims.RECORD
    assert ims.names(out) == ims.names(stock) and ims.record(out, b'Pic') == ims.record_at(out, 0)
    assert ims.font(out, FONT) == ims.font(stock, FONT)
    with pytest.raises(SystemExit, match='Entry 7 has no record 4'):
        ims.record_at(out, 4)
    with pytest.raises(SystemExit, match='only Entry 7'):
        p.entry(8).add_record(b'x' * ims.RECORD)
    with pytest.raises(SystemExit, match='of 48 bytes'):
        e7.add_record(b'x')


@pytest.mark.parametrize('word', [8, 0x14, 0x18])
def test_add_record_and_a_write_to_the_header_words_it_rewrites_fail(word):
    p = patch()
    p.owner = 'splash'
    p.entry(7).put(word, b'\0' * 4, 'its header word')
    p.owner = 'emoji'
    with pytest.raises(SystemExit, match=r'emoji \(Entry 7.s .*which add_record rewrites\) and splash \(its header word\)'):
        p.entry(7).add_record(b'x' * ims.RECORD)


def test_add_image_is_a_new_record_and_item_like_another_image():
    p = patch()
    px = bytes(range(16))
    assert p.add_image(0, 4, 2, px) == 2
    e7, e8 = p.entry(7).bytes(), p.entry(8).bytes()
    im = ims.image_at(e7, e8, 2)
    assert (im.item, im.width, im.height, im.bpp) == (2, 4, 2, 16) and e8[im.offset:im.offset + im.length] == px
    assert struct.unpack_from('<I', e7, ims.record_at(e7, 2) + 12)[0] == 2
    assert ims.image_at(e7, e8, 0) == ims.image(e7, e8, b'Pic')
    with pytest.raises(SystemExit, match='a 3x2 image is 12 bytes, not 16'):
        p.add_image(0, 3, 2, px)


@pytest.mark.firmware
def test_stock_records_repeat_their_item_and_counts_agree():
    """add_image copies a record and sets its item in words 2, 3 and 9, as every stock image record has it."""
    e7 = pa.get_entry_swapped(stock_l6ia(), 7)
    names, table, count = struct.unpack_from('<3I', e7, 0x10)
    assert names == count == 577 and struct.unpack_from('<I', e7, 8)[0] == len(e7)
    for i in range(count):
        w = struct.unpack_from('<12I', e7, table + ims.RECORD * i)
        if w[7] == 16:
            assert w[2] == w[3] == w[9], i


def test_peak_and_scaled():
    grey, white = ims.pixel(98, 98, 98), ims.pixel(255, 255, 255)
    px = struct.pack('<3H', 0, grey, white)
    assert ims.peak(px) == 1 and round(ims.peak(px[:4]), 2) == 0.39 and ims.peak(b'\0\0') == 0
    assert struct.unpack('<3H', ims.scaled(px, 2)) == (0, ims.pixel(196, 196, 196), white)
    assert ims.scaled(px, 1) == px
    assert struct.unpack('<H', ims.scaled(struct.pack('<H', ims.pixel(255, 0, 0)), 0.5))[0] == ims.pixel(132, 0, 0)


def test_trimmed_drops_black_border_rows_and_columns():
    # 3 columns of 3 from the bottom: only the middle column's lower two pixels are lit
    px = struct.pack('<9H', 0, 0, 0, 5, 6, 0, 0, 0, 0)
    assert ims.trimmed(px, 3, 3) == (struct.pack('<2H', 5, 6), 1, 2)
    assert ims.trimmed(b'\0' * 4, 1, 2) == (b'\0' * 4, 1, 2)


def test_resized_averages_by_area():
    white = ims.pixel(255, 255, 255)
    assert ims.resized(struct.pack('<H', white), 1, 1, 2, 2) == struct.pack('<4H', *[white] * 4)
    assert ims.resized(struct.pack('<2H', white, 0), 1, 2, 1, 1) == struct.pack('<H', 16 << 11 | 32 << 5 | 16)
    assert ims.resized(struct.pack('<2H', 0, white), 2, 1, 4, 1) == struct.pack('<4H', 0, 0, white, white)
    third = ims.resized(struct.pack('<3H', white, 0, 0), 3, 1, 1, 1)
    assert third == struct.pack('<H', 10 << 11 | 21 << 5 | 10)


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


def test_an_entry_exactly_its_partition_fits(monkeypatch):
    p = patch()
    p.entry(8).add_item(b'\0' * 0x100)
    monkeypatch.setitem(pm.Entry.MAX, 8, 0x2c8)
    assert len(p.entry(8).bytes()) == 0x2c8
    monkeypatch.setitem(pm.Entry.MAX, 8, 0x2c4)
    with pytest.raises(SystemExit, match='Entry 8 would be 0x2c8 bytes'):
        p.entry(8).bytes()


@pytest.mark.parametrize('word', [8, 12, 20])
def test_add_item_and_a_write_to_the_header_words_it_rewrites_fail(word):
    p = patch()
    p.owner = 'splash'
    p.entry(8).put(word, b'\0' * 4, 'its header word')
    p.owner = 'emoji'
    with pytest.raises(SystemExit, match=r'emoji \(Entry 8.s .*which add_item rewrites\) and splash \(its header word\)'):
        p.entry(8).add_item(b'x')
    p = patch()
    p.owner = 'emoji'
    p.entry(8).add_item(b'x')
    p.entry(8).add_item(b'y')
    p.owner = 'splash'
    with pytest.raises(SystemExit, match=r'splash \(its header word\) and emoji \(Entry 8.s .*which add_item rewrites\)'):
        p.entry(8).put(word, b'\0' * 4, 'its header word')


def test_add_glyph_takes_the_fonts_own_cell_height():
    e7, e8 = store(height=28)
    p = patch(entries={7: e7, 8: e8})
    p.add_glyph(FONT, 1, 2, b'\1\0' * 2 * 28)
    assert ims.glyph(p.entry(7).bytes(), 0xc0, 1) == (28, 2, 2)
    with pytest.raises(SystemExit, match='a 2 wide glyph of hx21_regularFont is 112 bytes, not 84'):
        p.add_glyph(FONT, 2, 2, b'\1\0' * 2 * 21)


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


@pytest.mark.parametrize('stock, error', [
    (bytes.fromhex('82b0 2de9'), 'give at least the 4 bytes a b.w takes, whole instructions'),
    (bytes.fromhex('82b0'), 'give at least the 4 bytes a b.w takes, whole instructions'),
    (bytes.fromhex('00b5 234b 2de9'), 'give at least the 4 bytes a b.w takes, whole instructions'),
    (bytes.fromhex('10b5 86b0'), 'the start of the function at 0x28d8fe80 is not at its stock address'),
])
def test_own_entry_refuses_short_cut_or_wrong_stock_bytes(stock, error):
    p = patch()
    p.put(FN, PROLOGUE)
    p.written.clear()
    p.owner = 'splash'
    with pytest.raises(SystemExit, match=error):
        p.own_entry(FN, stock, 'the text renderer')
    assert p.owned == {} and p.written == []


@pytest.mark.parametrize('stock, error', [
    (bytes.fromhex('82b0 2de9'), r'the instruction at 0x28d8fe82 is cut in two'),
    (bytes.fromhex('82b0'), 'give at least the 4 bytes a b.w takes'),
])
def test_chain_entry_refuses_short_or_cut_prologues(stock, error):
    p = patch()
    p.put(FN, PROLOGUE)
    with pytest.raises(SystemExit, match=error):
        p.chain_entry(FN, stock, before=BASE + 0x9000)


CALL, CALLEE = BASE + 0x100, BASE + 0x4000


@pytest.mark.parametrize('branch', [pm.bl, pm.thumb_bw])
def test_own_call_sends_a_bl_or_b_w_to_the_handler(branch):
    p = patch()
    p.put(CALL, branch(CALL, CALLEE))
    p.written.clear()
    p.owner = 'more_snapshots'
    p.own_call(CALL, CALLEE, 'the select', BASE + 0x9000)
    assert p.read(CALL, 4) == branch(CALL, BASE + 0x9000)
    p.finish_chains()


def test_own_call_refuses_a_call_of_another_function():
    p = patch()
    p.put(CALL, pm.bl(CALL, CALLEE + 2))
    p.written.clear()
    with pytest.raises(SystemExit, match='the call at 0x28d8fb80 is not at its stock address'):
        p.own_call(CALL, CALLEE, 'the select', BASE + 0x9000)
    assert p.owned == {}


def test_an_owned_call_cannot_be_owned_again_chained_or_written():
    p = patch()
    p.put(CALL, pm.bl(CALL, CALLEE))
    p.written.clear()
    p.owner = 'tuner'
    p.own_call(CALL, CALLEE, 'the tap', BASE + 0x9000)
    p.owner = 'bpm'
    with pytest.raises(SystemExit, match=r'bpm \(its tap\) and tuner \(the tap\) both own 0x28d8fb80'):
        p.own_call(CALL, CALLEE, 'its tap', BASE + 0x9100)
    with pytest.raises(SystemExit, match='bpm chains 0x28d8fb80, which tuner owns'):
        p.chain_bl(CALL, CALLEE, after=BASE + 0x9100)
    with pytest.raises(SystemExit, match=r'bpm \(a write\) and tuner \(the tap\) both patch 0x28d8fb82'):
        p.put(CALL + 2, b'\0\0')


def test_owning_a_chained_call_fails():
    p = patch()
    p.put(CALL, pm.bl(CALL, CALLEE))
    p.written.clear()
    p.owner = 'bpm'
    p.chain_bl(CALL, CALLEE, after=BASE + 0x9100)
    p.owner = 'tuner'
    with pytest.raises(SystemExit, match=r'tuner owns 0x28d8fb80 \(the tap\), which bpm chain'):
        p.own_call(CALL, CALLEE, 'the tap', BASE + 0x9000)


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


PC, CUT, IT = 'reads the PC', 'is cut in two by the end of the bytes', 'starts an IT block that runs past the end'


@pytest.mark.parametrize('code, why', [
    ('82b0 2de9f04f', None), ('10b5 86b0', None), ('f8b5 4678', None), ('30b5 85b0', None), ('10b5 eff30080', None),
    ('10b5 4df8044d', None), ('08bf 0120', None), ('10b5 0cbf 0120 0020', None),
    ('00b5 234b', (2, PC)), ('10b5 03a0', (2, PC)), ('00b1 0000', (0, PC)), ('fee7', (0, PC)), ('01d0', (0, PC)),
    ('7844', (0, PC)), ('10b5 dff80c00', (2, PC)), ('10b5 5ff80c00', (2, PC)), ('10b5 fff7febf', (2, PC)),
    ('10b5 fff7feff', (2, PC)), ('10b5 dfe800f0', (2, PC)), ('10b5 0ff20400', (2, PC)),
    ('9fed020a', (0, PC)), ('10b5 dfed010b', (2, PC)),      # vldr s0,[pc,#8]; vldr d16,[pc,#4]
    ('82b0 2de9', (2, CUT)), ('00b5 234b 2de9', (4, CUT)),
    ('10b5 08bf', (2, IT)), ('0cbf 0120', (0, IT)),          # it eq with nothing after it; ite eq with one of its two
])
def test_unmovable_finds_pc_reads_cut_instructions_and_open_it_blocks(code, why):
    assert pm.unmovable(bytes.fromhex(code)) == why


def test_an_owned_hook_runs_the_handler_then_the_stock_function_with_its_stack_argument_rewritten(m4emu):
    """A 9-argument function whose 9th ([sp,#0x10] on entry) the handler sets to 1 before the stock body reads it."""
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

    def run(fn_code):
        m4 = m4emu.M4(fn_code, FN)
        m4.load(p.cave.va, p.cave.buf)
        for i in range(5):
            m4.u32(m4emu.STACK_TOP + 4 * i, 5 + i)
        return m4.call(FN, 1, 2, 3, 4), [m4.u32(m4emu.STACK_TOP + 4 * i) for i in range(5)]

    body = p.read(FN + 6, 12)
    assert run(PROLOGUE + body) == (9, [5, 6, 7, 8, 9])
    assert run(p.read(FN, 18)) == (1, [5, 6, 7, 8, 1])


# On the stock firmware

RENDER_FN, RENDER_STOCK = 0x28db7aa4, bytes.fromhex('82b02de9f04f')
LED_SEND, LED_STOCK, LED_LIT, LED_LIT_VALUE = 0x28d98f74, bytes.fromhex('00b5234b'), 0x28d99004, 0x281c90a4
HOME_PAINT_LIT, HOME_PAINT = 0x28d96e28, 0x28dc8d39
HOME_CTOR_BL, HOME_CTOR = 0x28d96c44, 0x28dc91d0
SPLASH_MD5 = '102fdff9f8738b232273a27d581c49ae'
EPILOGUE = bytes.fromhex('bde8f04f 02b0 7047')     # pop.w {r4-r11,lr}; add sp,#8; bx lr: the renderer's prologue undone


@pytest.fixture(scope='module')
def stock():
    return stock_l6ia()


def stock_patch(data):
    return pm.Patch(pa.get_entry_swapped(data, 0), [], {})


def chain(p, kind):
    """A chain of each kind at its real site, which an owner then takes as a site of its own."""
    return {'entry': lambda: p.chain_entry(RENDER_FN, RENDER_STOCK, before=p.next()),
            'bl': lambda: p.chain_bl(HOME_CTOR_BL, HOME_CTOR, after=p.next()),
            'ptr': lambda: p.chain_ptr(HOME_PAINT_LIT, HOME_PAINT, after=p.next())}[kind]


SITES = {'entry': (RENDER_FN, RENDER_STOCK), 'bl': (HOME_CTOR_BL, pm.bl(HOME_CTOR_BL, HOME_CTOR)),
         'ptr': (HOME_PAINT_LIT, struct.pack('<I', HOME_PAINT))}


@pytest.mark.firmware
@pytest.mark.parametrize('kind', SITES)
def test_owning_a_site_and_chaining_it_fail_in_either_order(stock, kind):
    site, data = SITES[kind]
    p = stock_patch(stock)
    p.owner = 'splash'
    p.own_entry(site, data, 'its hook', p.next())
    p.owner = 'bpm'
    with pytest.raises(SystemExit, match=f'bpm chains {site:#x}, which splash owns \\(its hook\\)'):
        chain(p, kind)()
    p = stock_patch(stock)
    p.owner = 'bpm'
    chain(p, kind)()
    p.owner = 'splash'
    with pytest.raises(SystemExit, match=f'splash owns {site:#x} \\(its hook\\), which bpm chain'):
        p.own_entry(site, data, 'its hook')


@pytest.mark.firmware
@pytest.mark.parametrize('site, data', [(RENDER_FN, RENDER_STOCK), (LED_SEND, LED_STOCK)])
def test_two_owners_or_an_owner_and_a_write_fail_in_either_order(stock, site, data):
    p = stock_patch(stock)
    p.owner = 'splash'
    p.own_entry(site, data, 'its hook', p.next())
    p.owner = 'emoji'
    with pytest.raises(SystemExit, match=f'emoji \\(the hook\\) and splash \\(its hook\\) both own {site:#x}'):
        p.own_entry(site, data, 'the hook')
    for at in range(site, site + 4, 2):
        with pytest.raises(SystemExit, match=f'emoji \\(a write\\) and splash \\(its hook\\) both patch {at:#x}'):
            p.put(at, p.read(at, 2))
    p = stock_patch(stock)
    p.owner = 'emoji'
    p.put(site + 2, p.read(site + 2, 2), 'a write')
    p.owner = 'splash'
    with pytest.raises(SystemExit, match=f'splash \\(its hook\\) and emoji \\(a write\\) both patch {site + 2:#x}'):
        p.own_entry(site, data, 'its hook')


@pytest.mark.firmware
def test_owned_hook_guard_rails_on_the_led_send(stock):
    p = stock_patch(stock)
    p.owner = 'bpm'
    with pytest.raises(SystemExit, match='the start of the function at 0x28d98f74 is not at its stock address'):
        p.own_entry(LED_SEND, bytes.fromhex('10b5 234b'), 'the LED send')
    with pytest.raises(SystemExit, match='whole instructions'):
        p.own_entry(LED_SEND, LED_STOCK[:2], 'the LED send')
    with pytest.raises(SystemExit, match='whole instructions'):
        p.own_entry(RENDER_FN, RENDER_STOCK[:4], 'the text renderer')
    hook = p.own_entry(LED_SEND, LED_STOCK, 'the LED send')
    with pytest.raises(SystemExit, match='the instruction at 0x28d98f76 reads the PC'):
        hook.stock
    with pytest.raises(SystemExit, match=r'bpm owns 0x28d98f74 \(the LED send\) but gave no handler'):
        p.finish_chains()
    hook.to(p.next())
    assert p.read(LED_SEND, 4) == pm.thumb_bw(LED_SEND, p.next())
    p.finish_chains()


@pytest.mark.firmware
@pytest.mark.parametrize('led', [0, 1, 2])
def test_an_owned_led_send_rewrites_r1_and_runs_the_moved_instructions(stock, m4emu, led):
    """A stand-in for BPM's handler: the moved push {lr} and literal load, r1 changed, then the rest of the LED send."""
    p = stock_patch(stock)
    p.owner = 'bpm'
    hook = p.own_entry(LED_SEND, LED_STOCK, 'the LED send')
    a = pm.Asm(p.next())
    a.h(0xb500, 0xf081, 0x017f)            # push {lr}; eor r1,r1,#0x7f
    a.movw_movt(3, LED_LIT)
    a.h(0x681b)                            # ldr r3,[r3]: the literal the moved ldr r3,[pc,#0x8c] loads
    a.bw(LED_SEND + 4)
    hook.to(p.add(a.bytes()))
    p.finish_chains()
    m4 = m4emu.M4(p.read(LED_SEND, 4), LED_SEND)
    m4.load(p.cave.va, p.cave.buf)
    m4.write(LED_LIT, p.read(LED_LIT, 4))
    m4.stub(LED_SEND + 4, code=b'\x00\xbd')          # pop {pc}: the rest of the send returns through the moved push
    assert m4.call(LED_SEND, led, 0x123456) == led
    (r0, r1, _, r3), = m4.calls(LED_SEND + 4)
    assert (r0, r1, r3) == (led, 0x123456 ^ 0x7f, LED_LIT_VALUE)


@pytest.mark.firmware
def test_an_owned_text_renderer_sees_its_9th_argument_rewritten(stock, m4emu):
    p = stock_patch(stock)
    p.owner = 'splash'
    hook = p.own_entry(RENDER_FN, RENDER_STOCK, 'the text renderer')
    a = pm.Asm(p.next())
    a.h(0xf04f, 0x0c01, 0xf8cd, 0xc010)    # mov.w r12,#1; str.w r12,[sp,#0x10]
    a.bw(hook.stock)
    hook.to(p.add(a.bytes()))
    p.finish_chains()
    m4 = m4emu.M4(p.read(RENDER_FN, 6), RENDER_FN)
    m4.load(p.cave.va, p.cave.buf)
    seen = []
    m4.stub(RENDER_FN + 6, lambda m: seen.append([m.u32(m.reg('sp') + 44 + 4 * i) for i in range(5)]), EPILOGUE)
    for i in range(5):
        m4.u32(m4emu.STACK_TOP + 4 * i, 0x50 + i)
    m4.call(RENDER_FN, 1, 2, 3, 4)
    assert seen == [[0x50, 0x51, 0x52, 0x53, 1]]
    assert m4.calls(RENDER_FN + 6) == [(1, 2, 3, 4)]


def without_splash():
    """The real features but splash, which is always on and owns the text renderer the demo features take."""
    return [m for m in features.load() if features.name(m) != 'splash']


@pytest.mark.firmware
def test_patch_menu_writes_entries_7_and_8_and_both_owned_sites(stock, tmp_path, monkeypatch):
    """Through patch_menu(), as build.py runs it: a demo feature, on by either of two variables, with a path input, repaints
    HXStomp_Splash in place, adds a glyph, owns the text renderer and the LED send, and chains the Home paint."""
    (tmp_path / 'pic.bin').write_bytes(b'x')
    seen, handlers = {}, {}

    def apply(p):
        e7, e8 = p.entry(7), p.entry(8)
        img = ims.image(e7.data, e8.data, b'HXStomp_Splash')
        e8.expect_md5(img.offset, img.length, SPLASH_MD5, 'HXStomp_Splash')
        e8.put(img.offset, struct.pack('<H', ims.pixel(255, 0, 0)) * (img.length // 2), 'the splash')
        p.add_glyph(FONT, 1, 3, b'\x01\x00' * 3 * 21, 'a glyph')
        hook = p.own_entry(RENDER_FN, RENDER_STOCK, 'the text renderer')
        a = pm.Asm(p.next())
        a.bw(hook.stock)
        handlers[RENDER_FN] = p.add(a.bytes())
        hook.to(handlers[RENDER_FN])
        handlers[LED_SEND] = p.add(b'\x70\x47')
        p.own_entry(LED_SEND, LED_STOCK, 'the LED send', handlers[LED_SEND])
        p.chain_ptr(HOME_PAINT_LIT, HOME_PAINT, after=p.add(b'\x70\x47'))
        seen.update(text=p.input('HX_DEMO_TEXT'), pic=p.input('HX_DEMO'))

    demo = fake('demo', FLAG=('HX_DEMO', 'HX_DEMO_TEXT'), INPUTS=(Input('HX_DEMO', path=True),), apply=apply)
    load = lambda n: pa.get_entry_swapped(stock, n)
    plain, _ = pm.menu_entries(load, env={})
    assert sorted(plain) == [0, 8] and plain[0] == pm.menu_entry0(load(0), env={}, others=load)[0]    # 8: the boot picture

    real = without_splash()
    monkeypatch.setattr(features, 'load', lambda: real + [demo])
    monkeypatch.setenv('HX_DEMO', 'pic.bin')
    monkeypatch.setenv('HX_DEMO_TEXT', 'HXS OS \U0001f3b8')
    log = []
    new = pm.patch_menu(stock, log.append, cwd=str(tmp_path))
    assert seen == {'text': 'HXS OS \U0001f3b8', 'pic': str(tmp_path / 'pic.bin')}
    assert log == ['[+] Entry 0: features demo; Entry 7; Entry 8']
    path = tmp_path / 'demo.l6ia'
    path.write_bytes(new)
    report = subprocess.run([sys.executable, os.path.join(ROOT, 'tools/l6ia_verify.py'), str(path)], capture_output=True, text=True)
    assert 'ALL OK' in report.stdout

    e0, e7, e8 = (pa.get_entry_swapped(new, n) for n in (0, 7, 8))
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

    read = reader(e0)
    assert read(RENDER_FN, 6) == pm.thumb_bw(RENDER_FN, handlers[RENDER_FN]) + b'\x00\xbf'
    assert read(LED_SEND, 4) == pm.thumb_bw(LED_SEND, handlers[LED_SEND])
    assert read(LED_SEND + 4, 4) == reader(stock_e0())(LED_SEND + 4, 4)
    stub = struct.unpack('<I', read(HOME_PAINT_LIT, 4))[0]
    assert stub != HOME_PAINT and stub & 1


CLANG = pytest.mark.skipif(not os.path.exists(m4asm.CLANG), reason='no clang')


def renderer_owner(order=100):
    def apply(p):
        hook = p.own_entry(RENDER_FN, RENDER_STOCK, 'the text renderer')
        a = pm.Asm(p.next())
        a.bw(hook.stock)
        hook.to(p.add(a.bytes()))
        p.chain_ptr(HOME_PAINT_LIT, HOME_PAINT, after=p.add(b'\x70\x47'))
    return fake('demo', ORDER=order, apply=apply)


@pytest.mark.firmware
@CLANG
def test_bpm_builds_beside_an_owned_text_renderer(stock):
    load = lambda n: pa.get_entry_swapped(stock, n)
    alone, _ = pm.menu_entries(load, env={'HX_BPM': '1'})
    both, on = pm.menu_entries(load, without_splash() + [renderer_owner()], {'HX_BPM': '1'})
    assert [features.name(m) for m in on] == ['bpm', 'demo'] and sorted(both) == [0, 7, 8]     # 7 and 8: its strip icons
    segs = [pa._parse_e0_segments(e[0]) for e in (alone, both)]
    read = lambda e, sg, va, n: e[0][pa._e0_vaddr_to_foff(sg, va, n):pa._e0_vaddr_to_foff(sg, va, n) + n]
    assert read(both, segs[1], LED_SEND, 4) == read(alone, segs[0], LED_SEND, 4) != LED_STOCK
    assert read(both, segs[1], RENDER_FN + 4, 2) == b'\x00\xbf'


@pytest.mark.firmware
@CLANG
@pytest.mark.parametrize('order, first, second', [(10, 'demo', 'bpm'), (100, 'bpm', 'demo')])
def test_owning_the_led_send_beside_bpm_fails_in_either_order(stock, order, first, second):
    def apply(p):
        p.own_entry(LED_SEND, LED_STOCK, 'the LED send', p.add(b'\x70\x47'))
    demo = fake('demo', ORDER=order, apply=apply)
    with pytest.raises(SystemExit, match=f'{second} \\(the LED send\\) and {first} \\(the LED send\\) both own 0x28d98f74'):
        mods = sorted(features.load() + [demo], key=lambda m: getattr(m, 'ORDER', 100))
        pm.menu_entries(lambda n: pa.get_entry_swapped(stock, n), mods, {'HX_BPM': '1'})


@pytest.mark.firmware
def test_menu_entry0_refuses_a_feature_that_needs_another_entry(stock):
    with pytest.raises(SystemExit, match='a feature needs Entry 8: build with menu_entries'):
        pm.menu_entry0(pa.get_entry_swapped(stock, 0), [fake('x', apply=lambda p: p.entry(8))], {}, {})
