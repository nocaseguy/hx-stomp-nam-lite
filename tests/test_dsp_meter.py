"""tools/features/dsp_meter.py and src/m4/dsp_meter.s: the DSP Disp setting, the module run in unicorn against a fake DSP model and Edit
view (each block's per cent, the total in each format and its text widget, rounding and the ends, placement, locks) and a fake model
browser (each listed model's per cent between its icon and name), and the firmware it builds."""
import os
import struct

import pytest

import features
import patch_amp as pa
import patch_menu as pm
import setting_ids
from features import dsp_meter
from firmware import assert_virtual, branch_target, built, built_e0, reader

MODS = features.load()
IDS = setting_ids.by_name()
DISP = IDS['dsp_meter.disp']

# The fakes, at the addresses the module reads
DSP_PTR, SLOT_MODEL = 0x28449e78, 0x2812c590
DSP, NODES, BLOCKS, VIEW, CODE = 0x28500000, 0x28600000, 0x28700000, 0x28800000, 0x28e60000
FB = 0x28d1ce98
FILL, WIDGET_LOCK, WIDGET_UNLOCK = 0x100017e8, 0x28e24970, 0x28e24ae8
DSP_LOCK, DSP_UNLOCK = 0x28e07844, 0x28e0785c
TEXT = {0x28e249d0: 'init', 0x28e24a68: 'pos', 0x28e249e8: 'font', 0x28e24a28: 'colour', 0x28e24ac8: 'anchor',
        0x28e24bc0: 'text', 0x28e24bc8: 'visible', 0x28e24c90: 'erase', 0x28e24c30: 'draw'}     # the text widget's calls
CURSOR = 0x67                       # every empty slot's image, which the cursor for placing a block shows
FONT = {                            # what the glyphs must look like, independent of the module's encoding
    '0': ('###', '#.#', '#.#', '#.#', '###'), '1': ('.#.', '##.', '.#.', '.#.', '###'),
    '2': ('###', '..#', '###', '#..', '###'), '3': ('###', '..#', '###', '..#', '###'),
    '4': ('#.#', '#.#', '###', '..#', '..#'), '5': ('###', '#..', '###', '..#', '###'),
    '6': ('###', '#..', '###', '#.#', '###'), '7': ('###', '..#', '..#', '..#', '..#'),
    '8': ('###', '#.#', '###', '#.#', '###'), '9': ('###', '#.#', '###', '..#', '###'),
}
GLYPH = {tuple(rows): ch for ch, rows in FONT.items()}
WHITE, BLACK = 0xffffff, 0


def test_dsp_disp_setting():
    s, = dsp_meter.SETTINGS
    assert (s.key, s.label, s.values, s.default, s.max) == ('disp', b'DSP\nDisp', (b'Used/All', b'Free', b'Used%'), 0, 2)
    assert all(len(v) <= 8 and b'\n' not in v for v in s.values), 'a value shows 8 characters, on one line [verified on unit]'
    assert DISP == 0xd1, 'a unit keeps a setting\'s value by ID: never move it once a build has used it'
    assert dsp_meter.FLAG == 'HX_DSP_METER'


