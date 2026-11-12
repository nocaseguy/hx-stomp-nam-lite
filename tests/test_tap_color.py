"""tools/features/tap_color.py and src/m4/tap_color.s: the handlers in unicorn (the ring's colour, the label lines and icon, the Home
paint's recolouring after a change), the palette against the stock code it comes from, and the firmware it builds (Displays' page,
the virtual setting, the hooks)."""
import struct

import pytest

import features
import patch_menu as pm
import setting_ids
import image_store
from features import tap_color as tc
from firmware import assert_virtual, branch_target, built, built_e0, reader, stock_e0, stock_entry

MODS = features.load()
IDS = setting_ids.by_name()
SETTING = tc.SETTINGS[0]
MOD = 0x28e60000
GET_VALUE, CLOCK = 0x28e1f844, 0x28da6458
RAINBOW, RANDOM = 10, 11
RAINBOW_STEPS = tc.rainbow()
HOME = 0x2812a0c8
FS_FUNCTIONS = 0x28128a74
COLOURS = ('Red', 'DarkOrange', 'LightOrange', 'Yellow', 'Green', 'Turquoise', 'Blue', 'Violet', 'Pink', 'White')
STOCK_LED_INDEX = (2, 3, 4, 5, 6, 7, 8, 9, 10, 1)   # each value's colour in the stock LED palette 0x28dd8030
LED_PALETTE, ICON_OF = (0x28dd8030, 0x28dd8110), (0x28dc6e9c, 0x28dc6fe0)    # stock code, start and end
_code = {}


class Tap:
    """tap_color.s in tests/m4emu.py's M4: GET_VALUE answers self.value (None: unset), the setters and the LED colour logged."""

    def __init__(self, m4emu):
        if 'tap' not in _code:
            _code['tap'] = m4emu.assemble('src/m4/tap_color.s', MODS, IDS, inc={'rainbow.inc': tc.rainbow_inc()})
        code, self.sym = _code['tap']
        self.m = m4emu.M4(code, MOD)
        self.value, self.now = None, 0x12345678
        self.m.stub(GET_VALUE, self.get_value)
        self.m.stub(CLOCK, lambda m: m.reg('r0', self.now))
        for fn in (tc.LED_COLOUR, tc.SET_COLOR, tc.SET_IMAGE):
            self.m.stub(fn)
        self.functions((2, 2, 2))

    def get_value(self, m):
        assert m.reg('r0') == IDS['tap_color.color']
        if self.value is None:
            m.reg('r0', -1)
        else:
            m.write(m.reg('r1'), struct.pack('<II', 0, self.value))
            m.reg('r0', 0)

    def functions(self, fns):
        for k, f in enumerate(fns + (2, 2)):
            self.m.write(FS_FUNCTIONS + 2 * k, bytes([f, 0]))

    def call(self, sym, *args):
        self.m.log.clear()
        self.m.call(MOD + self.sym[sym], *args)
        return [(fn, regs[:2]) for fn, regs in self.m.log if fn not in (GET_VALUE, CLOCK)]

    def shown(self):
        return self.m.u32(MOD + self.sym['tap_now'])


@pytest.fixture
def tap(m4emu):
    return Tap(m4emu)


def test_feature_settings():
    assert tc.FLAG == 'HX_TAP_COLOR' and tc.MENU == 'Displays'
    assert SETTING.label == b'Color\nTap LED' and SETTING.default == 0 and SETTING.max == RANDOM and SETTING.values[RAINBOW:] == (b'Rainbow', b'Random')
    assert all(len(v) <= 8 for v in SETTING.values)
    assert pm.STOCK_CATEGORIES['Displays'] == (5, 0x28e3b540)


@pytest.mark.parametrize('value', range(10))
def test_each_value_colours_the_ring_the_label_and_the_icon(tap, value):
    tap.value = value
    assert tap.call('tap_led', 2, 0x0300ff) == [(tc.LED_COLOUR, (2, tap_word('tap_leds', value)))]
    assert tap.call('tap_text', 0x2812a12c, 0xff0000) == [(tc.SET_COLOR, (0x2812a12c, tap_word('tap_texts', value)))]
    assert tap.call('tap_icon', 0x2812a4bc, 0x78) == [(tc.SET_IMAGE, (0x2812a4bc, tap_word('tap_icons', value)))]


