"""tools/features/long_press.py and src/m4/long_press.s: the Hold settings, the event handler run in unicorn against a fake stock
handler (held-back presses, clicks, holds, the tuner and FS4/FS5, and where the stock behaviour stays), and the firmware it builds."""
import os
import struct

import pytest

import features
import patch_amp as pa
import patch_menu as pm
import setting_ids
from features import long_press

MODS = features.load()
IDS = setting_ids.by_name()
HOLD_IDS = [IDS[f'long_press.fs{n}'] for n in (1, 2, 3)]

CODE, OBJ, EVENT, LISTS = 0x28e60000, 0x28128a80, 0x28600000, 0x28128b4c
STOCK = 0x28700000                  # the stock handler, as the veneer hands it over
FUNCS, GUARD, REQUEST_TUNER, GET_LISTS, MOMENTARY = 0x28128a74, 0x28d96134, 0x28d96588, 0x28d96084, 0x28dd83c4
SETTER_CTX, SETTER, CTX = 0x28e007ec, 0x28e1f8f4, 0x28400000
FS_MODE = 21
PRESS, RELEASE, CLICK, HOLD = 1, 2, 3, 5
TUNER, FS4, FS5 = 1, 2, 3


class Handler:
    """lp_event in unicorn: what reaches the stock handler, and the tuner requests."""

    def __init__(self, m4emu):
        code, self.sym = m4emu.assemble('src/m4/long_press.s', MODS, IDS)
        self.m = m4emu.M4(code, CODE)
        self.settings, self.types = {FS_MODE: 0}, {}
        self.momentary, self.guard, self.seen, self.written = set(), 0, [], []
        self.m.stub(pm.GET_VALUE, self._get_value)
        self.m.stub(STOCK, self._stock)
        self.m.stub(GUARD, lambda m: m.reg('r0', self.guard))
        self.m.stub(REQUEST_TUNER)
        self.m.stub(GET_LISTS, lambda m: m.reg('r0', LISTS))
        self.m.stub(MOMENTARY, lambda m: m.reg('r0', int(m.reg('r1') in self.momentary)))
        self.m.stub(SETTER_CTX, lambda m: m.reg('r0', CTX))
        self.m.stub(SETTER, self._set)
        for k in range(5):
            self.function(k, 2)

    def _get_value(self, m):
        pid, out = m.reg('r0'), m.reg('r1')
        if pid in self.settings:
            m.u8(out, self.types.get(pid, 2))
            m.u32(out + 4, self.settings[pid])
            m.reg('r0', 0)
        else:
            m.reg('r0', -1)

    def _stock(self, m):
        ev = m.read(m.reg('r0'), 8)
        assert m.reg('r1') == OBJ
        self.seen.append((ev[0], ev[1], struct.unpack_from('<I', ev, 4)[0]))

    def _set(self, m):
        rec = m.read(m.reg('r2'), 8)
        self.written.append((m.reg('r0'), m.reg('r1'), rec[0], struct.unpack_from('<I', rec, 4)[0], m.reg('r3')))

    def boot(self):
        self.written.clear()
        self.m.call(CODE + self.sym['lp_boot'], 0x2812a05c)
        return self.written

    def function(self, k, f):
        self.m.u8(FUNCS + 2 * k, f)

    def hold_action(self, n, action):
        self.settings[HOLD_IDS[n - 1]] = action

    def event(self, code, kind, source=1):
        self.m.write(EVENT, bytes([source, code, 0, 0]) + struct.pack('<I', kind))
        self.m.call(CODE + self.sym['lp_event'], EVENT, OBJ, STOCK | 1)

    def run(self, *events):
        """Each (code, type) through lp_event -> [(code, type)] the stock handler got, and the tuner requests."""
        self.seen.clear()
        self.m.log.clear()
        for code, kind in events:
            self.event(code, kind)
        assert all(src == 1 for src, _, _ in self.seen)
        return [(c, t) for _, c, t in self.seen], len(self.m.calls(REQUEST_TUNER))


def tap(code):
    return [(code, PRESS), (code, RELEASE), (code, CLICK)]


def held(code):
    return [(code, PRESS), (code, HOLD), (code, RELEASE)]


@pytest.fixture
def h(m4emu):
    return Handler(m4emu)


