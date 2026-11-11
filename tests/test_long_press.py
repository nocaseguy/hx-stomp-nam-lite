"""tools/features/long_press.py and src/m4/long_press.s: the Hold settings, the event handler run in unicorn against a fake stock
handler (held-back presses, clicks, holds, the tuner and FS4/FS5, and where the stock behaviour stays), and the firmware it builds."""
import struct

import pytest

import features
import patch_menu as pm
import setting_ids
from features import long_press
from firmware import assert_virtual, branch_target, built, built_e0

MODS = features.load()
IDS = setting_ids.by_name()
HOLD_IDS = [IDS[f'long_press.fs{n}'] for n in (1, 2, 3, 4, 5)]
HOME_CTOR_CALL, HOME_CTOR = 0x28d96c44, 0x28dc91d0

CODE, OBJ, EVENT, LISTS = 0x28e60000, 0x28128a80, 0x28600000, 0x28128b4c
STOCK = 0x28700000                  # the stock handler, as the veneer hands it over
FUNCS, GUARD, REQUEST_TUNER, GET_LISTS, MOMENTARY = 0x28128a74, 0x28d96134, 0x28d96588, 0x28d96084, 0x28dd83c4
FS_MODE = 21
PRESS, RELEASE, CLICK, HOLD = 1, 2, 3, 5
TUNER, FS4, FS5 = 1, 2, 3
FS6 = 4                             # FS6..FS10: 4..8
GET_CONTROLLERS, CONTROLLERS, LOCK, UNLOCK = 0x28d9608c, 0x28480000, 0x28e24c00, 0x28e24bb0
TONE_OF, TONE, GET_BYPASS, CONTROL = 0x28d92a98, 0x28490000, 0x28e04514, 0x28dde408
ON, OFF = 0x3f800000, 0


class Handler:
    """lp_event in unicorn: what reaches the stock handler, and the tuner requests."""

    def __init__(self, m4emu):
        code, self.sym = m4emu.assemble('src/m4/long_press.s', MODS, IDS)
        self.m = m4emu.M4(code, CODE)
        self.settings = {FS_MODE: 0, **{pid: 0 for pid in HOLD_IDS}}     # Off unless a test sets an action
        self.momentary, self.guard, self.seen = set(), 0, []
        self.m.stub(pm.GET_VALUE, self._get_value)
        self.m.stub(STOCK, self._stock)
        self.m.stub(GUARD, lambda m: m.reg('r0', self.guard))
        self.m.stub(REQUEST_TUNER)
        self.m.stub(GET_LISTS, lambda m: m.reg('r0', LISTS))
        self.m.stub(MOMENTARY, lambda m: m.reg('r0', int(m.reg('r1') in self.momentary)))
        self.bypassed, self.order = {}, []
        self.m.stub(GET_CONTROLLERS, lambda m: m.reg('r0', CONTROLLERS))
        self.m.stub(LOCK, lambda m: self.order.append(('lock', m.reg('r0'))))
        self.m.stub(UNLOCK, lambda m: self.order.append(('unlock', m.reg('r0'))))
        self.m.stub(TONE_OF, lambda m: m.reg('r0', TONE))
        self.m.stub(GET_BYPASS, self._get_bypass)
        self.m.stub(CONTROL, lambda m: self.order.append(('control', m.reg('r0'), m.reg('r1'), m.reg('r2'), m.reg('r3'))))
        for i in range(64):
            self.node(i)
        for k in range(5):
            self.function(k, 2)

    def _get_value(self, m):
        pid, out = m.reg('r0'), m.reg('r1')
        if pid in self.settings:
            m.u8(out, 2)
            m.u32(out + 4, self.settings[pid])
            m.reg('r0', 0)
        else:
            m.reg('r0', -1)

    def _stock(self, m):
        ev = m.read(m.reg('r0'), 8)
        assert m.reg('r1') == OBJ
        self.seen.append((ev[0], ev[1], struct.unpack_from('<I', ev, 4)[0]))

    def _get_bypass(self, m):
        assert m.reg('r0') == TONE
        self.order.append(('get', m.reg('r1')))
        if m.reg('r1') in self.bypassed:
            m.u8(m.reg('r2'), self.bypassed[m.reg('r1')])
        m.reg('r0', 0)

    def node(self, i, kind=None, controller=8, cc=0, block=0):
        """Controller node i: free (kind None), or kind 2 a bypass assignment of block to controller (8 MIDI CC) at cc."""
        at = CONTROLLERS + 0xac + 0x48 * i
        self.m.u8(at + 0x44, 0x40 if kind is None else 0)
        self.m.u8(at + 0x28, kind or 0)
        self.m.u8(at + 0x10, controller)
        self.m.u32(at + 0x14, cc)
        self.m.u32(at + 0x2c, block)

    def hold(self, code):
        self.order.clear()
        self.run(*held(code))
        return [o for o in self.order if o[0] in ('get', 'control')]

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
    assert len(long_press.SETTINGS) == 5
    for n, s in zip((1, 2, 3, 4, 5), long_press.SETTINGS):
        assert (s.key, s.label, s.default) == (f'fs{n}', f'Function\nFS{n} Hold'.encode(), n + 3), 'FS1..FS5 Hold default to FS6..FS10'
        assert s.values == (b'Off', b'Tuner', b'FS4', b'FS5', b'FS6', b'FS7', b'FS8', b'FS9', b'FS10')
        assert all(len(v) <= 8 for v in s.values)
    assert HOLD_IDS == [0xd2, 0xd3, 0xd4, 0xd5, 0xd6], 'a unit keeps a setting\'s value by ID: never move it once a build has used it'
    assert long_press.FLAG == 'HX_LONG_PRESS' and long_press.VIRTUAL_CC == 20


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


