"""tools/features/fs_probe.py and src/m4/fs_probe.s: the footswitch probe run in unicorn (raw reports, posted events, the hex rows it
paints) and the firmware it builds."""
import os
import struct

import pytest

import features
import patch_amp as pa
import patch_menu as pm
import setting_ids
from features import fs_probe

MODS = features.load()
IDS = setting_ids.by_name()

CODE, TRAMP, OBJ, EVENT, FB = 0x28e60000, 0x28e70000, 0x28500000, 0x28600000, 0x28d1ce98
FILL, FLAG_GET, REDRAW = 0x100017e8, 0x28dd83c4, 0x28db8508
FONT = {
    '0': ('###', '#.#', '#.#', '#.#', '###'), '1': ('.#.', '##.', '.#.', '.#.', '###'),
    '2': ('###', '..#', '###', '#..', '###'), '3': ('###', '..#', '###', '..#', '###'),
    '4': ('#.#', '#.#', '###', '..#', '..#'), '5': ('###', '#..', '###', '..#', '###'),
    '6': ('###', '#..', '###', '#.#', '###'), '7': ('###', '..#', '..#', '..#', '..#'),
    '8': ('###', '#.#', '###', '#.#', '###'), '9': ('###', '#.#', '###', '..#', '###'),
    'A': ('.#.', '#.#', '###', '#.#', '#.#'), 'B': ('##.', '#.#', '##.', '#.#', '##.'),
    'C': ('###', '#..', '#..', '#..', '###'), 'D': ('##.', '#.#', '#.#', '#.#', '##.'),
    'E': ('###', '#..', '###', '#..', '###'), 'F': ('###', '#..', '###', '#..', '#..'),
}
GLYPH = {rows: ch for ch, rows in FONT.items()}
SCALE, PITCH, LEFT, TOP = 2, 12, 4, 64


class Probe:
    def __init__(self, m4emu):
        code, self.sym = m4emu.assemble('src/m4/fs_probe.s', MODS, IDS)
        self.m = m4emu.M4(code, CODE)
        self.flags, self.fills = {}, []
        self.m.stub(FLAG_GET, lambda m: m.reg('r0', self.flags.get(m.reg('r1'), 0)))
        self.m.stub(REDRAW)
        self.m.stub(FILL, self._fill)

    def _fill(self, m):
        h, colour, anchor = m.stack_args(3)
        self.fills.append((m.reg('r1'), m.reg('r2'), m.reg('r3'), h, colour & 0xffffff, anchor))

    def raw(self, k, value):
        """fs_raw as the ring loop's chain reaches it: r10 the report's value (call() resets r4-r11, so a trampoline sets it)."""
        at = TRAMP + 0x20 * value            # one per value: unicorn keeps code it translated, so rewriting one in place would not take
        tramp = bytes.fromhex('2de9 0044') + struct.pack('<2H', 0xf04f, 0x0a00 | value) + pm.bl(at + 8, CODE + self.sym['fs_raw'])
        self.m.load(at, tramp + bytes.fromhex('bde8 0084'))
        self.m.call(at, OBJ, k)

    def post(self, code, kind, source=1):
        self.m.write(EVENT, bytes([source, code, 0, 0]) + struct.pack('<I', kind))
        self.m.call(CODE + self.sym['fs_post'], EVENT)

    def rows(self):
        """The text of each row fs_paint draws, after checking it blacks out their area first."""
        self.fills.clear()
        self.m.call(CODE + self.sym['fs_paint'], FB)
        assert self.fills[0] == (0, 4, 272, 62, 0, 0)
        cells = {(x, y) for x, y, w, h, c, a in self.fills[1:] if (w, h, c) == (SCALE, SCALE, 0xffffff)}
        out = []
        for k in range(5):
            top, text = TOP - PITCH * k, ''
            for g in range(40):
                left = LEFT + 4 * SCALE * g
                rows = tuple(''.join('#' if (left + c * SCALE, top - (r + 1) * SCALE) in cells else '.' for c in range(3))
                             for r in range(5))
                text += GLYPH.get(rows, ' ' if '#' not in ''.join(rows) else '?')
            out.append(text.rstrip())
        return out