def test_hold_settings():
    for n, s in zip((1, 2, 3), long_press.SETTINGS):
        assert (s.key, s.label, s.values, s.default) == (f'fs{n}', f'FS{n}\nHold'.encode(), (b'Off', b'Tuner', b'FS4', b'FS5'), 0)
        assert all(len(v) <= 8 for v in s.values)
    assert HOLD_IDS == [63, 78, 132], 'a unit keeps a setting\'s value by ID: never move it once a build has used it'
    assert long_press.FLAG == 'HX_LONG_PRESS'


def test_with_no_hold_action_every_event_reaches_the_stock_handler_unchanged(h):
    events = tap(12) + held(13) + tap(14) + [(13, 4)]
    assert h.run(*events) == (events, 0)


def test_tap_with_a_hold_action_toggles_on_the_click(h):
    h.hold_action(1, TUNER)
    assert h.run((12, PRESS)) == ([], 0)
    assert h.run((12, RELEASE)) == ([(12, RELEASE)], 0)
    assert h.run((12, CLICK)) == ([(12, PRESS), (12, RELEASE)], 0)


def test_hold_opens_the_tuner_without_toggling(h):
    h.hold_action(2, TUNER)
    assert h.run(*held(13)) == ([(13, RELEASE)], 1)
    assert h.m.calls(GUARD)[0][0] == 5


def test_hold_does_not_open_the_tuner_when_the_guard_refuses(h):
    h.hold_action(3, TUNER)
    h.guard = 1
    assert h.run(*held(14)) == ([(14, RELEASE)], 0)


@pytest.mark.parametrize('action, code', [(FS4, 15), (FS5, 16)])
def test_hold_presses_fs4_or_fs5(h, action, code):
    h.hold_action(1, action)
    assert h.run(*held(12)) == ([(code, PRESS), (code, RELEASE), (12, RELEASE)], 0)


def test_each_footswitch_has_its_own_hold_action(h):
    h.hold_action(1, FS4)
    h.hold_action(3, FS5)
    assert h.run(*held(13)) == (held(13), 0)
    assert h.run(*held(14)) == ([(16, PRESS), (16, RELEASE), (14, RELEASE)], 0)
    assert h.run(*held(12)) == ([(15, PRESS), (15, RELEASE), (12, RELEASE)], 0)


@pytest.mark.parametrize('mode', [2, 3])
def test_preset_and_snapshot_modes_stay_stock(h, mode):
    h.hold_action(1, TUNER)
    h.settings[FS_MODE] = mode
    assert h.run(*held(12), *tap(12)) == (held(12) + tap(12), 0)


@pytest.mark.parametrize('function', [1, 5, 14])
def test_footswitches_that_are_not_stomps_stay_stock(h, function):
    h.hold_action(1, TUNER)
    h.function(0, function)
    assert h.run(*held(12)) == (held(12), 0)


def test_a_momentary_footswitch_stays_stock(h):
    h.hold_action(2, TUNER)
    h.momentary.add(1)
    assert h.run(*held(13)) == (held(13), 0)
    assert h.m.calls(GET_LISTS) and h.m.calls(MOMENTARY)[0][1] == 1


def test_other_keys_and_sources_pass(h):
    for n in (1, 2, 3):
        h.hold_action(n, TUNER)
    events = held(15) + held(16) + held(9) + held(11)
    assert h.run(*events) == (events, 0)
    h.seen.clear()
    h.event(12, PRESS, source=2)
    assert h.seen == [(2, 12, PRESS)]


def test_a_hold_whose_action_went_away_gives_the_press_back(h):
    h.hold_action(1, TUNER)
    assert h.run((12, PRESS)) == ([], 0)
    h.hold_action(1, 0)
    assert h.run((12, HOLD), (12, RELEASE)) == ([(12, PRESS), (12, RELEASE), (12, RELEASE)], 0)


def test_stray_clicks_and_holds_pass(h):
    h.hold_action(1, TUNER)
    assert h.run((12, CLICK), (12, HOLD)) == ([(12, CLICK), (12, HOLD)], 0)


def test_a_stored_value_out_of_range_reads_off(h):
    h.hold_action(1, 100)               # ID 63 holds its stock 100 on a unit that never set it
    assert h.run(*held(12)) == (held(12), 0)