def tap_word(table, value):
    return {'tap_leds': LEDS, 'tap_texts': TEXTS, 'tap_icons': ICONS}[table][value]


LEDS = (0x0300ff, 0x002dff, 0x00afd0, 0x00ff84, 0x00ff06, 0x80ff00, 0xff3200, 0xff0032, 0x2800ff, 0xceff6b)
TEXTS = (0xff0000, 0xff5a18, 0xf5911e, 0xead82f, 0x43ff40, 0x3cceb5, 0x0097e4, 0xb049db, 0xf12f91, 0xb1b1b1, 0xb1b1b1, 0xb1b1b1)   # Rainbow, Random: White
ICONS = (0x78, 0x1ca, 0x90, 0x83, 0x1b6, 0x21e, 0x234, 0x110, 0x127, 0x115, 0x115, 0x115)


@pytest.mark.parametrize('value', (None, 12, 15))
def test_unset_or_out_of_range_is_stock_red(tap, value):
    tap.value = value
    assert tap.call('tap_led', 2, 0) == [(tc.LED_COLOUR, (2, 0x0300ff))]
    assert tap.call('tap_text', 1, 0) == [(tc.SET_COLOR, (1, 0xff0000))]
    assert tap.call('tap_icon', 1, 0) == [(tc.SET_IMAGE, (1, 0x78))]


def label(k):
    return [(tc.SET_COLOR, (HOME + 0x64 + 0x30 * k, None)), (tc.SET_COLOR, (HOME + 0xf4 + 0x30 * k, None)),
            (tc.SET_IMAGE, (HOME + 0x3f4 + 0x24 * k, None))]


def recoloured(calls):
    return [(fn, (regs[0], None)) for fn, regs in calls]


def test_home_paint_recolours_the_tap_label_once_per_change(tap):
    tap.functions((2, 1, 2))
    tap.value = 6
    calls = tap.call('tap_paint', 0x28d1ce98, HOME)
    assert recoloured(calls) == label(1)
    assert [regs[1] for _, regs in calls] == [TEXTS[6], TEXTS[6], ICONS[6]]
    assert tap.call('tap_paint', 0x28d1ce98, HOME) == [], 'the same setting: nothing to do'
    tap.value = 3
    calls = tap.call('tap_paint', 0x28d1ce98, HOME)
    assert [regs[1] for _, regs in calls] == [TEXTS[3], TEXTS[3], ICONS[3]]


def test_home_paint_recolours_every_tap_footswitch_and_none_without_one(tap):
    tap.functions((1, 2, 1))
    tap.value = 0
    assert recoloured(tap.call('tap_paint', 0, HOME)) == label(0) + label(2)
    tap.functions((14, 14, 14))     # Snapshot mode
    tap.value = 1
    assert tap.call('tap_paint', 0, HOME) == []


def test_module_tables_are_the_palette(tap):
    words = lambda name, n: struct.unpack(f'<{n}I', tap.m.read(MOD + tap.sym[name], 4 * n))
    assert (words('tap_leds', 10), words('tap_texts', 12), words('tap_icons', 12)) == (LEDS, TEXTS, ICONS)


@pytest.mark.parametrize('value', range(10))
def test_the_shown_colour_is_the_labels_after_a_paint_and_a_beat(tap, value):
    tap.value = value
    tap.call('tap_paint', 0, HOME)
    assert tap.shown() == TEXTS[value]
    tap.m.u32(MOD + tap.sym['tap_now'], 0)
    tap.call('tap_led', 2, 0)
    assert tap.shown() == TEXTS[value]


def test_random_lights_the_ring_a_new_palette_colour_each_beat(tap):
    tap.value = RANDOM
    leds = [tap.call('tap_led', 2, 0x0300ff)[0][1] for _ in range(300)]
    assert all(led == 2 for led, _ in leds)
    colours = [c for _, c in leds]
    assert set(colours) == set(LEDS), 'every colour comes up'
    assert all(a != b for a, b in zip(colours, colours[1:])), 'never the same twice running'
    assert max(colours.count(c) for c in LEDS) < 3 * min(colours.count(c) for c in LEDS)
    assert tap.shown() == TEXTS[LEDS.index(colours[-1])], 'BPM Tempo follows the ring'


def test_random_seeds_from_the_clock_once(tap):
    tap.value = RANDOM
    tap.now = 0
    tap.call('tap_led', 2, 0)
    assert tap.m.u32(MOD + tap.sym['tap_seed']) != 0, 'a zero clock still seeds'
    tap.m.log.clear()
    tap.call('tap_led', 2, 0)
    assert not tap.m.calls(CLOCK)


