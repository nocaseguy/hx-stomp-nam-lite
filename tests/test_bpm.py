"""tools/features/bpm.py and src/m4/bpm.s: the BPM's settings, its hooks on the firmware, and its handlers run in tests/m4emu.py."""
import os
import struct
import types

import pytest

import features
import m4asm
import patch_amp as pa
import patch_menu as pm
import setting_ids
from features import bpm, tuner

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS = (5, 4, 2, 3, 0, 1)          # BPM Font's values as font numbers: 41 Lite, 35 Bold, 28 Bold, 28 Lite, 21 Bold, 21 Reg
COLOURS = (0xffffff, 0xb1b1b1, 0xff0000, 0xff7f00, 0xffff00, 0x00ff00, 0x00ffff, 0x0080ff, 0xb000ff)
CLANG = pytest.mark.skipif(not os.path.exists(m4asm.CLANG), reason='no Command Line Tools clang')


def test_settings_values_defaults_and_ids():
    s = {x.key: x for x in bpm.SETTINGS}
    assert s['font'].values == (b'41 Lite', b'35 Bold', b'28 Bold', b'28 Lite', b'21 Bold', b'21 Reg')
    assert s['color'].values == (b'White', b'Gray', b'Red', b'Orange', b'Yellow', b'Green', b'Cyan', b'Blue', b'Purple')
    assert s['dot'].values == (b'Left', b'Right', b'Both')
    assert all(x.default == 0 for x in s.values()), 'value 0 is the default: an ID never set reads 0'
    assert len(FONTS) == len(s['font'].values) and len(COLOURS) == len(s['color'].values)
    ids = setting_ids.by_name()
    assert (ids['bpm.font'], ids['bpm.color'], ids['bpm.dot']) == (128, 126, 102)
    assert bpm.FLAG == 'HX_BPM'


# --- the hooks, on the stock firmware ---

def stock_e0():
    stock = os.environ.get('HX_STOMP_HXF')
    if not stock:
        pytest.skip('HX_STOMP_HXF is not set')
    data, _ = pa.load_l6ia_from_any(stock)
    return pa.get_entry_swapped(data, 0)


def build(e0, extra=(), monkeypatch=None):
    """menu_entry0 with the BPM on (and extra features): (new Entry 0, the BPM's Module)."""
    seen = {}
    real = pm.Patch.module

    def module(self, path):
        m = real(self, path)
        seen[path] = m
        return m

    monkeypatch.setattr(pm.Patch, 'module', module)
    new, on = pm.menu_entry0(e0, features.load() + list(extra), {'HX_BPM': '1'})
    assert 'bpm' in [features.name(m) for m in on]
    return new, seen['src/m4/bpm.s']


def reader(e0):
    segs = pa._parse_e0_segments(e0)

    def read(va, n):
        o = pa._e0_vaddr_to_foff(segs, va, n)
        return bytes(e0[o:o + n])
    return read


def bl_target(b, at):
    return setting_ids.bl_targets(struct.unpack('<2H', b), at)[0]


def bw_target(b, at):
    h1, h2 = struct.unpack('<2H', b)
    return bl_target(struct.pack('<2H', h1, h2 | 0x5000), at)


