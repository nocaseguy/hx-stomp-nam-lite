"""tools/features/tuner.py and src/m4/tuner.s: Tuner Activation and Lock Tuner Settings on a third page of the tuner's settings, run
in unicorn (the tap, the page's paint, knob turns and presses, Lock On everywhere else, and the hooks around them), and the firmware."""
import struct

import pytest

import features
import patch_menu as pm
import setting_ids
from features import tuner
from firmware import assert_virtual, built, built_e0, reader

MODS = features.load()
IDS = setting_ids.by_name()
ACTIVATE, LOCK = IDS['tuner.activate'], IDS['tuner.lock']
CODE, VIEW, EVENT, TRAMP = 0x28e60000, 0x28500000, 0x28510000, 0x28e70000
VIRT_SET = 0x28e80000        # the virtual settings engine's store, as customos_setting_set calls it
COLOURS = [fn for fn, _ in tuner.KNOB_COLOURS]
FLOAT_ONE = 0x3f800000


def cstr(m, va):
    data = m.read(va, 32)
    return data[:data.index(b'\0')]


class Page:
    """tuner.s in unicorn: settings {ID: value} behind GET_VALUE and the engine's store, the view at VIEW on page `page`."""

    def __init__(self, m4emu, page=tuner.PAGE):
        code, sym = m4emu.assemble('src/m4/tuner.s', MODS, IDS, VIRT_SET)
        self.at = {k: CODE + v for k, v in sym.items()}
        self.m = m = m4emu.M4(code, CODE)
        self.settings, self.written, self.steps, self.guard = {}, [], 0, 0
        m.stub(pm.GET_VALUE, self._get)
        m.stub(VIRT_SET, self._set)
        m.stub(tuner.STEPS, lambda m: m.reg('r0', self.steps))
        m.stub(tuner.GUARD, lambda m: m.reg('r0', self.guard))
        for fn in (tuner.REQUEST_TUNER, tuner.TAP_CORE):
            m.stub(fn)
        for fn in (tuner.PAINT, tuner.SHOW, tuner.VALUE_TEXT, tuner.POSITION, tuner.LABEL, *COLOURS):
            m.stub(fn)
        for fn in (tuner.PAINT_TBH, tuner.PAINT_END):
            m.stub(fn, code=struct.pack('<H', 0xbd10))                 # pop {r4,pc}: what via() pushed, as the paint's own epilogue
        for fn in (tuner.RESET_RET, *(site + 4 for site in tuner.RESET_SITES)):
            m.stub(fn, code=struct.pack('<H', 0xbd38))                 # pop {r3,r4,r5,pc}, as the event handler's epilogue
        m.stub(tuner.TURN_FN_CONT, code=struct.pack('<H', 0xbdf8))     # pop {r3-r7,pc}: the stock turn, after the moved prologue
        for fn in (tuner.NEXT_READ + 4, tuner.PREV_READ + 4, tuner.DOTS_READ + 4):
            m.stub(fn, code=struct.pack('<H', 0xbd10))                 # pop {r4,pc}
        m.stub(tuner.PAGE_STORE + 4, code=struct.pack('<H', 0xbd30))   # pop {r4,r5,pc}
        self.page(page)

    def _get(self, m):
        pid = m.reg('r0')
        if pid in self.settings:
            m.u32(m.reg('r1') + 4, self.settings[pid])
            m.reg('r0', 0)
        else:
            m.reg('r0', -1)

    def _set(self, m):
        pid, value = m.reg('r0'), m.reg('r1')
        assert pid in (ACTIVATE, LOCK), 'only virtual IDs reach the engine'
        self.written.append((pid, 2, value))
        self.settings[pid] = value
        m.reg('r0', 0)

    def page(self, n):
        self.m.u8(VIEW + 0x74, n)

    def turn(self, knob, steps):
        self.steps = steps
        self.m.write(EVENT, struct.pack('<4Bi', 0, knob, 0, 0, 1234))
        return self.m.call(self.at['tuner_turn'], EVENT, VIEW)

    def press(self, knob):
        return self.m.call(self.at['tuner_press'], VIEW, knob)

    def via(self, cave, *hws):
        """A function that pushes and sets r3/r4 (which m4emu.call keeps for itself) as hws say, then branches to cave, as the stock
        function it hooks does: cave leaves through a stub that pops."""
        a = pm.Asm(TRAMP)
        a.h(*hws)
        a.bw(cave)
        self.m.load(TRAMP, a.bytes())
        return TRAMP

    def painted(self, fn):
        return [regs[:2] for regs in self.m.calls(fn)]