@pytest.mark.parametrize('n, code', [(4, 15), (5, 16)])
def test_external_footswitches_4_and_5_have_hold_actions(h, n, code):
    h.hold_action(n, TUNER)
    assert h.run(*held(code)) == ([(code, RELEASE)], 1)
    assert h.run(*tap(code)) == ([(code, RELEASE), (code, PRESS), (code, RELEASE)], 0)


def test_external_footswitch_holds_reach_virtual_footswitches(h):
    h.hold_action(5, FS6 + 4)
    h.node(2, kind=2, cc=24, block=6)
    h.bypassed[6] = 0
    assert h.hold(16) == [('get', 6), ('control', CONTROLLERS, 8, 24, OFF)]


def test_other_keys_and_sources_pass(h):
    for n in (1, 2, 3, 4, 5):
        h.hold_action(n, TUNER)
    events = held(17) + held(9) + held(11) + held(0)
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


@pytest.mark.parametrize('bypassed, value', [(1, ON), (0, OFF)])
def test_virtual_footswitch_turns_its_blocks_to_the_opposite_of_the_first_ones_state(h, bypassed, value):
    h.hold_action(1, FS6)
    h.node(5, kind=2, cc=20, block=7)
    h.node(9, kind=2, cc=20, block=8)
    h.bypassed[7], h.bypassed[8] = bypassed, 1 - bypassed
    assert h.hold(12) == [('get', 7), ('control', CONTROLLERS, 8, 20, value)]
    assert h.seen == [(1, 12, RELEASE)]


@pytest.mark.parametrize('action, cc', [(FS6, 20), (FS6 + 1, 21), (FS6 + 4, 24)])
def test_each_virtual_footswitch_has_its_cc(h, action, cc):
    h.hold_action(2, action)
    h.node(3, kind=2, cc=cc, block=4)
    h.bypassed[4] = 1
    assert h.hold(13) == [('get', 4), ('control', CONTROLLERS, 8, cc, ON)]


def test_the_scan_skips_free_nodes_other_kinds_controllers_and_ccs(h):
    h.hold_action(1, FS6)
    h.node(0, kind=None, cc=20, block=1)
    h.node(1, kind=1, cc=20, block=2)
    h.node(2, kind=2, controller=3, cc=20, block=3)
    h.node(3, kind=2, cc=21, block=4)
    h.node(63, kind=2, cc=20, block=5)
    h.bypassed[5] = 0
    assert h.hold(12) == [('get', 5), ('control', CONTROLLERS, 8, 20, OFF)]


def test_the_scan_holds_only_the_controllers_lock_and_releases_it_before_the_calls(h):
    h.hold_action(1, FS6)
    h.node(4, kind=2, cc=20, block=9)
    h.bypassed[9] = 1
    h.hold(12)
    assert [o[0] for o in h.order] == ['lock', 'unlock', 'get', 'control']
    assert h.order[0][1] == h.order[1][1] == CONTROLLERS + 4