@pytest.mark.firmware
@CLANG
def test_hooks_chain_the_handlers(monkeypatch):
    e0 = stock_e0()
    new, m = build(e0, monkeypatch=monkeypatch)
    read = reader(new)

    def is_stub(stub, original, before, after):
        want = pm.chain_cave(stub, original, list(before), list(after))
        assert read(stub, len(want)) == want

    def stub_of_bl(site, original, before=(), after=()):
        is_stub(bl_target(read(site, 4), site), original, before, after)

    stub_of_bl(bpm.HOME_CTOR_CALL, bpm.HOME_CTOR, after=[m['bpm_construct']])
    for site in bpm.STORE_WRITE_CALLS:
        stub_of_bl(site, bpm.STORE_WRITE, after=[m['bpm_written']])
    stub_of_bl(bpm.LED_TICK_CALL, bpm.LED_SLEEP, after=[m['bpm_tick']])
    for site in bpm.TAP_LED_READS:
        stub_of_bl(site, pm.GET_VALUE, after=[m['bpm_tapled']])
    is_stub(struct.unpack('<I', read(bpm.HOME_PAINT_LIT, 4))[0] - 1, bpm.HOME_PAINT & ~1, [m['bpm_before']], [m['bpm_after']])
    # the tap tempo core: its prologue moved to a trampoline, then a b.w back after it
    stub = bw_target(read(bpm.TAP_CORE, 4), bpm.TAP_CORE)
    tramp = stub - 8
    assert read(tramp, 8) == bpm.TAP_CORE_STOCK + pm.thumb_bw(tramp + 4, bpm.TAP_CORE + 4)
    is_stub(stub, tramp, [m['bpm_tap']], [])
    # the LED send: a plain b.w to the handler, which runs the send's first two instructions itself
    assert bw_target(read(bpm.LED_SEND, 4), bpm.LED_SEND) == m['bpm_ledsend']
    assert read(bpm.LED_SEND + 4, 4) == reader(e0)(bpm.LED_SEND + 4, 4)
    # the settings: labels and limits code (each range is not the stock 0..1)
    for key, pid, label, top in (('font', 128, b'BPM\nFont', 5), ('color', 126, b'BPM\nColor', 8), ('dot', 102, b'BPM\nDot Pos', 2)):
        assert read(pm.NAMES_LONG + pm.NAME_LEN * pid, len(label) + 1) == label + b'\0'
        tab, entry = pm.limits_entry(pid)
        snippet = tab + 2 * struct.unpack('<H', read(entry, 2))[0]
        assert read(snippet, 8) == struct.pack('<4H', 0x2302, 0x2200, 0x2100, 0x2400 | top)


@pytest.mark.firmware
@CLANG
@pytest.mark.parametrize('site, what', [(bpm.LED_SEND, 'the LED send'), (bpm.TAP_LED_READS[0] - 2, 'a read of Tap Tempo LED'),
                                        (bpm.TAP_CORE, 'the start of the function'), (bpm.LED_TICK_CALL, 'the call')])
def test_hooks_refuse_bytes_that_are_not_stock(monkeypatch, site, what):
    e0 = bytearray(stock_e0())
    o = pa._e0_vaddr_to_foff(pa._parse_e0_segments(e0), site, 2)
    e0[o:o + 2] = b'\xff\xff'
    with pytest.raises(SystemExit, match=what):
        build(bytes(e0), monkeypatch=monkeypatch)


@pytest.mark.firmware
@CLANG
def test_hooks_are_shared_with_other_features(monkeypatch):
    """Another feature on the Home paint, the Home constructor and the tap core builds; one writing the LED send does not."""
    handler = {}

    def other(p):
        h = handler['h'] = p.add(b'\x70\x47')
        p.chain_ptr(bpm.HOME_PAINT_LIT, bpm.HOME_PAINT, before=h, after=h)
        p.chain_bl(bpm.HOME_CTOR_CALL, bpm.HOME_CTOR, after=h)
        p.chain_entry(bpm.TAP_CORE, bpm.TAP_CORE_STOCK, before=h)

    def clash(p):
        p.put(bpm.LED_SEND, b'\0' * 4, 'its own LED hook')

    e0 = stock_e0()
    new, m = build(e0, [types.SimpleNamespace(__name__='features.other', ORDER=30, apply=other)], monkeypatch)
    read = reader(new)
    stub = struct.unpack('<I', read(bpm.HOME_PAINT_LIT, 4))[0] - 1
    want = pm.chain_cave(stub, bpm.HOME_PAINT & ~1, [m['bpm_before'], handler['h']], [m['bpm_after'], handler['h']])
    assert read(stub, len(want)) == want
    assert read(tuner.TAP_SITE, 4) != tuner.TAP_SITE_STOCK, 'the tuner still hooks its call of the tap core'
    with pytest.raises(SystemExit, match=r'clash \(its own LED hook\) and bpm \(the LED send\) both patch'):
        build(e0, [types.SimpleNamespace(__name__='features.clash', ORDER=30, apply=clash)], monkeypatch)