class Meter:
    """The module in unicorn: blocks in slots, the DSP Disp setting, and what paint draws."""

    def __init__(self, m4emu):
        code, self.sym = m4emu.assemble('src/m4/dsp_meter.s', MODS, IDS)
        self.m = m4emu.M4(code, CODE)
        self.fills, self.events, self.setting = [], [], None
        self.widget, self.drawn = {}, []
        self.m.stub(FILL, self._fill)
        for fn, name in TEXT.items():
            self.m.stub(fn, lambda m, name=name: self._text(m, name))
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

    def _text(self, m, name):
        """The widget's state as its setters leave it; draw notes the text shown (None while hidden)."""
        self.events.append('text ' + name)
        w = self.widget
        if name in ('erase', 'draw'):
            assert m.reg('r0') == m.reg('r1') == FB
            assert m.reg('r2') == w['at']
        else:
            assert w.setdefault('at', m.reg('r0')) == m.reg('r0')
        if name == 'init':
            w.update(inits=w.get('inits', 0) + 1, node=m.reg('r1'), visible=1)
        elif name == 'pos':
            w['pos'] = (m.reg('r1'), m.reg('r2'))
        elif name in ('font', 'colour', 'anchor', 'visible'):
            w[name] = m.reg('r1')
        elif name == 'text':
            ptr, size = m.reg('r1'), m.reg('r2')
            raw = m.read(ptr, size)
            assert b'\0' in raw, 'the text ends within the length given'
            w['text'] = raw.split(b'\0')[0].decode()
        elif name == 'draw':
            self.drawn.append(w.get('text') if w['visible'] else None)

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
        self.drawn.clear()
        self.m.call(CODE + self.sym['dsp_paint'], FB, VIEW, 0, 0)
        return self

    def texts(self, colour, rows=None):
        """[(text, left, right, top, bottom, scale)] of the glyph cells drawn in colour, left to right (top to bottom when rows
        gives the rows' (bottom, top) bands)."""
        if rows:
            return [t for lo, hi in rows for t in self._texts(colour, lambda y: lo <= y < hi)]
        return self._texts(colour, lambda y: True)

    def _texts(self, colour, within):
        cells = sorted((x, y, w) for x, y, w, h, c, a in self.fills if c == colour and a == 0 and w == h and w in (1, 2) and within(y))
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
        assert len(self.drawn) == 1
        return self.drawn[0]


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


def test_total_is_a_text_widget_on_the_title_line(meter):
    """Right-aligned at the corner, in hx21_regularFont and white as the title, on the title's baseline (0xea - 22 = 228 - 16)."""
    blocks(meter, 2345)
    meter.setting = 0
    w = meter.paint().widget
    assert (w['pos'], w['anchor'], w['font'], w['colour'], w['visible']) == ((316, 228), 8, 1, WHITE, 1)
    assert w['at'] + 0x30 <= w['node'], 'the widget and its node do not overlap'
    assert meter.texts(WHITE) == [], 'no pixel-drawn total'


def test_widget_is_made_once_and_placed_before_its_first_text(meter):
    blocks(meter, 2345)
    ev = meter.paint().events
    assert ev.index('text pos') < ev.index('text text')
    meter.paint()
    meter.paint()
    assert meter.widget['inits'] == 1 and 'text init' not in meter.events


def test_every_paint_shows_the_total_then_erases_and_draws_it(meter):
    """setVisible(1) marks it dirty every paint; the erase follows the new text, so it covers the old text and the new."""
    blocks(meter, 2345)
    meter.setting = 0
    for total in ('23/75', '0/75'):
        if total == '0/75':
            meter.block(0, 0)
        ev = [e for e in meter.paint().events if e.startswith('text')]
        assert ev[-4:] == ['text text', 'text visible', 'text erase', 'text draw']
        assert meter.widget['visible'] == 1 and meter.total() == total


def test_dsp_lock_is_released_before_the_widget_lock(meter):
    blocks(meter, 2345)
    ev = meter.paint().events
    assert ev[:2] == ['dsp lock', 'dsp unlock'] and ev[2] == 'widget lock' and ev[-1] == 'widget unlock'
    assert 'fill' in ev and 'text draw' in ev and all(e == 'fill' or e.startswith('text') for e in ev[3:-1])


def test_no_dsp_model_hides_the_total_and_takes_no_dsp_lock(meter):
    blocks(meter, 2345)
    meter.paint()
    meter.m.u32(DSP_PTR, 0)
    m = meter.paint()
    assert m.events == ['widget lock', 'text visible', 'text erase', 'text draw', 'widget unlock'] and m.fills == []
    assert m.widget['visible'] == 0 and m.total() is None


# The model browser: its list level, category and subcategory, first row's item, and five row icons, as 0x28dc3424 fills them
BROWSER = 0x28900000
LEVEL, COUNT, ITEM, COST = 0x28df0280, 0x28e0edcc, 0x28e01204, 0x28e01d50
ITEMS = 0x28a00000
MODELS = 2
NAMES_X = 60
ICON_W = 28