def test_settings_stay_off_customos():
    assert tuner.MENU is False
    assert [s.label for s in tuner.SETTINGS] == [b'Activate', b'Lock']
    assert [(s.values, s.default) for s in tuner.SETTINGS] == [((b'Hold', b'Press'), 0), ((b'Off', b'On'), 0)]


@pytest.mark.parametrize('activate', [None, 0, 2])
def test_tap_in_hold_mode_runs_the_stock_tap_core(m4emu, activate):
    t = Page(m4emu)
    if activate is not None:
        t.settings[ACTIVATE] = activate
    t.m.call(t.at['tuner_tap'], 11, 22, 33, 44)
    assert [args[:4] for args in t.m.calls(tuner.TAP_CORE)] == [(11, 22, 33, 44)], 'its arguments as the tail call had them'
    assert t.m.calls(tuner.REQUEST_TUNER) == []


@pytest.mark.parametrize('guard, opened', [(0, True), (1, False)])
def test_tap_in_press_mode_asks_for_the_tuner_as_the_stock_hold_does(m4emu, guard, opened):
    t = Page(m4emu)
    t.settings[ACTIVATE], t.guard = 1, guard
    t.m.call(t.at['tuner_tap'], 11, 22, 33, 44)
    assert [args[0] for args in t.m.calls(tuner.GUARD)] == [5]
    assert len(t.m.calls(tuner.REQUEST_TUNER)) == opened and t.m.calls(tuner.TAP_CORE) == []


@pytest.mark.parametrize('activate, lock', [(0, 0), (1, 1), (1, 0)])
def test_paint_draws_both_knobs_and_hides_the_third(m4emu, activate, lock):
    t = Page(m4emu)
    t.settings.update({ACTIVATE: activate, LOCK: lock})
    t.m.call(t.at['tuner_paint'], VIEW)
    assert t.painted(tuner.SHOW) == [(0, 1), (1, 1), (2, 0)]
    texts = [(k, cstr(t.m, va)) for k, va in t.painted(tuner.VALUE_TEXT)]
    assert texts == [(0, tuner.SETTINGS[0].values[activate]), (1, tuner.SETTINGS[1].values[lock])]
    assert t.painted(tuner.POSITION) == [(0, FLOAT_ONE * activate), (1, FLOAT_ONE * lock)]
    assert [(k, cstr(t.m, va)) for k, va in t.painted(tuner.LABEL)] == [(k, s.label) for k, s in enumerate(tuner.SETTINGS)]
    for fn, colour in tuner.KNOB_COLOURS:
        assert t.painted(fn) == [(0, colour), (1, colour)]


def test_paint_draws_unset_and_stray_values_as_the_default(m4emu):
    t = Page(m4emu)
    t.settings[LOCK] = 7
    t.m.call(t.at['tuner_paint'], VIEW)
    assert [cstr(t.m, va) for _, va in t.painted(tuner.VALUE_TEXT)] == [b'Hold', b'Off']


@pytest.mark.parametrize('knob, pid', [(0, ACTIVATE), (1, LOCK)])
def test_turn_steps_the_setting_and_repaints(m4emu, knob, pid):
    t = Page(m4emu)
    t.settings.update({ACTIVATE: 0, LOCK: 0})
    assert t.turn(knob, 1) == 1
    assert t.written == [(pid, 2, 1)] and [args[0] for args in t.m.calls(tuner.PAINT)] == [VIEW]
    assert t.m.calls(tuner.STEPS)[0][0] == 1234
    assert t.turn(knob, -3) == 1
    assert t.written[-1] == (pid, 2, 0)


@pytest.mark.parametrize('value, steps', [(1, 1), (1, 5), (0, -1), (0, 0)])
def test_turn_past_an_end_changes_nothing(m4emu, value, steps):
    t = Page(m4emu)
    t.settings.update({ACTIVATE: value, LOCK: 0})
    assert t.turn(0, steps) == 1
    assert t.written == [] and t.m.calls(tuner.PAINT) == []


@pytest.mark.parametrize('knob', [2, 3])
def test_turn_of_the_empty_knob_changes_nothing(m4emu, knob):
    t = Page(m4emu)
    assert t.turn(knob, 1) == 1
    assert t.written == [] and t.m.calls(tuner.PAINT) == []
    assert len(t.m.calls(tuner.STEPS)) == (knob == 2), 'the stock counts detents of knobs 0..2 only'