# --- the handlers, run in unicorn ---

MOD = 0x28e60000                     # where the module runs: its code is position independent, its firmware calls absolute
OUT = 0x28e50000                     # a GET_VALUE out buffer, as a caller's stack would hold
REDRAW, GET_VALUE, EXTERNAL, LED_SEND_REST = 0x28db8508, 0x28e1f844, 0x28d9685c, 0x28d98f78
SET_FONT, SET_TEXT_COLOUR, SET_TEXT_VISIBLE = 0x28e249e8, 0x28e24a28, 0x28e24bc8
SET_RECT_POS, SET_RECT_SIZE, SET_RECT_COLOUR, SET_RECT_VISIBLE = 0x28e24af0, 0x28e24b28, 0x28e24b98, 0x28e24b00
STUBS = (REDRAW, SET_FONT, SET_TEXT_COLOUR, SET_TEXT_VISIBLE, SET_RECT_POS, SET_RECT_SIZE, SET_RECT_COLOUR, SET_RECT_VISIBLE,
         0x28e249d0, 0x28e24a68, 0x28e24ac8, 0x28e24bc0, 0x28e24988, 0x28e24a18,
         0x28e24c90, 0x28e24c30, 0x28e24b40, 0x28e24b58, 0x28e24970, 0x28e24ae8)
POP_PC = struct.pack('<H', 0xbd00)
_code = {}


class Bpm:
    """bpm.s in tests/m4emu.py's M4, the firmware it calls stubbed: GET_VALUE answers from self.settings."""

    def __init__(self, m4emu, text, sym):
        self.sym, self.settings, self.external = sym, {}, 0
        self.m = m4emu.M4(text, MOD)
        for at in STUBS:
            self.m.stub(at)
        self.m.stub(GET_VALUE, self.get_value)
        self.m.stub(EXTERNAL, lambda m: m.reg('r0', self.external))
        self.m.stub(LED_SEND_REST, code=POP_PC)                 # the rest of the send, after the moved push {lr}

    def get_value(self, m):
        v = self.settings.get(m.reg('r0'))
        if v is None:
            m.reg('r0', -1)
        else:
            m.write(m.reg('r1'), struct.pack('<II', 3, v & 0xffffffff))
            m.reg('r0', 0)

    def at(self, sym):
        return MOD + self.sym[sym]

    def call(self, sym, *args):
        self.m.log.clear()
        return self.m.call(self.at(sym), *args)

    def data(self, off, n=1):
        return self.m.read(self.at('bpm_data') + off, n)

    def set_data(self, off, b):
        self.m.write(self.at('bpm_data') + off, b)

    def text_now(self):
        return self.m.read(self.at('bpm_text'), 16).split(b'\0')[0]

    def called(self, at):
        return self.m.calls(at)


@pytest.fixture
def m4(m4emu):
    if 'bpm' not in _code:
        _code['bpm'] = m4emu.assemble('src/m4/bpm.s', features.load(), setting_ids.by_name())
    return Bpm(m4emu, *_code['bpm'])


def bits(f):
    return struct.unpack('<I', struct.pack('<f', f))[0]


@pytest.mark.parametrize('select, bpm_id', [(0, 16), (1, 16), (2, 15)])
def test_format_reads_the_tempo_select_picks(m4, select, bpm_id):
    m4.settings = {14: select, bpm_id: bits(120.0), 31 - bpm_id: bits(99.0)}
    m4.call('bpm_format', 5)
    assert m4.text_now() == b'120'


@pytest.mark.parametrize('tempo, text', [(40.0, b'40'), (240.0, b'240'), (120.0, b'120'), (119.5, b'120'), (119.4, b'119'),
                                         (99.6, b'100'), (239.96, b'240'), (60.0, b'60')])