def wipe(r, w=ICON_W):
    """Row r's label box, cleared in black from the right edge of its w-px icon, centred on x 21, to the names."""
    return (21 + w // 2, 175 - 40 * r, NAMES_X - 21 - w // 2, 14, BLACK, 0)


class Browser(Meter):
    """The module's browser handler in unicorn: lists of model costs by (category, subcategory), and the browser showing one."""

    def __init__(self, m4emu):
        super().__init__(m4emu)
        self.lists, self.items, self.bad_items, self.level = {}, {}, set(), 0
        self.m.stub(LEVEL, self._level)
        self.m.stub(COUNT, self._count)
        self.m.stub(ITEM, self._item)
        self.m.stub(COST, self._cost)
        self.show(MODELS, cat=2, sub=0)
        for r in range(5):
            self.icon(r, 0x175)

    def _level(self, m):
        m.u8(m.reg('r0'), self.level)
        m.reg('r0', 0)
        self.events.append('level')

    def _count(self, m):
        self.events.append('count')
        costs = self.lists.get((m.reg('r0'), m.reg('r1')))
        m.reg('r0', -3 if costs is None else len(costs))

    def _item(self, m):
        key = (m.reg('r0'), m.reg('r1'), m.reg('r2'))
        if key in self.bad_items:
            m.reg('r0', -3)
            return
        at = ITEMS + 0x30 * len(self.items)
        self.items[at] = self.lists[key[:2]][key[2]]
        m.u32(m.reg('r3'), at)
        m.reg('r0', 0)

    def _cost(self, m):
        cost = self.items.get(m.reg('r0'))
        if cost is None:
            m.reg('r0', -0x15)
            return
        m.u32(m.reg('r1'), cost)
        m.reg('r0', 0)

    def show(self, level, cat, sub, first=0, path=0):
        """The browser at a list level showing (cat, sub) from item first, with the stock level getter giving path."""
        self.level = path
        self.m.u8(BROWSER + 0x40, level)
        self.m.u8(BROWSER + 0x569, first)
        self.m.u8(BROWSER + 0x56e + path, cat)
        self.m.u8(BROWSER + 0x570 + path, sub)

    def icon(self, r, image, w=ICON_W):
        """Row r's icon (None: hidden), w px wide, top-centre anchored at x 21, as the ROM list init places them."""
        wd = BROWSER + 0x22c + 0x24 * r
        self.m.u32(wd, image or 0)
        self.m.u32(wd + 0xc, 21)
        self.m.u32(wd + 0x10, 194 - 40 * r)
        self.m.u32(wd + 0x14, w)
        self.m.u32(wd + 0x18, 24)
        self.m.u8(wd + 0x1c, 7)
        self.m.u8(wd + 0x1d, image is not None)

    def paint(self):
        self.fills.clear()
        self.events.clear()
        self.items.clear()
        assert self.m.call(CODE + self.sym['dsp_browser'], FB, BROWSER, 0, 0) == 0
        return self

    def texts(self, colour, rows=None):
        return super().texts(colour, rows or [(194 - 40 * (r + 1), 194 - 40 * r) for r in range(5)])

    def numbers(self):
        return [t[0] for t in self.texts(WHITE)]


@pytest.fixture
def browser(m4emu):
    return Browser(m4emu)


def test_browser_shows_each_listed_models_per_cent(browser):
    browser.lists[(2, 0)] = [509, 520, 2345, 49, 9950]
    assert browser.paint().numbers() == ['5', '5', '23', '0', '100']


@pytest.mark.parametrize('cost, width', [(2345, 14), (509, 6)])
@pytest.mark.parametrize('icon_w', [22, 28, 36])
def test_browser_number_is_centred_between_its_rows_icon_and_name(browser, cost, width, icon_w):
    browser.lists[(2, 0)] = [cost] * 5
    for r in range(5):
        browser.icon(r, 0x175, icon_w)
    edge = 21 + icon_w // 2
    for r, (text, left, right, top, bottom, s) in enumerate(browser.paint().texts(WHITE)):
        assert s == 2 and (top, bottom) == (187 - 40 * r, 177 - 40 * r)
        assert right - left == width and abs((left - edge) - (NAMES_X - right)) <= 1 and edge < left


def test_browser_wipes_each_rows_label_before_drawing_it(browser):
    browser.lists[(2, 0)] = [2345, 509]
    browser.icon(1, None)
    browser.icon(2, 0x175, 36)
    f = browser.paint().fills
    assert wipe(2, 36) in f
    f[f.index(wipe(2, 36))] = wipe(2)
    boxes = [f.index(wipe(r)) for r in range(5)]
    assert boxes == sorted(boxes) and all(c == WHITE for *_, c, _ in f[boxes[0] + 1:boxes[1]])
    assert [c for *_, c, _ in f[boxes[1]:]] == [BLACK] * 4


def test_browser_reads_the_page_from_the_first_rows_item(browser):
    browser.lists[(11, 0)] = [100 * k for k in range(10)]
    browser.show(MODELS, cat=11, sub=0, first=3)
    assert browser.paint().numbers() == ['3', '4', '5', '6', '7']


def test_browser_takes_the_list_the_stock_level_picks(browser):
    browser.lists[(14, 1)] = [1500]
    browser.lists[(2, 0)] = [900]
    browser.show(MODELS, cat=2, sub=0)
    browser.show(MODELS, cat=14, sub=1, path=1)
    for r in range(1, 5):
        browser.icon(r, None)
    assert browser.paint().numbers() == ['15']


def test_browser_skips_hidden_rows_rows_past_the_list_and_items_without_a_cost(browser):
    browser.lists[(2, 0)] = [100, 200, 300, 400]        # four models: row 4 is past the list, though its icon is visible
    browser.icon(1, None)
    browser.bad_items.add((2, 0, 2))
    browser.lists[(2, 0)][3] = None                     # the cost function rejects it
    assert browser.paint().numbers() == ['1']


def test_browser_draws_nothing_for_a_list_the_firmware_has_not(browser):
    browser.show(MODELS, cat=1, sub=0)
    m = browser.paint()
    assert m.numbers() == [] and m.fills == [wipe(r) for r in range(5)]
    assert m.events == ['level', 'count', 'widget lock'] + ['fill'] * 5 + ['widget unlock']


@pytest.mark.parametrize('level', [0, 1, 3, 4, 5, 6])
def test_browser_leaves_other_list_levels_alone(browser, level):
    """Categories, subcategories and the rest list no models: no call, no lock, nothing drawn."""
    browser.lists[(2, 0)] = [2345] * 5
    browser.show(level, cat=2, sub=0)
    m = browser.paint()
    assert m.fills == [] and m.events == []


@pytest.mark.parametrize('level', [1, 4])
def test_browser_wipes_the_labels_once_on_leaving_the_model_list(browser, level):
    browser.lists[(2, 0)] = [2345] * 5
    browser.paint()
    browser.show(level, cat=2, sub=0)
    m = browser.paint()
    assert m.fills == [wipe(r) for r in range(5)] and m.events == ['widget lock'] + ['fill'] * 5 + ['widget unlock']
    assert browser.paint().events == []


def test_browser_takes_the_widget_lock_after_the_level_and_count(browser):
    """The level getter takes the DSP model lock, which is never held with the widget lock."""
    browser.lists[(2, 0)] = [2345]
    ev = browser.paint().events
    assert ev[:3] == ['level', 'count', 'widget lock'] and ev[-1] == 'widget unlock'
    assert 'fill' in ev and all(e == 'fill' for e in ev[3:-1])


@pytest.mark.firmware
def test_build_chains_the_module_after_the_edit_paint():
    read, on = built({'HX_DSP_METER': '1'})
    assert on == ['dsp_meter', 'splash']
    stub = struct.unpack('<I', read(dsp_meter.EDIT_PAINT_LIT, 4))[0]
    assert stub & 1 and stub != dsp_meter.EDIT_PAINT
    stub &= ~1
    head = pm.chain_cave(stub, dsp_meter.EDIT_PAINT & ~1, [], [stub])
    after = stub + len(head) - 12                # the after handler's bl, before the epilogue
    assert read(stub, after - stub) == head[:after - stub]
    paint = branch_target(after, read(after, 4))
    assert read(paint, 4) == bytes.fromhex('f0b5 8bb0')  # push {r4-r7,lr}; sub sp,#44: paint's prologue


def chained_after(read, lit, stock):
    """The after handler the build chains on the function pointer at lit."""
    stub = struct.unpack('<I', read(lit, 4))[0]
    assert stub & 1 and stub != stock
    stub &= ~1
    head = pm.chain_cave(stub, stock & ~1, [], [stub])
    after = stub + len(head) - 12                # the after handler's bl, before the epilogue
    assert read(stub, after - stub) == head[:after - stub]
    return branch_target(after, read(after, 4))


@pytest.mark.firmware
def test_build_chains_the_browser_handler_after_the_browser_paint():
    read, _ = built({'HX_DSP_METER': '1'})
    browser = chained_after(read, dsp_meter.BROWSER_PAINT_LIT, dsp_meter.BROWSER_PAINT)
    assert read(browser, 6) == bytes.fromhex('2de9 f041 82b0')   # push.w {r4-r8,lr}; sub sp,#8: browser's prologue
    assert read(dsp_meter.NAMES_X, 2) == bytes([NAMES_X, 0x23])   # movs r3, #60


@pytest.mark.firmware
def test_browser_items_are_priced_as_the_model_table_says():
    """Every model in every browser list, priced by the firmware's own item lookup and cost function run on the stock Entry 0
    (its model table sorted, as boot sorts it): the cost is the model's, plus the second model's for an amp+cab."""
    stock = os.environ.get('HX_STOMP_HXF')
    if not stock:
        pytest.skip('HX_STOMP_HXF is not set')
    import m4emu
    data, _ = pa.load_l6ia_from_any(stock)
    e0 = pa.get_entry_swapped(data, 0)
    m = m4emu.M4(b'', 0x28f80000)
    for _, off, n, dst, _ in pa._parse_e0_segments(e0):
        if dst >= 0x28000000:
            m.load(dst, e0[off:off + n])
    table = struct.unpack('<I', m.read(0x28e01c08, 4))[0]
    rows = sorted((m.read(table + 12 * i, 12) for i in range(823)), key=lambda r: struct.unpack_from('<I', r)[0])
    m.write(table, b''.join(rows))
    cost = {struct.unpack_from('<I', r)[0]: struct.unpack_from('<I', r, 8)[0] for r in rows}
    out, priced = 0x28f00100, 0
    for cat in range(19):
        for sub in range(4):
            for i in range(struct.unpack('<I', m.read(0x28e3e13c + 4 * (4 * cat + sub), 4))[0]):
                assert m.call(ITEM, cat, sub, i, out) == 0
                item = m.u32(out)
                kind, first, second = struct.unpack('<III', m.read(item, 12))
                assert m.call(COST, item, out + 4) == 0, (cat, sub, i)
                pair = (kind & 0xff) >= 0x10 and 0x30005 >> ((kind & 0xff) - 0x10) & 1     # kinds with a second model
                assert m.u32(out + 4) == cost[first] + (cost[second] if pair else 0), (cat, sub, i)
                priced += 1
    assert priced > 400


@pytest.mark.firmware
def test_build_serves_dsp_disp_as_a_virtual_setting():
    e0 = built_e0({'HX_DSP_METER': '1'})
    assert_virtual(e0, dsp_meter, dsp_meter.SETTINGS[0])
    assert not any(reader(e0)(pm.NAMES_LONG + pm.NAME_LEN * 101, pm.NAME_LEN)), 'its old real ID is left alone'


@pytest.mark.firmware
def test_without_the_flag_the_edit_paint_and_dsp_disp_id_stay_stock():
    read, on = built({})
    assert on == ['splash']
    assert struct.unpack('<I', read(dsp_meter.EDIT_PAINT_LIT, 4))[0] == dsp_meter.EDIT_PAINT
    assert struct.unpack('<I', read(dsp_meter.BROWSER_PAINT_LIT, 4))[0] == dsp_meter.BROWSER_PAINT
    assert read(dsp_meter.NAMES_X, 2) == dsp_meter.NAMES_X_STOCK
    fn, stock = pm.VIRTUAL_HOOKS['get']
    assert read(fn, len(stock)) == stock


@pytest.mark.firmware
def test_builds_alongside_bpm():
    """Both features on: no overlapping writes, and the Edit paint is still the meter's alone (BPM chains the Home paint)."""
    read, on = built({'HX_DSP_METER': '1', 'HX_BPM': '1'})
    assert on == ['bpm', 'dsp_meter', 'splash']
    stub = struct.unpack('<I', read(dsp_meter.EDIT_PAINT_LIT, 4))[0] & ~1
    head = pm.chain_cave(stub, dsp_meter.EDIT_PAINT & ~1, [], [stub])
    assert read(stub, len(head) - 12) == head[:-12]