def test_boot_makes_bool_hold_records_ints_and_keeps_their_value(h):
    for pid, (kind, value) in zip(HOLD_IDS, ((2, 3), (1, 1), (1, 0))):
        h.settings[pid], h.types[pid] = value, kind
    assert h.boot() == [(CTX, HOLD_IDS[1], 2, 1, 6), (CTX, HOLD_IDS[2], 2, 0, 6)]


def test_boot_clamps_a_value_out_of_range_and_skips_unset_ids(h):
    h.settings[HOLD_IDS[0]], h.types[HOLD_IDS[0]] = 100, 1
    assert h.boot() == [(CTX, HOLD_IDS[0], 2, 0, 6)]


def test_boot_leaves_int_records_alone(h):
    for pid in HOLD_IDS:
        h.settings[pid] = 5
    assert h.boot() == []


def built(env):
    stock = os.environ.get('HX_STOMP_HXF')
    if not stock:
        pytest.skip('HX_STOMP_HXF is not set')
    data, _ = pa.load_l6ia_from_any(stock)
    new, on = pm.menu_entry0(pa.get_entry_swapped(data, 0), env=env)
    segs = pa._parse_e0_segments(new)

    def read(va, n):
        o = pa._e0_vaddr_to_foff(segs, va, n)
        return new[o:o + n]

    return read, [features.name(m) for m in on]


def branch_target(at, hw):
    hw1, hw2 = struct.unpack('<2H', hw)
    s, j1, j2 = (hw1 >> 10) & 1, (hw2 >> 13) & 1, (hw2 >> 11) & 1
    off = (s << 24) | ((~(j1 ^ s) & 1) << 23) | ((~(j2 ^ s) & 1) << 22) | ((hw1 & 0x3ff) << 12) | ((hw2 & 0x7ff) << 1)
    return at + 4 + (off - (1 << 25) if s else off)


@pytest.mark.firmware
def test_build_owns_the_handler_and_hands_lp_event_the_stock_handler():
    read, on = built({'HX_LONG_PRESS': '1'})
    assert on == ['tuner', 'long_press']
    veneer = branch_target(long_press.HANDLER, read(long_press.HANDLER, 4))
    hw = struct.unpack('<4H', read(veneer, 8))
    imm = lambda a, b: ((a & 0xf) << 12) | (((a >> 10) & 1) << 11) | (((b >> 12) & 7) << 8) | (b & 0xff)
    assert (hw[0] & 0xfbf0, hw[2] & 0xfbf0, (hw[1] >> 8) & 0xf, (hw[3] >> 8) & 0xf) == (0xf240, 0xf2c0, 2, 2)
    stock = imm(hw[0], hw[1]) | imm(hw[2], hw[3]) << 16
    assert stock & 1
    assert read(stock & ~1, 4) == long_press.HANDLER_STOCK
    assert branch_target((stock & ~1) + 4, read((stock & ~1) + 4, 4)) == long_press.HANDLER + 4
    lp_event = branch_target(veneer + 8, read(veneer + 8, 4))
    assert read(lp_event, 2) == bytes.fromhex('2de9')    # push.w {r4-r8,lr}
    assert read(long_press.HOME_CTOR_CALL, 4) != pm.bl(long_press.HOME_CTOR_CALL, long_press.HOME_CTOR)


@pytest.mark.firmware
def test_build_sets_the_hold_labels():
    read, _ = built({'HX_LONG_PRESS': '1'})
    for n, pid in zip((1, 2, 3), HOLD_IDS):
        for tab in (pm.NAMES_LONG, pm.NAMES_SHORT):
            assert read(tab + pm.NAME_LEN * pid, 9) == f'FS{n}\nHold\0'.encode()


@pytest.mark.firmware
def test_without_the_flag_the_handler_stays_stock():
    read, on = built({})
    assert 'long_press' not in on
    assert read(long_press.HANDLER, 4) == long_press.HANDLER_STOCK
    assert read(long_press.HOME_CTOR_CALL, 4) == pm.bl(long_press.HOME_CTOR_CALL, long_press.HOME_CTOR)


@pytest.mark.firmware
def test_builds_alongside_bpm_and_dsp_meter():
    _, on = built({'HX_LONG_PRESS': '1', 'HX_BPM': '1', 'HX_DSP_METER': '1'})
    assert on == ['tuner', 'bpm', 'dsp_meter', 'long_press']