def test_format_rounds_to_a_whole_bpm(m4, tempo, text):
    m4.settings = {14: 2, 15: bits(tempo)}
    for font in FONTS:
        m4.call('bpm_format', font)
        assert m4.text_now() == text


def test_format_marks_external_clock_where_the_font_has_an_x(m4):
    m4.settings, m4.external = {14: 2, 15: bits(120.0)}, 1
    for font in FONTS:
        m4.call('bpm_format', font)
        assert m4.text_now() == (b'120' if font in (0, 4) else b'120 X')


@pytest.mark.parametrize('stored', [None, 0, bits(0.5), 0xffffffff])
def test_format_without_a_tempo(m4, stored):
    m4.settings = {14: 2} if stored is None else {14: 2, 15: stored}
    m4.call('bpm_format', 5)
    assert m4.text_now() == b'--'
    m4.call('bpm_format', 4)
    assert m4.text_now() == b'', 'the digit-only fonts have no dash'


def painted(m4, boot_done=True):
    m4.set_data(0, struct.pack('<I', 1))
    if boot_done:
        m4.set_data(8, struct.pack('<I', 1500))


def fs_functions(m4, functions):
    m4.m.write(0x28128a74, b''.join(bytes([f, 0]) for f in functions))


def rings(m4, lit):
    m4.m.write(m4.at('bpm_rings'), bytes(lit))


@pytest.mark.parametrize('tap', [0, 1, 2])
def test_tick_follows_the_tap_footswitchs_ring(m4, tap):
    painted(m4)
    fs_functions(m4, [1 if k == tap else 7 for k in range(3)])
    for lit in (1, 1, 0, 0, 1):
        rings(m4, [1 - lit if k != tap else lit for k in range(3)])
        before = m4.data(4)[0]
        m4.call('bpm_tick')
        assert m4.data(4)[0] == lit
        assert len(m4.called(REDRAW)) == (lit != before), 'a repaint for each turn of the ring, and none otherwise'


def test_tick_clears_a_taps_red_at_the_rings_next_turn(m4):
    painted(m4)
    fs_functions(m4, [7, 1, 7])
    m4.call('bpm_tap')
    assert list(m4.data(4, 2)) == [1, 1] and len(m4.called(REDRAW)) == 1
    rings(m4, [0, 1, 0])
    m4.call('bpm_tick')
    assert list(m4.data(4, 2)) == [1, 1], 'the ring is lit as the dot: no turn yet'
    rings(m4, [0, 0, 0])
    m4.call('bpm_tick')
    assert list(m4.data(4, 2)) == [0, 0]


def test_tick_without_a_tap_footswitch_leaves_the_dot(m4):
    painted(m4)
    fs_functions(m4, [7, 7, 7])
    rings(m4, [1, 1, 1])
    m4.call('bpm_tick')
    assert m4.data(4)[0] == 0 and not m4.called(REDRAW)


def test_nothing_repaints_before_the_home_view_has_painted(m4):
    fs_functions(m4, [1, 7, 7])
    rings(m4, [1, 0, 0])
    m4.call('bpm_tick')
    m4.call('bpm_tap')
    m4.call('bpm_written', 15)
    assert not m4.called(REDRAW) and m4.data(8, 4) == b'\0\0\0\0'


def test_tick_repaints_every_20_ms_for_the_first_1500_ms(m4):
    painted(m4, boot_done=False)
    fs_functions(m4, [7, 7, 7])
    times = []
    for ms in range(1, 1601):
        m4.call('bpm_tick')
        if m4.called(REDRAW):
            times.append(ms)
    assert times == list(range(20, 1501, 20))


@pytest.mark.parametrize('pid, repaints', [(13, 0), (14, 1), (15, 1), (16, 1), (17, 0), (126, 0)])
def test_written_repaints_for_the_tempo_settings(m4, pid, repaints):
    painted(m4)
    m4.call('bpm_written', pid, 0, 3)
    assert len(m4.called(REDRAW)) == repaints


