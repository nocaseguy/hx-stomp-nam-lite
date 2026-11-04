"""tools/features/dsp_meter.py and src/m4/dsp_meter.s: the DSP Disp setting, the module run in unicorn against a fake DSP model and Edit
view (each block's per cent, the total in each format, rounding and the ends, placement, locks), and the firmware it builds."""
import os
import struct

import pytest

import features
import patch_amp as pa
import patch_menu as pm
import setting_ids
from features import dsp_meter

MODS = features.load()
IDS = setting_ids.by_name()
DISP = IDS['dsp_meter.disp']

# The fakes, at the addresses the module reads
DSP_PTR, SLOT_MODEL = 0x28449e78, 0x2812c590
DSP, NODES, BLOCKS, VIEW, CODE = 0x28500000, 0x28600000, 0x28700000, 0x28800000, 0x28e60000
FB = 0x28d1ce98
FILL, WIDGET_LOCK, WIDGET_UNLOCK = 0x100017e8, 0x28e24970, 0x28e24ae8
DSP_LOCK, DSP_UNLOCK = 0x28e07844, 0x28e0785c
CURSOR = 0x67                       # every empty slot's image, which the cursor for placing a block shows
FONT = {                            # what the glyphs must look like, independent of the module's encoding
    '0': ('###', '#.#', '#.#', '#.#', '###'), '1': ('.#.', '##.', '.#.', '.#.', '###'),
    '2': ('###', '..#', '###', '#..', '###'), '3': ('###', '..#', '###', '..#', '###'),
    '4': ('#.#', '#.#', '###', '..#', '..#'), '5': ('###', '#..', '###', '..#', '###'),
    '6': ('###', '#..', '###', '#.#', '###'), '7': ('###', '..#', '..#', '..#', '..#'),
    '8': ('###', '#.#', '###', '#.#', '###'), '9': ('###', '#.#', '###', '..#', '###'),
    '/': ('..#', '..#', '.#.', '#..', '#..'), '%': ('#.#', '..#', '.#.', '#..', '#.#'),
}
GLYPH = {tuple(rows): ch for ch, rows in FONT.items()}
WHITE, BLACK = 0xffffff, 0


def test_dsp_disp_setting():
    s, = dsp_meter.SETTINGS
    assert (s.key, s.label, s.values, s.default, s.max) == ('disp', b'DSP\nDisp', (b'Used/All', b'Free', b'Used%'), 0, 2)
    assert all(len(v) <= 8 and b'\n' not in v for v in s.values), 'a value shows 8 characters, on one line [verified on unit]'
    assert DISP == 101, 'a unit keeps a setting\'s value by ID: never move it once a build has used it'
    assert dsp_meter.FLAG == 'HX_DSP_METER'