def test_with_no_block_to_read_the_virtual_footswitch_alternates(h):
    h.hold_action(1, FS6)
    assert h.hold(12) == [('control', CONTROLLERS, 8, 20, ON)]
    assert h.hold(12) == [('control', CONTROLLERS, 8, 20, OFF)]
    h.node(6, kind=2, cc=20, block=11)          # assigned, but the getter does not know the block: alternate on
    assert h.hold(12) == [('get', 11), ('control', CONTROLLERS, 8, 20, ON)]
    h.bypassed[11] = 1                           # a read state wins over the alternation
    assert h.hold(12) == [('get', 11), ('control', CONTROLLERS, 8, 20, ON)]


@pytest.mark.parametrize('n, code', [(1, 12), (3, 14), (5, 16)])
def test_a_stored_value_out_of_range_reads_the_default(h, n, code):
    h.hold_action(n, 100)               # a value another build stored
    assert h.hold(code) == [('control', CONTROLLERS, 8, 20 + n - 1, ON)]


def test_an_unset_hold_reads_its_default(h):
    """A virtual setting no build has stored reads its default, so FS1..FS5 Hold start on FS6..FS10 with no first-boot write."""
    h.settings.pop(HOLD_IDS[2], None)
    assert h.hold(14) == [('control', CONTROLLERS, 8, 22, ON)]


BUF = 0x28610000


def cc_text(h, cc):
    """The knob text after lp_cc_text runs on the stock "CC" + digits buffer, as at the three call sites."""
    h.m.write(BUF, b'CC' + str(cc).encode() + b'\0' * 7)
    h.m.call(CODE + h.sym['lp_cc_text'], cc, BUF + 2)
    return h.m.read(BUF, 9).split(b'\0')[0].decode()


@pytest.mark.parametrize('cc, text', [(20, 'FS6'), (21, 'FS7'), (22, 'FS8'), (23, 'FS9'), (24, 'FS10')])
def test_ccs_20_to_24_read_as_the_virtual_footswitches(h, cc, text):
    assert cc_text(h, cc) == text


@pytest.mark.parametrize('cc', [0, 4, 19, 25, 82, 127])
def test_other_ccs_keep_their_numbers(h, cc):
    assert cc_text(h, cc) == f'CC{cc}'


@pytest.mark.firmware
def test_build_owns_the_handler_and_hands_lp_event_the_stock_handler():
    read, on = built({'HX_LONG_PRESS': '1'})
    assert on == ['long_press', 'splash']
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
    assert read(HOME_CTOR_CALL, 4) == pm.bl(HOME_CTOR_CALL, HOME_CTOR), 'no boot hook: unset virtual settings read their defaults'
    assert read(long_press.MIDI_IN_FIRST, 2) == bytes([20, 0x22]), 'MIDI In: the first step up from Off is FS6\'s CC 20'
    for site in long_press.CC_TEXT_CALLS:
        assert read(site, 4) != pm.bl(site, long_press.ITOA), f'the CC text at {site:#x} is chained'


@pytest.mark.firmware
def test_build_serves_the_holds_as_virtual_settings():
    e0 = built_e0({'HX_LONG_PRESS': '1'})
    for s in long_press.SETTINGS:
        assert_virtual(e0, long_press, s)


@pytest.mark.firmware
def test_without_the_flag_the_handler_stays_stock():
    read, on = built({})
    assert 'long_press' not in on
    assert read(long_press.HANDLER, 4) == long_press.HANDLER_STOCK
    assert read(long_press.MIDI_IN_FIRST, 2) == long_press.MIDI_IN_FIRST_STOCK
    for site in long_press.CC_TEXT_CALLS:
        assert read(site, 4) == pm.bl(site, long_press.ITOA)


@pytest.mark.firmware
def test_builds_alongside_the_tuner_bpm_and_dsp_meter():
    _, on = built({'HX_LONG_PRESS': '1', 'HX_BPM': '1', 'HX_DSP_METER': '1', 'HX_TUNER': '1'})
    assert on == ['tuner', 'bpm', 'dsp_meter', 'long_press', 'splash']