def test_lock_on_does_not_lock_its_own_page(m4emu):
    t = Page(m4emu)
    t.settings.update({ACTIVATE: 0, LOCK: 1})
    assert t.turn(1, -1) == 1
    assert t.written == [(LOCK, 2, 0)]


@pytest.mark.parametrize('page', [0, 1, 2, 3])
@pytest.mark.parametrize('lock', [0, 1, None])
def test_other_pages_are_stock_unless_locked(m4emu, page, lock):
    t = Page(m4emu, page=page)
    if lock is not None:
        t.settings[LOCK] = lock
    assert t.turn(0, 1) == (lock == 1)
    assert t.press(0) == (lock == 1)
    assert t.written == [] and t.m.calls(tuner.STEPS) == []


@pytest.mark.parametrize('knob, pid', [(0, ACTIVATE), (1, LOCK)])
def test_press_resets_to_the_default(m4emu, knob, pid):
    t = Page(m4emu)
    t.settings.update({ACTIVATE: 1, LOCK: 1})
    assert t.press(knob) == 1
    assert t.written == [(pid, 2, 0)] and len(t.m.calls(tuner.PAINT)) == 1
    assert t.press(knob) == 1
    assert len(t.written) == 1 and len(t.m.calls(tuner.PAINT)) == 1, 'already the default'


def test_press_of_the_empty_knob_changes_nothing(m4emu):
    t = Page(m4emu)
    t.settings.update({ACTIVATE: 1, LOCK: 1})
    assert t.press(2) == 1
    assert t.written == []


@pytest.mark.parametrize('page, lock, stock', [(0, 0, True), (2, 1, False), (4, 0, False)])
def test_turn_hook_runs_the_stock_turn_only_when_the_handler_lets_it(m4emu, page, lock, stock):
    t = Page(m4emu, page=page)
    t.settings.update({ACTIVATE: 0, LOCK: lock})
    t.m.write(EVENT, struct.pack('<4Bi', 0, 0, 0, 0, 1))
    t.m.call(t.at['tuner_turn_hook'], EVENT, VIEW, 0x77)
    assert [args[:3] for args in t.m.calls(tuner.TURN_FN_CONT)] == ([(EVENT, VIEW, 0x77)] if stock else [])


@pytest.mark.parametrize('site, knob', tuner.RESET_SITES.items())
@pytest.mark.parametrize('page, lock, stock', [(1, 0, True), (1, 1, False), (4, 1, False)])
def test_reset_hooks_run_the_stock_reset_only_when_the_handler_lets_it(m4emu, site, knob, page, lock, stock):
    t = Page(m4emu, page=page)
    t.settings.update({ACTIVATE: 1, LOCK: lock})
    t.m.call(t.via(t.at[f'tuner_reset{knob}'], 0xb538, 0x460c), 0, VIEW)    # push {r3-r5,lr}; mov r4,r1: the view
    assert [args[1] for args in t.m.calls(site + 4)] == ([VIEW] if stock else [])
    assert len(t.m.calls(tuner.RESET_RET)) == (not stock)
    if page == tuner.PAGE:
        assert t.written == ([(ACTIVATE, 2, 0)] if knob == 0 else [(LOCK, 2, 0)] if knob == 1 else [])


ORDER = [0, 1, tuner.PAGE, 2, 3]       # the pages as paged and dotted: this one third, the string pages after it


@pytest.mark.parametrize('page', range(5))
@pytest.mark.parametrize('entry, cont', [('tuner_next_page', tuner.NEXT_READ + 4), ('tuner_prev_page', tuner.PREV_READ + 4)])
def test_paging_reads_the_pages_place_in_the_order(m4emu, page, entry, cont):
    t = Page(m4emu, page=page)
    t.m.call(t.via(t.at[entry], 0xb510), 0, VIEW)                       # push {r4,lr}
    assert [args[3] for args in t.m.calls(cont)] == [ORDER.index(page)]


@pytest.mark.parametrize('place', range(5))
def test_a_page_change_stores_the_page_at_its_new_place(m4emu, place):
    t = Page(m4emu)
    t.m.call(t.via(t.at['tuner_store_page'], 0xb530, 0x4603, 0x460c), place, VIEW)   # push {r4,r5,lr}; mov r3,r0; mov r4,r1
    assert [args[::3] for args in t.m.calls(tuner.PAGE_STORE + 4)] == [(VIEW, ORDER[place])]