@pytest.fixture
def probe(m4emu):
    return Probe(m4emu)


def test_untouched_rows_show_zeros(probe):
    assert probe.rows() == [f'{k} 00 00 0000 0000 00 00 00 00 00' for k in range(5)]


def test_raw_reports_count_by_edge_and_keep_the_flag_and_last_value(probe):
    probe.flags[1] = 1
    for v in (0x7f, 0x7f, 0x7f, 0x00):
        probe.raw(1, v)
    probe.raw(2, 0x40)
    probe.raw(4, 0x3f)
    rows = probe.rows()
    assert rows[1] == '1 01 00 0003 0001 00 00 00 00 00'
    assert rows[2] == '2 00 40 0001 0000 00 00 00 00 00'
    assert rows[4] == '4 00 3F 0000 0001 00 00 00 00 00'
    assert probe.m.calls(FLAG_GET)[0][:2] == (OBJ, 1)
    assert all(regs[:2] == (0, 1) for regs in probe.m.calls(REDRAW)) and len(probe.m.calls(REDRAW)) == 6


def test_reports_for_other_codes_are_ignored(probe):
    probe.raw(5, 0x7f)
    probe.raw(0xf3, 0x7f)               # a touch code: 9 - 12 as the loop's uxtb leaves it
    assert probe.rows() == [f'{k} 00 00 0000 0000 00 00 00 00 00' for k in range(5)]
    assert not probe.m.calls(FLAG_GET) and not probe.m.calls(REDRAW)


def test_posted_events_count_by_type(probe):
    for kind in (1, 2, 3, 1, 5, 2, 4, 9):
        probe.post(14, kind)
    probe.post(16, 5)
    probe.post(11, 1)                   # a touch: not a footswitch
    probe.post(14, 1, source=2)         # not a key event
    rows = probe.rows()
    assert rows[2] == '2 00 00 0000 0000 02 02 01 01 02'
    assert rows[4] == '4 00 00 0000 0000 00 00 00 01 00'
    assert [rows[k] for k in (0, 1, 3)] == [f'{k} 00 00 0000 0000 00 00 00 00 00' for k in (0, 1, 3)]
    assert len(probe.m.calls(REDRAW)) == 9 and all(regs[:2] == (0, 1) for regs in probe.m.calls(REDRAW))


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


@pytest.mark.firmware
def test_build_hooks_the_ring_loop_the_post_and_the_home_paint():
    read, on = built({'HX_FS_PROBE': '1'})
    assert on == ['tuner', 'fs_probe']
    assert read(fs_probe.RING_FLAG_CALL, 4) != pm.bl(fs_probe.RING_FLAG_CALL, fs_probe.FLAG_GET)
    assert read(fs_probe.POST, 4) != fs_probe.POST_STOCK
    assert struct.unpack('<I', read(fs_probe.HOME_PAINT_LIT, 4))[0] != fs_probe.HOME_PAINT


@pytest.mark.firmware
def test_without_the_flag_the_hooks_stay_stock():
    read, on = built({})
    assert 'fs_probe' not in on
    assert read(fs_probe.RING_FLAG_CALL, 4) == pm.bl(fs_probe.RING_FLAG_CALL, fs_probe.FLAG_GET)
    assert read(fs_probe.POST, 4) == fs_probe.POST_STOCK
    assert struct.unpack('<I', read(fs_probe.HOME_PAINT_LIT, 4))[0] == fs_probe.HOME_PAINT


@pytest.mark.firmware
def test_builds_alongside_bpm():
    _, on = built({'HX_FS_PROBE': '1', 'HX_BPM': '1'})
    assert on == ['tuner', 'bpm', 'fs_probe']
