"""The Global Settings icon strip (src/m4/strip.s, tools/patch_menu.py add_strip): six slots, a carousel over every category that
moves only to keep the current one in it, lit, each icon centred in its slot, and each feature category's lit and dim icons made from
its section icon."""
import struct

import pytest

import image_store as ims
import patch_menu as pm
from firmware import branch_target, reader, stock_entry

CAVE, VIEW = 0x28e60000, 0x28e91000
WIDGETS, WIDGET, Y = VIEW + 0x110, 0x24, 0xa6
STOCK_X = (9, 57, 111, 161, 214, 263)
STOCK_CATS = [(0x17, 0x1c7, 36), (0x209, 0x3c, 41), (0x150, 0x17c, 36), (0x11d, 0x5e, 41), (0xfd, 0x45, 36), (0xb, 0x65, 48)]
CENTRES = [2 * x + w for x, (_, _, w) in zip(STOCK_X, STOCK_CATS)]
SET_IMAGE, SET_POS = 0x28e24c18, 0x28e24c68


def run(m4emu, m, update, current):
    """[(widget, image, x)] strip_update sets for the view at category current."""
    m.u8(VIEW + 5, current)
    m.log.clear()
    m.call(update, VIEW)
    images = m.calls(SET_IMAGE)
    positions = m.calls(SET_POS)
    assert [w for w, _, _ in images] == [w for w, _, _ in positions] == [WIDGETS + WIDGET * i for i in range(6)]
    assert {y for _, _, y in positions} == {Y}
    return [(w, img, x) for (w, img, _), (_, x, _) in zip(images, positions)]


def shown(n, turns):
    """The categories in the six slots after each category of turns (the knob's path from category 0), as the carousel should
    show them: it moves only when the current one is not in it, bringing it in at the last slot on a turn right, the first on a
    turn left."""
    first, prev, out = 0, 0, []
    for cur in turns:
        if (cur - first) % n >= 6:
            first = (cur - 5) % n if 2 * ((cur - prev) % n) <= n else cur
        prev = cur
        out.append([(first + i) % n for i in range(6)])
    return out