@pytest.mark.parametrize('value', (RAINBOW, RANDOM))
def test_rainbow_and_random_leave_the_label_white_and_the_paint_leaves_the_ring_colour(tap, value):
    tap.functions((1, 2, 2))
    tap.value = value
    assert tap.call('tap_text', 1, 0) == [(tc.SET_COLOR, (1, 0xb1b1b1))]
    assert tap.call('tap_icon', 1, 0) == [(tc.SET_IMAGE, (1, 0x115))]
    tap.call('tap_led', 2, 0)
    ring = tap.shown()
    assert [regs[1] for _, regs in tap.call('tap_paint', 0, HOME)] == [0xb1b1b1, 0xb1b1b1, 0x115]
    assert tap.shown() == ring


def test_rainbow_moves_a_step_round_the_wheel_each_beat_and_round_again(tap):
    tap.value = RAINBOW
    for want in range(2 * len(RAINBOW_STEPS) + 3):
        led, text = RAINBOW_STEPS[want % len(RAINBOW_STEPS)]
        assert tap.call('tap_led', 2, 0) == [(tc.LED_COLOUR, (2, led))]
        assert tap.shown() == text, 'BPM Tempo follows the ring'


def test_rainbow_blends_red_dk_orange_yellow_green_blue_violet_in_small_steps():
    assert tc.RAINBOW_ANCHORS == tuple(COLOURS.index(c) for c in ('Red', 'DarkOrange', 'Yellow', 'Green', 'Blue', 'Violet'))
    assert len(RAINBOW_STEPS) == 6 * tc.SHADES >= 36, 'enough shades to look continuous'
    for i, k in enumerate(tc.RAINBOW_ANCHORS):
        assert RAINBOW_STEPS[i * tc.SHADES] == (LEDS[k], TEXTS[k]), 'each anchor is the palette colour itself'
    channels = lambda c: [c >> s & 0xff for s in (0, 8, 16)]
    for (a, _), (b, _) in zip(RAINBOW_STEPS, RAINBOW_STEPS[1:] + RAINBOW_STEPS[:1]):
        assert max(abs(x - y) for x, y in zip(channels(a), channels(b))) <= 0xff // tc.SHADES + 1, 'no jump between shades'
    blue, violet = (tc.RAINBOW_ANCHORS.index(COLOURS.index(c)) * tc.SHADES for c in ('Blue', 'Violet'))
    indigo = RAINBOW_STEPS[(blue + violet) // 2 + 1][0]
    assert channels(indigo)[2] == 0xff and 0x10 < channels(indigo)[0] < 0x32, 'indigo comes between Blue and Violet'


def test_the_feature_palette_is_the_modules():
    assert (tc.LEDS, tc.TEXTS) == (LEDS, TEXTS[:10])


def test_blend_rounds_each_channel():
    assert tc.blend(0x000000, 0xffffff, 1, 2) == 0x808080
    assert tc.blend(0x0300ff, 0x0300ff, 3, 7) == 0x0300ff
    assert [tc.blend(0x00, 0x07, k, 7) for k in range(8)] == list(range(8))


@pytest.mark.parametrize('value', (RAINBOW, RANDOM))
def test_the_ring_lit_outside_the_beat_keeps_rainbow_and_random_where_they_are(tap, value):
    tap.value = value
    beat = tap.call('tap_led', 2, 0)[0][1][1]
    shown = tap.shown()
    for _ in range(3):
        assert tap.call('tap_led_again', 2, 0) == [(tc.LED_COLOUR, (2, beat))]
    assert tap.shown() == shown
    if value == RAINBOW:
        assert tap.call('tap_led', 2, 0)[0][1][1] == RAINBOW_STEPS[1][0], 'the next beat takes the next colour'


@pytest.mark.parametrize('value', range(10))
def test_the_ring_lit_outside_the_beat_is_the_colour_picked(tap, value):
    tap.value = value
    assert tap.call('tap_led_again', 2, 0) == [(tc.LED_COLOUR, (2, LEDS[value]))]
    assert tap.shown() == TEXTS[value]


def stock_code(m4emu, span):
    read = reader(stock_e0())
    return m4emu.M4(read(span[0], span[1] - span[0]), span[0])


@pytest.mark.firmware
def test_leds_are_the_stock_lit_palette(m4emu):
    m = stock_code(m4emu, LED_PALETTE)
    assert tuple(m.call(LED_PALETTE[0], 0, i, 1) & 0xffffff for i in STOCK_LED_INDEX) == LEDS
    assert LEDS[0] == struct.unpack('<I', reader(stock_e0())(tc.TAP_RED, 4))[0] & 0xffffff, 'Red is the stock TAP ring'


@pytest.mark.firmware
def test_icons_are_the_switch_icons_stock_picks_for_the_label_colours(m4emu):
    m = stock_code(m4emu, ICON_OF)
    assert tuple(m.call(ICON_OF[0], c) for c in TEXTS) == ICONS
    names = image_store.names(stock_entry(7))
    assert [names[i] for i in ICONS[:10]] == [f'Icon_Switch{c}'.encode() for c in COLOURS]


@pytest.mark.firmware
def test_build_puts_tap_led_color_on_the_displays_page():
    e0 = stock_e0()
    new = built_e0({'HX_TAP_COLOR': '1'})
    read = reader(new)
    pages = struct.unpack('<I', read(pm.ARRAYS['pages'][1][0], 4))[0]
    assert struct.unpack('<6I', read(pages, 24)) == (3, 4, 2, 1, 4, 1), 'no new page: it fills the empty slot'
    for site in pm.SITES:
        cave = branch_target(pm.SITES[site][0], read(pm.SITES[site][0], 4))
        code = read(cave, 64)
        at = next(i for i in range(0, 60, 2) if code[i:i + 2] == bytes([5, 0x28 + pm.SITES[site][1]]))
        target = at + 2 + 4 + 2 * code[at + 2] + 2
        lo, hi = struct.unpack_from('<2I', code, target)
        imm = lambda w: ((w >> 16 & 0xff) | (w >> 28 & 7) << 8 | (w >> 10 & 1) << 11 | (w & 0xf) << 12)
        assert struct.unpack('<3H', read(imm(lo) | imm(hi) << 16, 6)) == (25, 26, IDS['tap_color.color']), site
    assert read(0x28e3b540, 6) == reader(e0)(0x28e3b540, 6), 'the stock table stays'
    assert_virtual(new, tc, SETTING)


@pytest.mark.firmware
def test_build_sends_the_tap_calls_and_the_home_paint_to_the_module(m4emu):
    code, sym = m4emu.assemble('src/m4/tap_color.s', MODS, IDS, inc={'rainbow.inc': tc.rainbow_inc()})
    read, on = built({'HX_TAP_COLOR': '1'})
    assert 'tap_color' in on
    module = branch_target(tc.LED_CALLS[0], read(tc.LED_CALLS[0], 4)) - sym['tap_led']
    assert read(module, len(code)) == code
    assert [branch_target(s, read(s, 4)) for s in tc.LED_CALLS] == [module + sym['tap_led'], module + sym['tap_led_again']]
    assert [branch_target(s, read(s, 4)) for s, _ in tc.TEXT_CALLS] == [module + sym['tap_text']] * 2
    assert branch_target(tc.ICON_CALL, read(tc.ICON_CALL, 4)) == module + sym['tap_icon']
    stub = struct.unpack('<I', read(tc.HOME_PAINT_LIT, 4))[0] & ~1
    assert branch_target(stub + 6, read(stub + 6, 4)) == module + sym['tap_paint'], 'push, ldm, then the before handler'


@pytest.mark.firmware
def test_without_the_flag_the_sites_stay_stock():
    read, on = built({})
    assert 'tap_color' not in on
    assert all(read(s, 4) == pm.bl(s, tc.LED_COLOUR) for s in tc.LED_CALLS)
    assert all(read(s, 4) == pm.bl(s, tc.SET_COLOR) for s, _ in tc.TEXT_CALLS)
    assert read(tc.ICON_CALL, 4) == pm.bl(tc.ICON_CALL, tc.SET_IMAGE)
    assert struct.unpack('<3H', read(0x28e3b540, 6)) == (25, 26, pm.EMPTY_SLOT)


@pytest.mark.firmware
def test_builds_alongside_every_other_feature():
    env = {f: '1' for m in MODS for f in features.flags(m)}
    _, on = built(env)
    assert {'bpm', 'breathing_line', 'long_press', 'more_snapshots', 'tap_color'} <= set(on)