def test_tapled_keeps_the_real_value_and_returns_on(m4):
    for real in (0, 1):
        m4.m.write(OUT, struct.pack('<II', 1, real))
        m4.call('bpm_tapled', bpm.TAP_LED_ID, OUT)
        assert m4.data(6)[0] == real
        assert struct.unpack('<II', m4.m.read(OUT, 8)) == (1, 1)


@pytest.mark.parametrize('tap_led_on', [0, 1])
def test_ledsend_notes_rings_and_darkens_the_tap_ring_when_its_led_is_off(m4, tap_led_on):
    fs_functions(m4, [7, 1, 7])
    m4.set_data(6, [tap_led_on])
    for led, colour in ((0, 0x00ff0000), (1, 0xab0000ff), (2, 0x000000), (1, 0x77000000)):
        m4.call('bpm_ledsend', led, colour)
        rest = m4.called(LED_SEND_REST)
        assert len(rest) == 1
        r0, r1, _, r3 = rest[0]
        lit = int(colour & 0xffffff != 0)
        assert m4.m.read(m4.at('bpm_rings') + led, 1)[0] == lit, 'the top byte is not part of the colour'
        assert (r0, r3) == (led, bpm.LED_SEND_LIT_VALUE)
        darkened = led == 1 and lit and not tap_led_on
        assert r1 == (0 if darkened else colour)


def test_ledsend_passes_leds_that_are_not_rings(m4):
    m4.call('bpm_ledsend', 3, 0xffffff)
    assert m4.called(LED_SEND_REST)[0][:2] == (3, 0xffffff)


def before(m4, font=None, colour=None, dot=None, lit=0, tapped=0):
    ids = setting_ids.by_name()
    m4.settings = {14: 2, 15: bits(128.0)}
    for key, v in (('font', font), ('color', colour), ('dot', dot)):
        if v is not None:
            m4.settings[ids[f'bpm.{key}']] = v
    m4.set_data(4, [lit, tapped])
    m4.call('bpm_before', 0x20000000, 0x2812a05c)


@pytest.mark.parametrize('value', range(6))
def test_before_sets_the_font_bpm_font_says(m4, value):
    before(m4, font=value)
    assert [r[1] for r in m4.called(SET_FONT)] == [FONTS[value]]


@pytest.mark.parametrize('value', [None, 6, 255])
def test_before_takes_the_default_font_when_unset_or_out_of_range(m4, value):
    before(m4, font=value)
    assert [r[1] for r in m4.called(SET_FONT)] == [FONTS[0]]


@pytest.mark.parametrize('value', [*range(9), None, 9])
def test_before_sets_the_colour_bpm_color_says(m4, value):
    before(m4, colour=value)
    assert [r[1] for r in m4.called(SET_TEXT_COLOUR)] == [COLOURS[value if value in range(9) else 0]]


@pytest.mark.parametrize('value, xs', [(0, range(69, 99)), (1, range(221, 251)), (2, [*range(69, 99), *range(221, 251)]),
                                       (None, range(69, 99)), (3, range(69, 99))])
def test_before_shows_the_dots_bpm_dot_pos_says(m4, value, xs):
    before(m4, dot=value)
    shown = [r[0] for r in m4.called(SET_RECT_VISIBLE) if r[1] == 1]
    assert len(m4.called(SET_RECT_VISIBLE)) == 18 and len(shown) == len(xs) // 30 * 9
    cols = set()
    for (_, x, y, _), (_, cw, ch, _) in zip(m4.called(SET_RECT_POS), m4.called(SET_RECT_SIZE)):
        cols |= set(range(x, x + cw))
        assert 237 - 15 <= y <= 237 and y - ch >= 237 - 30, 'within the 30 px dot below the top edge'
    assert cols == set(xs)


@pytest.mark.parametrize('lit, tapped, expect', [(0, 0, 0x404040), (1, 0, COLOURS[3]), (1, 1, 0xff0000), (0, 1, 0x404040)])
def test_before_lights_the_dot(m4, lit, tapped, expect):
    before(m4, colour=3, lit=lit, tapped=tapped)
    assert {r[1] for r in m4.called(SET_RECT_COLOUR)} == {expect}