class Meter:
    """The module in unicorn: blocks in slots, the DSP Disp setting, and what paint draws."""

    def __init__(self, m4emu):
        code, self.sym = m4emu.assemble('src/m4/dsp_meter.s', MODS, IDS)
        self.m = m4emu.M4(code, CODE)
        self.fills, self.events, self.setting = [], [], None
        self.m.stub(FILL, self._fill)
        for fn, name in ((WIDGET_LOCK, 'widget lock'), (WIDGET_UNLOCK, 'widget unlock'), (DSP_LOCK, 'dsp lock'),
                         (DSP_UNLOCK, 'dsp unlock')):
            self.m.stub(fn, lambda m, name=name: self.events.append(name))
        self.m.stub(pm.GET_VALUE, self._get_value)
        self.m.u32(DSP_PTR, DSP)
        self.m.u32(DSP + 0x4400, NODES)
        self.m.u32(DSP + 0x43fc, 0)
        for idx in range(16):
            self.m.u32(DSP + 0x14 + 0x54 * idx, 0xffffffff)     # no block
        for k in range(8):
            self.slot(k, None)

    def _fill(self, m):
        h, colour, anchor = m.stack_args(3)
        self.fills.append((m.reg('r1'), m.reg('r2'), m.reg('r3'), h, colour & 0xffffff, anchor & 0xff))
        self.events.append('fill')

    def _get_value(self, m):
        pid, out = m.reg('r0'), m.reg('r1')
        if pid == DISP and self.setting is not None:
            m.u32(out + 4, self.setting)
            m.reg('r0', 0)
        else:
            m.reg('r0', -1)

    def block(self, idx, cost, handle=None):
        """A block object with this cost behind DSP record idx (0..7 first row, 8..15 second)."""
        handle = idx if handle is None else handle
        obj = BLOCKS + 0x100 * idx
        self.m.u32(DSP + 0x14 + 0x54 * idx, handle)
        self.m.u32(NODES + 0x24 + 4 * handle, obj)
        self.m.u8(obj + 5, 1)
        self.m.u32(obj + 0x44, cost)

    def slot(self, k, image, w=24, h=24, second_row=False, x=None, y=0xb5):
        """Edit view slot k showing image (None: hidden), centre-anchored as the stock layout places them."""
        wd = VIEW + 0x4a4 + 0x24 * k
        self.m.u32(wd, image or 0)
        self.m.u32(wd + 0xc, 41 + 34 * k if x is None else x)
        self.m.u32(wd + 0x10, y)
        self.m.u32(wd + 0x14, w)
        self.m.u32(wd + 0x18, h)
        self.m.u8(wd + 0x1c, 4)
        self.m.u8(wd + 0x1d, image is not None)
        self.m.u8(SLOT_MODEL + 0x3f + k, 1 if second_row else 0)

    def paint(self):
        self.fills.clear()
        self.events.clear()
        self.m.call(CODE + self.sym['paint'], FB, VIEW, 0, 0)
        return self

    def texts(self, colour):
        """[(text, left, right, top, bottom, scale)] of the glyph cells drawn in colour, left to right."""
        cells = sorted((x, y, w) for x, y, w, h, c, a in self.fills if c == colour and a == 0 and w == h and w in (1, 2)
                       and (x, y, w) != (270, 222, 46))
        runs = []
        for x, y, s in cells:
            if runs and runs[-1][2] == s and x - runs[-1][1] <= 2 * s:
                runs[-1][0].append((x, y))
                runs[-1][1] = max(runs[-1][1], x)
            else:
                runs.append([[(x, y)], x, s])
        out = []
        for pts, _, s in runs:
            left, right = min(x for x, _ in pts), max(x for x, _ in pts) + s
            top, bottom = max(y for _, y in pts) + s, min(y for _, y in pts)
            text = ''
            for g in range((right - left + s) // (4 * s)):
                rows = tuple(''.join('#' if (left + 4 * s * g + c * s, top - (r + 1) * s) in pts else '.' for c in range(3))
                             for r in range(5))
                text += GLYPH.get(rows, '?')
            out.append((text, left, right, top, bottom, s))
        return out

    def numbers(self):
        return [t[0] for t in self.texts(BLACK)]

    def total(self):
        t = self.texts(WHITE)
        assert len(t) <= 1
        return t[0][0] if t else None


@pytest.fixture
def meter(m4emu):
    return Meter(m4emu)


def one_block(meter, cost):
    meter.block(0, cost)
    meter.slot(0, 0x113)
    return meter.paint()


@pytest.mark.parametrize('cost, shown', [(0, '0'), (49, '0'), (50, '1'), (149, '1'), (150, '2'), (2345, '23'), (4000, '40'),
                                         (9949, '99'), (9950, '100'), (10000, '100'), (99949, '999'), (200000, '999')])
def test_block_cost_to_per_cent(meter, cost, shown):
    """Hundredths of a per cent, rounded to the nearest per cent; three digits at most."""
    assert one_block(meter, cost).numbers() == [shown]


def test_number_is_centred_on_the_block_at_2x(meter):
    meter.block(0, 2345)
    meter.slot(3, 0x113)
    meter.m.u32(DSP + 0x14 + 0x54 * 3, 0)           # slot 3 shows record 3, whose handle is the block's
    (text, left, right, top, bottom, s), = meter.paint().texts(BLACK)
    assert (text, s) == ('23', 2)
    assert (left + right) / 2 == 41 + 34 * 3 and (top + bottom) / 2 == 0xb5


def test_lifted_block_number_follows_the_block(meter):
    """Move mode draws the picked-up block as the 28x28 square at the top of a 28x40 image."""
    meter.block(0, 2345)
    meter.slot(0, 0x104, w=28, h=40)
    (_, left, right, top, bottom, _), = meter.paint().texts(BLACK)
    assert (left + right) / 2 == 41 and (top + bottom) / 2 == 0xb5 + 20 - 14


@pytest.mark.parametrize('side, scale', [(24, 2), (12, 1), (6, None)])
def test_scale_keeps_the_number_inside_the_icon(meter, side, scale):
    meter.block(0, 2345)
    meter.slot(0, 0x113, w=side, h=side)
    t = meter.paint().texts(BLACK)
    assert [s for *_, s in t] == ([scale] if scale else [])
    for _, left, right, top, bottom, _ in t:
        assert 41 - side // 2 < left and right < 41 + side // 2 and 0xb5 - side // 2 < bottom and top < 0xb5 + side // 2


def test_empty_slot_cursor_and_hidden_slots_get_no_number(meter):
    meter.block(0, 2345)
    meter.block(1, 1000)
    meter.slot(0, CURSOR)
    meter.slot(1, None)
    assert meter.paint().numbers() == []


def test_a_second_row_block_is_read_from_its_own_record(meter):
    meter.block(2, 500)
    meter.block(10, 3000)
    meter.slot(2, 0x113, second_row=True)
    assert meter.paint().numbers() == ['30']


def blocks(meter, *costs):
    for k, cost in enumerate(costs):
        meter.block(k, cost)
        meter.slot(k, 0x113)


@pytest.mark.parametrize('setting, costs, total', [
    (0, (2345, 1000, 1349), '46/75'), (1, (2345, 1000, 1349), '29'), (2, (2345, 1000, 1349), '61%'),
    (0, (), '0/75'), (1, (), '75'), (2, (), '0%'),
    (0, (4000, 4000), '80/75'), (1, (4000, 4000), '0'), (2, (4000, 4000), '107%'),
    (2, (3700, 3800), '100%'), (1, (3700, 3800), '0'), (2, (3750, 3750), '101%'),
])
def test_total_formats(meter, setting, costs, total):
    """Used/All, Free and Used%, of the 75 per cent blocks may use (9000 less the fixed 1500)."""
    blocks(meter, *costs)
    meter.setting = setting
    assert meter.paint().total() == total


def test_total_is_the_sum_of_the_shown_numbers(meter):
    blocks(meter, 149, 149, 149, 2349)       # 1 + 1 + 1 + 23, though the raw sum rounds to 28
    meter.setting = 0
    m = meter.paint()
    assert m.numbers() == ['1', '1', '1', '23'] and m.total() == '26/75'


def test_total_counts_a_block_no_slot_shows(meter):
    blocks(meter, 2000)
    meter.block(9, 1000)                     # a second-row block behind slot 1, which shows nothing
    meter.setting = 0
    assert meter.paint().total() == '30/75'


@pytest.mark.parametrize('stored', [None, 3, 200])
def test_unset_or_out_of_range_setting_shows_the_default(meter, stored):
    blocks(meter, 2345)
    meter.setting = stored
    assert meter.paint().total() == '23/75'


def test_total_is_right_aligned_over_a_cleared_box(meter):
    blocks(meter, 2345)
    meter.setting = 0
    m = meter.paint()
    box = m.fills.index((270, 222, 46, 10, BLACK, 0))
    first = next(i for i, f in enumerate(m.fills) if f[4] == WHITE)
    assert box < first
    (_, left, right, top, bottom, s), = m.texts(WHITE)
    assert (right, top, bottom, s) == (316, 232, 222, 2)


def test_dsp_lock_is_released_before_the_widget_lock(meter):
    blocks(meter, 2345)
    ev = meter.paint().events
    assert ev[:2] == ['dsp lock', 'dsp unlock'] and ev[2] == 'widget lock' and ev[-1] == 'widget unlock'
    assert 'fill' in ev and all(e == 'fill' for e in ev[3:-1])


def test_no_dsp_model_draws_nothing_and_takes_no_dsp_lock(meter):
    blocks(meter, 2345)
    meter.m.u32(DSP_PTR, 0)
    m = meter.paint()
    assert m.events == ['widget lock', 'widget unlock'] and m.fills == []


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


def bl_target(at, hw):
    return setting_ids.bl_targets(struct.unpack('<2H', hw), at)[0]


@pytest.mark.firmware
def test_build_chains_the_module_after_the_edit_paint():
    read, on = built({'HX_DSP_METER': '1'})
    assert on == ['tuner', 'dsp_meter']
    stub = struct.unpack('<I', read(dsp_meter.EDIT_PAINT_LIT, 4))[0]
    assert stub & 1 and stub != dsp_meter.EDIT_PAINT
    stub &= ~1
    head = pm.chain_cave(stub, dsp_meter.EDIT_PAINT & ~1, [], [stub])
    after = stub + len(head) - 12                # the after handler's bl, before the epilogue
    assert read(stub, after - stub) == head[:after - stub]
    paint = bl_target(after, read(after, 4))
    assert read(paint, 4) == bytes.fromhex('f0b5 8bb0')  # push {r4-r7,lr}; sub sp,#44: paint's prologue


@pytest.mark.firmware
def test_build_sets_the_dsp_disp_label_and_limits():
    read, _ = built({'HX_DSP_METER': '1'})
    for tab in (pm.NAMES_LONG, pm.NAMES_SHORT):
        assert read(tab + pm.NAME_LEN * DISP, 9) == b'DSP\nDisp\0'
    tab, entry = pm.limits_entry(DISP)
    snippet = tab + 2 * struct.unpack('<H', read(entry, 2))[0]
    assert read(snippet, 8) == struct.pack('<4H', 0x2302, 0x2200, 0x2100, 0x2402)   # type 2, default 0, min 0, max 2


@pytest.mark.firmware
def test_without_the_flag_the_edit_paint_and_dsp_disp_id_stay_stock():
    read, on = built({})
    assert on == ['tuner']
    assert struct.unpack('<I', read(dsp_meter.EDIT_PAINT_LIT, 4))[0] == dsp_meter.EDIT_PAINT
    assert not any(read(pm.NAMES_LONG + pm.NAME_LEN * DISP, pm.NAME_LEN))


@pytest.mark.firmware
def test_builds_alongside_bpm():
    """Both features on: no overlapping writes, and the Edit paint is still the meter's alone (BPM chains the Home paint)."""
    read, on = built({'HX_DSP_METER': '1', 'HX_BPM': '1'})
    assert on == ['tuner', 'bpm', 'dsp_meter']
    stub = struct.unpack('<I', read(dsp_meter.EDIT_PAINT_LIT, 4))[0] & ~1
    head = pm.chain_cave(stub, dsp_meter.EDIT_PAINT & ~1, [], [stub])
    assert read(stub, len(head) - 12) == head[:-12]