def expected(cats, current, slots):
    return [(WIDGETS + WIDGET * i, cats[c][1] if c == current else cats[c][0], (CENTRES[i] - cats[c][2]) // 2)
            for i, c in enumerate(slots)]


def strip(m4emu, cats):
    code, sym = m4emu.assemble('src/m4/strip.s', [], {}, inc={'strip.inc': pm.strip_inc(cats, CENTRES)})
    m = m4emu.M4(code, CAVE, log_regs=('r0', 'r1', 'r2'))
    m.stub(SET_IMAGE)
    m.stub(SET_POS)
    return m, CAVE + sym['strip_update']


def features(n):
    """The stock categories and n - 6 feature ones."""
    return STOCK_CATS + [(0x241 + 2 * i, 0x242 + 2 * i, 22 + 2 * i) for i in range(n - 6)]


def turned(n, rights, lefts=0):
    """The knob's path from category 0: rights turns right, then lefts turns left, wrapping round as the menu does."""
    return [i % n for i in range(1, rights + 1)] + [(rights - i) % n for i in range(1, lefts + 1)]


def test_eight_categories_turning_right_go_round_as_a_carousel(m4emu):
    """The sections numbered from 1 as on the screen: past Breathing Line (8) the strip goes on with 1, 2, ... until it is 1..6."""
    cats = features(8)
    m, update = strip(m4emu, cats)
    run(m4emu, m, update, 0)
    windows = [[next(c for c, cat in enumerate(cats) if img in cat[:2]) + 1 for _, img, _ in run(m4emu, m, update, cur)]
               for cur in turned(8, 14)]
    assert windows == [[1, 2, 3, 4, 5, 6]] * 5 + [
        [2, 3, 4, 5, 6, 7], [3, 4, 5, 6, 7, 8],         # BPM Display, Breathing Line
        [4, 5, 6, 7, 8, 1], [5, 6, 7, 8, 1, 2], [6, 7, 8, 1, 2, 3], [7, 8, 1, 2, 3, 4], [8, 1, 2, 3, 4, 5],
        [1, 2, 3, 4, 5, 6], [2, 3, 4, 5, 6, 7]]


@pytest.mark.parametrize('n', [7, 8, 9, 12])
@pytest.mark.parametrize('rights, lefts', [(0, 0), (2 * 12 + 3, 0), (0, 2 * 12 + 3), (9, 13), (13, 4)])
def test_the_carousel_keeps_the_current_category_lit_for_any_number_of_categories(m4emu, n, rights, lefts):
    cats = features(n)
    m, update = strip(m4emu, cats)
    path = [0] + turned(n, rights, lefts)
    for cur, slots in zip(path, shown(n, path)):
        assert cur in slots
        assert run(m4emu, m, update, cur) == expected(cats, cur, slots), (cur, slots)


def test_stock_categories_keep_the_stock_strip(m4emu):
    m, update = strip(m4emu, features(8))
    for cur in [0, 1, 2, 3, 4, 5, 4, 3, 2, 1, 0]:
        got = run(m4emu, m, update, cur)
        assert got == expected(features(8), cur, range(6))
        assert [x for _, _, x in got] == list(STOCK_X), 'each stock icon at its stock x'


def test_turning_left_from_the_first_category_brings_the_last_in_at_the_first_slot(m4emu):
    m, update = strip(m4emu, features(8))
    run(m4emu, m, update, 0)
    assert [img for _, img, _ in run(m4emu, m, update, 7)] == [features(8)[7][1]] + [c[0] for c in STOCK_CATS[:5]]


def test_strip_inc_lists_each_category_and_slot():
    inc = pm.strip_inc([(0x17, 0x1c7, 36), (0x241, 0x100, 28)], CENTRES)
    assert '    .hword 0x17, 0x1c7, 36, 0\n    .hword 0x241, 0x100, 28, 0\n' in inc
    assert '    .hword 54, 155, 258, 363, 464, 574\n' in inc


@pytest.mark.firmware
def test_built_strip_scrolls_with_new_lit_and_dim_icons(m4emu):
    """BPM and breathing line: the four stock loops call one strip_update, a carousel over 8 categories; each section icon gets a
    new lit picture (its border trimmed, white at its brightest, at strip size) and a dim one."""
    out, _ = pm.menu_entries(stock_entry, None, {'HX_BPM': '1', 'HX_BREATHING_LINE': '1'})
    read = reader(out[0])
    targets = set()
    for at, (_, after) in pm.STRIP_LOOPS.items():
        code = read(at, 8)
        assert code[:2] == b'\x30\x46', 'mov r0,r6'
        targets.add(branch_target(at + 2, code[2:6]))
        off = struct.unpack('<H', code[6:])[0]
        assert off >> 11 == 0x1c and at + 10 + 2 * ((off & 0x7ff) ^ 0x400) - 0x800 == after, 'b to the code after the loop'
    update, = targets
    stock7, e7, e8 = stock_entry(7), out[7], out[8]
    n = struct.unpack_from('<I', stock7, 0x18)[0]
    assert struct.unpack_from('<I', e7, 0x18)[0] == n + 4
    px = lambda im: e8[im.offset:im.offset + im.length]
    for i, (icon, size) in enumerate((('Icon_Tempo', (35, 46)), ('Icon_DualIR', (45, 26)))):     # 22x29, and 28x16 under 6 blank rows
        src = ims.image_at(e7, e8, pm.ICONS[icon])
        lit, dim = ims.image_at(e7, e8, n + 2 * i), ims.image_at(e7, e8, n + 2 * i + 1)
        assert (lit.width, lit.height) == (dim.width, dim.height) == size, icon
        trimmed, w, h = ims.trimmed(px(src), src.width, src.height)
        assert px(lit) == ims.resized(ims.scaled(trimmed, 1 / ims.peak(trimmed)), w, h, *size)
        assert round(ims.peak(px(lit)), 1) == 1 and px(dim) == ims.scaled(px(lit), pm.STRIP_DIMMED)

    m = m4emu.M4(read(update, 0x100), update, log_regs=('r0', 'r1', 'r2'))
    m.stub(SET_IMAGE)
    m.stub(SET_POS)
    cats = STOCK_CATS + [(n + 1, n, 35), (n + 3, n + 2, 45)]
    path = [0] + turned(8, 2 * 8 + 3, 2 * 8 + 5)        # twice round to the right and back twice round to the left
    for cur, slots in zip(path, shown(8, path)):
        assert run(m4emu, m, update, cur) == expected(cats, cur, slots), (cur, slots)


@pytest.mark.firmware
def test_a_build_with_one_feature_category_goes_round_seven(m4emu):
    """The carousel's size is the build's number of categories: BPM alone makes 7, so turning right from BPM Display shows 3..7, 1."""
    out, _ = pm.menu_entries(stock_entry, None, {'HX_BPM': '1'})
    read = reader(out[0])
    update = branch_target(next(iter(pm.STRIP_LOOPS)) + 2, read(next(iter(pm.STRIP_LOOPS)) + 2, 4))
    n = struct.unpack_from('<I', stock_entry(7), 0x18)[0]
    m = m4emu.M4(read(update, 0x100), update, log_regs=('r0', 'r1', 'r2'))
    m.stub(SET_IMAGE)
    m.stub(SET_POS)
    cats = STOCK_CATS + [(n + 1, n, 35)]
    path = [0] + turned(7, 2 * 7 + 2, 9)
    for cur, slots in zip(path, shown(7, path)):
        assert run(m4emu, m, update, cur) == expected(cats, cur, slots), (cur, slots)
    assert shown(7, [0, 1, 2, 3, 4, 5, 6, 0])[-1] == [2, 3, 4, 5, 6, 0]


@pytest.mark.firmware
def test_strip_scale_and_dimming_are_the_stock_ones():
    """Each stock section's strip icon is its section icon at about STRIP_SCALE times the size, and its dim picture its lit one at
    about STRIP_DIMMED."""
    e7, e8 = stock_entry(7), stock_entry(8)
    ratios, dims = [], []
    for section in ('InsOuts', 'Prefs', 'Footswitches', 'EXPPedals', 'MIDITempo', 'Displays'):
        icon, dim, lit = (ims.image(e7, e8, f'{kind}_{section}{sel}'.encode())
                          for kind, sel in (('Icon', ''), ('Global', ''), ('Global', 'Sel')))
        ratios += [dim.width / icon.width, dim.height / icon.height]
        a, b = (struct.unpack(f'<{im.length // 2}H', e8[im.offset:im.offset + im.length]) for im in (dim, lit))
        dims += [(x >> 5 & 63) / (y >> 5 & 63) for x, y in zip(a, b) if y >> 5 & 63 > 15]
    assert abs(sum(ratios) / len(ratios) - pm.STRIP_SCALE) < 0.01
    assert abs(sum(dims) / len(dims) - pm.STRIP_DIMMED) < 0.01