@pytest.mark.parametrize('page', range(5))
def test_the_page_dots_mark_the_pages_place_in_the_order(m4emu, page):
    t = Page(m4emu, page=page)
    t.m.call(t.via(t.at['tuner_dots'], 0xb510, 0x460c), 0, VIEW)          # push {r4,lr}; mov r4,r1
    assert [args[0] for args in t.m.calls(tuner.DOTS_READ + 4)] == [ORDER.index(page)]


@pytest.mark.parametrize('page, to', [(0, tuner.PAINT_TBH), (3, tuner.PAINT_TBH), (4, None), (5, tuner.PAINT_END)])
def test_paint_switch_sends_page_4_to_its_paint(m4emu, page, to):
    t = Page(m4emu)
    t.settings.update({ACTIVATE: 0, LOCK: 0})
    t.m.call(t.via(t.at['tuner_switch'], 0xb510, 0x4603, 0x460c), page, VIEW)   # push {r4,lr}; mov r3,r0; mov r4,r1
    shown = t.painted(tuner.SHOW)
    if to is None:
        assert shown == [(0, 1), (1, 1), (2, 0)] and len(t.m.calls(tuner.PAINT_END)) == 1
    else:
        assert shown == [] and len(t.m.calls(to)) == 1 and len(t.m.calls(tuner.PAINT_END)) == (to == tuner.PAINT_END)


@pytest.mark.firmware
def test_firmware_has_five_tuner_pages_and_no_customos_section_of_its_own():
    e0 = built_e0({'HX_TUNER': '1'})
    read = reader(e0)
    assert read(pm.NAV_CMP, 2) == pm.NAV_CMP_STOCK and read(pm.TEXT_FN, 4) == pm.TEXT_FN_STOCK, 'no CustomOS section'
    for s in tuner.SETTINGS:
        assert_virtual(e0, tuner, s)
    for pid in (29, 104):
        assert read(pm.NAMES_LONG + pm.NAME_LEN * pid, pm.NAME_LEN) == bytes(pm.NAME_LEN), 'its old real IDs are left alone'
    assert read(tuner.NEXT_PAGE, 2) == b'\x03\x2b' and read(tuner.PAGE_DOTS, 2) == b'\x05\x20'
    assert all(read(site, 2) == b'\x04\x2b' for site in tuner.PAGE_CLAMPS)
    for site in (tuner.PAINT_SWITCH, tuner.TURN_FN, tuner.TAP_SITE, *tuner.RESET_SITES, tuner.NEXT_READ, tuner.PREV_READ,
                 tuner.PAGE_STORE, tuner.DOTS_READ):
        hw1, hw2 = struct.unpack('<2H', read(site, 4))
        assert hw1 >> 11 == 0x1e and hw2 & 0xd000 == 0x9000, f'no b.w at {site:#x}'


@pytest.mark.firmware
def test_without_its_flag_the_tuner_is_stock():
    read, on = built({})
    assert on == []
    assert read(pm.NAV_CMP, 2) == pm.NAV_CMP_STOCK and read(pm.TEXT_FN, 4) == pm.TEXT_FN_STOCK, 'no CustomOS section'
    assert read(tuner.NEXT_PAGE, 2) == tuner.NEXT_PAGE_STOCK and read(tuner.PAGE_DOTS, 2) == tuner.PAGE_DOTS_STOCK
    assert read(tuner.TAP_SITE, 4) == pm.thumb_bw(tuner.TAP_SITE, tuner.TAP_CORE) and read(tuner.TURN_FN, 4) == tuner.TURN_FN_STOCK


@pytest.mark.firmware
def test_customos_holds_only_the_other_features_settings():
    read, on = built({'HX_TUNER': '1', 'HX_BPM': '1'})
    assert on == ['tuner', 'bpm']
    assert read(pm.NAV_CMP, 2) == b'\x06\x2b'
    pages = struct.unpack('<I', read(pm.ARRAYS['pages'][2][0], 4))[0]
    assert struct.unpack('<I', read(pages + 4 * 6, 4))[0] == 1, "BPM's three settings: one page"
    assert read(pm.VIRTUAL_HOOKS['label'][0], 4) != pm.VIRTUAL_HOOKS['label'][1], 'the engine labels BPM\'s virtual settings'
