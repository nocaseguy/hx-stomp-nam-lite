"""tools/features/more_snapshots.py and src/m4/more_snapshots.s: the module run in unicorn against a fake snapshot manager and stock
select (a flip on the lit snapshot, select's view of it, bank B's defaults and edits, preset load and save, the lock), the number
it draws over the snapshot icon in bank B, and the firmware it builds."""
import os
import struct

import pytest

import features
import patch_amp as pa
import patch_menu as pm
import setting_ids
from features import more_snapshots as ms

MODS = features.load()
IDS = setting_ids.by_name()

MGR, CODE = 0x2812c630, 0x28e60000
SELECT, RECORD_INIT = 0x28de2f90, 0x28de14b4
LOCK, UNLOCK, MEMCPY, MEMSET = 0x28e24c00, 0x28e24bb0, 0x28e24c78, 0x28e24b78
STREAM, HEADER = 0x28700000, 0x28700100     # a serializer's arguments: it finds the manager itself
ICON, LABELS, NODE, FB = 0x2812ade8, 0x2812a4bc, 0x28600000, 0x28d1ce98
CAMERAS = {'white': (0x1a0, 0x71, 0x10f), 'red': (0x156, 0x105, 0x4f), 'lit': (0x13, 0x202, 0x12a)}   # Icon_Snapshot1..3, Red, Sel
LABEL_X, LABEL_Y = (53, 160, 267), 100
WIDGET_LOCK, WIDGET_UNLOCK, REDRAW, FILL, TEXT = 0x28e24970, 0x28e24ae8, 0x28db8508, 0x100017e8, 0x28db7aa4
REC, RECS, CUR, PREV, BUSY = 0x260, 0xc, 0x743, 0x744, 0x9a9
VALID, NAME = 0x24b, 0x255            # in a record: set once it holds a sound; its name, 11 bytes


def record(i):
    return MGR + RECS + REC * i


def bank_a(i):
    """Snapshot i+1's record as a loaded preset has it: a pattern of its own and its name."""
    r = bytearray([0xa0 + i]) * REC
    r[VALID] = 1
    r[NAME:NAME + 11] = f'A{i + 1}'.encode().ljust(11, b'\0')
    return bytes(r)


class Manager:
    """The module in unicorn, with the manager's records, the lock, and select doing what stock does to them."""

    def __init__(self, m4emu):
        code, self.sym = m4emu.assemble('src/m4/more_snapshots.s', MODS, IDS)
        self.m = m4emu.M4(code, CODE)
        self.stack_top = m4emu.STACK_TOP
        self.depth, self.selects, self.inits, self.held = 0, [], [], []
        self.m.stub(LOCK, self._lock)
        self.m.stub(UNLOCK, self._unlock)
        self.m.stub(MEMCPY, lambda m: m.write(m.reg('r0'), m.read(m.reg('r1'), m.reg('r2'))))
        self.m.stub(MEMSET, lambda m: m.write(m.reg('r0'), bytes([m.reg('r1') & 0xff]) * m.reg('r2')))
        self.m.stub(SELECT, self._select)
        self.m.stub(RECORD_INIT, self._init)
        self.events = []
        self.m.stub(WIDGET_LOCK, lambda m: self.events.append('widget lock'))
        self.m.stub(WIDGET_UNLOCK, lambda m: self.events.append('widget unlock'))
        self.m.stub(REDRAW, lambda m: self.events.append(('redraw', m.reg('r0'), m.reg('r1'))))
        self.m.stub(FILL, lambda m: self.events.append(('fill', m.reg('r0'), m.reg('r1'), m.reg('r2'), m.reg('r3'),
                                                        *m.stack_args(3))))
        self.m.stub(TEXT, lambda m: self.events.append(('text', m.reg('r0'), m.read(m.reg('r1'), 32).split(b'\0')[0], m.reg('r3'),
                                                        *m.stack_args(5))))     # the renderer draws to the NUL
        self.icon_style = 'white'
        self.camera(ICON, 262, 237, 6, NODE)                             # the top view's, at its stock place
        for i in range(3):
            self.camera(LABELS + 0x24 * i, LABEL_X[i], LABEL_Y, 7, NODE + 0x40 * (i + 1))
        for i in range(3):
            self.m.write(record(i), bank_a(i))
        self.m.u8(MGR + CUR, 0)
        self.m.u8(MGR + PREV, 0)
        self.m.u8(MGR + BUSY, 0)

    def _lock(self, m):
        assert m.reg('r0') == MGR + 4 and self.depth == 0, 'the manager lock, once: it may not be recursive'
        self.depth += 1

    def _unlock(self, m):
        assert m.reg('r0') == MGR + 4 and self.depth == 1
        self.depth -= 1

    def _select(self, m):
        """Stock: an unused record gets the old one's sound (not its name); then the old index becomes the previous one."""
        mgr, new = m.reg('r0'), m.reg('r1')
        assert mgr == MGR and self.depth == 0, 'select takes the lock itself'
        if self.m.read(MGR + BUSY, 1)[0]:
            self.held.append(new)
            m.reg('r0', 0)
            return
        old = self.cur()
        self.selects.append((new, old, self.rec(old), self.rec(new)))
        if not self.rec(new)[VALID]:
            m.write(record(new), self.rec(old)[:VALID] + b'\1' + self.rec(new)[VALID + 1:])
        m.u8(MGR + PREV, old)
        m.u8(MGR + CUR, new)
        m.reg('r0', 1)

    def _init(self, m):
        assert m.reg('r0') == MGR and self.depth == 0, 'the record defaults take the lock themselves'
        rec, name = m.reg('r1'), m.read(m.reg('r2'), 11)
        self.inits.append(name.rstrip(b'\0'))
        m.write(rec + VALID, b'\0')
        m.write(rec + NAME, name)

    def camera(self, w, x, y, anchor, node):
        """A visible 52x35 camera image widget."""
        for off, v in ((0xc, x), (0x10, y), (0x14, 52), (0x18, 35), (0x20, node)):
            self.m.u32(w + off, v)
        self.m.u8(w + 0x1c, anchor)
        self.m.u8(w + 0x1d, 1)

    def rec(self, i):
        return self.m.read(record(i), REC)

    def read_busy(self):
        return self.m.read(MGR + BUSY, 1)[0]

    def cur(self):
        return self.m.read(MGR + CUR, 1)[0]

    def prev(self):
        return self.m.read(MGR + PREV, 1)[0]

    def name(self, i):
        return self.rec(i)[NAME:NAME + 11].rstrip(b'\0')

    def press(self, i):
        """The footswitch for snapshot i+1 (i 0..2), as the snapshot action calls select."""
        return self.m.call(CODE + self.sym['snaps_select'], MGR, i)

    def call(self, sym, *args):
        return self.m.call(CODE + self.sym[sym], *args)

    def paint(self, view='top'):
        """The top view's (or Home view's) paint, then the module after it, with the cameras as stock sets them for the current
        snapshot; what the module did, and which camera nodes it marked to draw (0 the top icon, 1..3 the labels)."""
        cur = self.cur()
        self.m.u32(ICON, CAMERAS[self.icon_style][cur])
        for i in range(3):
            self.m.u32(LABELS + 0x24 * i, CAMERAS['lit' if i == cur else 'white'][i])
        self.events.clear()
        for n in range(4):
            self.m.u8(NODE + 0x40 * n + 0x24, 0)
        self.m.write(self.stack_top - 0x400, b'\xaa' * 0x400)     # a stack that is not zeroed, as on the unit
        sym, view_at = ('snaps_paint', 0x2812aae0) if view == 'top' else ('snaps_home_paint', 0x2812a05c)
        self.m.call(CODE + self.sym[sym], FB, view_at)
        return self.events, [n for n in range(4) if self.m.read(NODE + 0x40 * n + 0x24, 1)[0]]


@pytest.fixture
def mgr(m4emu):
    return Manager(m4emu)


def test_a_snapshot_not_lit_goes_straight_to_select(mgr):
    assert mgr.press(1) == 1
    assert mgr.selects == [(1, 0, bank_a(0), bank_a(1))] and mgr.cur() == 1 and mgr.prev() == 0
    assert [mgr.rec(i) for i in range(3)] == [bank_a(i) for i in range(3)] and mgr.inits == []


@pytest.mark.parametrize('lit', [0, 1, 2])
def test_the_lit_snapshot_again_flips_to_bank_b(mgr, lit):
    """Bank B's three records start as defaults named SNAPSHOT 4-6; select comes from the sound being left, so the new one takes it."""
    mgr.m.u8(MGR + CUR, lit)
    mgr.m.u8(MGR + PREV, 2 - lit)
    assert mgr.press(lit) == 1
    assert mgr.inits == [b'SNAPSHOT 4', b'SNAPSHOT 5', b'SNAPSHOT 6']
    (new, old, old_rec, new_rec), = mgr.selects
    assert new == lit and old != lit, 'a select of another index, so it recalls rather than reselects'
    assert old_rec == bank_a(lit), 'the record select comes from is the sound being left'
    assert not new_rec[VALID] and new_rec[NAME:NAME + 10] == f'SNAPSHOT {lit + 4}'.encode()
    assert mgr.rec(lit)[:VALID] == bank_a(lit)[:VALID] and mgr.name(lit) == f'SNAPSHOT {lit + 4}'.encode()
    assert [mgr.name(i) for i in range(3)] == [f'SNAPSHOT {i + 4}'.encode() for i in range(3)]
    assert mgr.cur() == lit and mgr.prev() == 2 - lit, 'the previous snapshot is kept'
    assert mgr.depth == 0


def test_a_second_press_flips_back_with_both_banks_kept(mgr):
    mgr.press(0)
    edited = bytearray(mgr.rec(0))
    edited[5] = 0x55                                    # an edit on snapshot 4
    mgr.m.write(record(0), edited)
    mgr.selects.clear()
    mgr.press(0)
    (new, old, old_rec, new_rec), = mgr.selects
    assert (new, old_rec, new_rec) == (0, bytes(edited), bank_a(0)), 'snapshot 1 again, from snapshot 4 with its edit'
    assert [mgr.rec(i) for i in range(3)] == [bank_a(i) for i in range(3)]
    mgr.press(0)
    assert mgr.rec(0) == bytes(edited), 'snapshot 4 keeps its edit'
    assert mgr.inits == [b'SNAPSHOT 4', b'SNAPSHOT 5', b'SNAPSHOT 6'], 'bank B is set up once a preset'


def test_another_switch_in_bank_b_selects_within_it(mgr):
    mgr.press(0)
    mgr.selects.clear()
    mgr.press(2)
    (new, old, _, _), = mgr.selects
    assert (new, old) == (2, 0) and mgr.name(2) == b'SNAPSHOT 6'


@pytest.mark.parametrize('index', [3, 8, 0xff])
def test_an_index_above_2_goes_to_select(mgr, index):
    mgr.m.u8(MGR + CUR, index & 0xff)
    mgr.press(index)
    assert [s[0] for s in mgr.selects] == [index] and mgr.inits == []


def test_while_select_is_held_off_the_press_goes_to_select(mgr):
    mgr.m.u8(MGR + BUSY, 1)
    mgr.press(0)
    assert mgr.held == [0] and mgr.selects == [] and mgr.inits == []
    assert [mgr.rec(i) for i in range(3)] == [bank_a(i) for i in range(3)]


def test_a_preset_load_starts_bank_a_and_a_new_bank_b(mgr):
    mgr.press(0)
    mgr.call('snaps_loaded', MGR, 0, 0, 0)
    for i in range(3):                                  # the parser fills the records with the new preset
        mgr.m.write(record(i), bank_a(i))
    mgr.inits.clear()
    mgr.press(0)
    assert mgr.inits == [b'SNAPSHOT 4', b'SNAPSHOT 5', b'SNAPSHOT 6']
    assert mgr.name(0) == b'SNAPSHOT 4'


@pytest.mark.parametrize('busy', [0, 1])
def test_a_save_in_bank_b_recalls_bank_a_for_the_write(mgr, busy):
    """A load takes the preset's live values for its current snapshot, so the write must run with bank A's sound live: select
    recalls snapshot 1 from snapshot 4's sound, the writer runs, then select recalls snapshot 4. Select is let run for these two,
    as the load path lets its own, and its hold is put back."""
    mgr.press(0)
    edited = bytearray(mgr.rec(0))
    edited[5] = 0x55
    mgr.m.write(record(0), edited)
    bank_b = [mgr.rec(i) for i in range(3)]
    mgr.m.u8(MGR + BUSY, busy)
    mgr.selects.clear()
    mgr.call('snaps_saving', STREAM, HEADER)
    assert [mgr.rec(i) for i in range(3)] == [bank_a(i) for i in range(3)]
    assert [(new, old_rec, new_rec) for new, _, old_rec, new_rec in mgr.selects] == [(0, bytes(edited), bank_a(0))]
    assert mgr.read_busy() == busy and mgr.held == []
    mgr.selects.clear()
    mgr.call('snaps_saved', STREAM, HEADER)
    assert [mgr.rec(i) for i in range(3)] == bank_b
    assert [(new, old_rec, new_rec) for new, _, old_rec, new_rec in mgr.selects] == [(0, bank_a(0), bytes(edited))]
    assert mgr.read_busy() == busy and mgr.held == [] and mgr.cur() == 0
    mgr.m.u8(MGR + BUSY, 0)
    mgr.press(0)
    assert [mgr.rec(i) for i in range(3)] == [bank_a(i) for i in range(3)], 'still flips back after a save'


def test_a_save_in_bank_a_changes_nothing(mgr):
    mgr.call('snaps_saving', STREAM, HEADER)
    mgr.call('snaps_saved', STREAM, HEADER)
    assert [mgr.rec(i) for i in range(3)] == [bank_a(i) for i in range(3)] and mgr.inits == []


def test_a_preset_load_during_a_save_does_not_flip_after_it(mgr):
    mgr.press(0)
    mgr.call('snaps_saving', STREAM, HEADER)
    mgr.call('snaps_loaded', MGR, 0, 0, 0)
    mgr.call('snaps_saved', STREAM, HEADER)
    assert [mgr.rec(i) for i in range(3)] == [bank_a(i) for i in range(3)]


def camera(left, bottom, digit, lit=False):
    """A camera's new number: a box over its digit (white on a lit camera's circle), then the digit in hx28_boldFont."""
    box, ink = (0xffffff, 0x101010) if lit else (0, 0xffffff)
    return [('fill', FB, left + 22, bottom + 6, 16, 22, box, 0), ('text', FB, digit.encode(), left + 29, bottom + 1, 2, ink, 1, 1)]


def top(digit):
    """What the top view's paint does in bank B: the icon's number, at its stock place (262, 237, anchor 6: top left)."""
    return ['widget lock', *camera(262, 202, digit), 'widget unlock']


def labels(lit):
    """What the Home view's paint does in bank B: 4, 5, 6 over the labels (anchor 7: x the centre, y the top), the lit one inverted."""
    out = ['widget lock']
    for i in range(3):
        out += camera(LABEL_X[i] - 26, LABEL_Y - 35, str(i + 4), i == lit)
    return out + ['widget unlock']


def test_bank_a_paints_nothing(mgr):
    assert mgr.paint() == ([], []) and mgr.paint('home') == ([], [])


@pytest.mark.parametrize('lit', [0, 1, 2])
def test_bank_b_draws_its_numbers_over_the_icon_and_the_labels(mgr, lit):
    mgr.m.u8(MGR + CUR, lit)
    mgr.events.clear()
    mgr.press(lit)
    assert mgr.events[-1] == ('redraw', 0, 1), 'the flip asks for a paint, which draws the numbers'
    assert mgr.paint() == (top(str(lit + 4)), [])
    assert mgr.paint('home') == (labels(lit), [])


def test_the_numbers_follow_the_snapshot_within_bank_b(mgr):
    mgr.press(0)
    mgr.press(2)
    assert mgr.paint() == (top('6'), [])
    assert mgr.paint('home') == (labels(2), [])


def test_an_edited_snapshots_red_icon_gets_a_white_number(mgr):
    mgr.press(0)
    mgr.icon_style = 'red'
    assert mgr.paint() == (top('4'), [])


def test_hidden_or_other_images_get_no_number(mgr):
    """A label shows text instead of a camera once its snapshot is renamed; only a visible stock camera gets a number."""
    mgr.press(0)
    mgr.m.u8(ICON + 0x1d, 0)
    assert mgr.paint() == (['widget lock', 'widget unlock'], [])
    mgr.m.u8(LABELS + 0x1d, 0)
    mgr.m.u8(LABELS + 0x24 + 0x1d, 0)
    assert mgr.paint('home') == (labels(0)[:1] + labels(0)[5:], [])


def test_back_in_bank_a_the_cameras_are_drawn_again(mgr):
    mgr.press(0)
    mgr.press(0)
    assert mgr.paint() == (['widget lock', 'widget unlock', ('redraw', 0, 1)], [0]), 'its node marked, and a paint to draw it'
    assert mgr.paint() == ([], []), 'once'
    assert mgr.paint('home') == (['widget lock', 'widget unlock', ('redraw', 0, 1)], [1, 2, 3]), 'the labels, once each paint'
    assert mgr.paint('home') == ([], [])


def test_a_preset_load_in_bank_b_draws_the_cameras_again(mgr):
    mgr.press(0)
    mgr.call('snaps_loaded', MGR, 0, 0, 0)
    assert mgr.paint() == (['widget lock', 'widget unlock', ('redraw', 0, 1)], [0])
    assert mgr.paint('home') == (['widget lock', 'widget unlock', ('redraw', 0, 1)], [1, 2, 3])
    mgr.call('snaps_loaded', MGR, 0, 0, 0)
    assert mgr.paint() == ([], []) and mgr.paint('home') == ([], []), 'a load in bank A leaves them alone'


def test_a_save_in_bank_b_keeps_the_numbers(mgr):
    """The save's flip to bank A marks the cameras for a redraw; the next paint draws bank B's numbers over them again."""
    mgr.press(0)
    mgr.call('snaps_saving', STREAM, HEADER)
    mgr.call('snaps_saved', STREAM, HEADER)
    assert mgr.paint() == (top('4') + [('redraw', 0, 1)], [0])
    assert mgr.paint() == (top('4'), [])


def test_feature_flag():
    assert ms.FLAG == 'HX_MORE_SNAPSHOTS' and not getattr(ms, 'SETTINGS', ())


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
    """The target of a b.w or bl."""
    h1, h2 = struct.unpack('<2H', hw)
    return setting_ids.bl_targets((h1, h2 | 0x4000), at)[0]


@pytest.mark.firmware
def test_build_sends_the_snapshot_footswitch_to_the_module_and_wraps_load_and_save(m4emu):
    code, sym = m4emu.assemble('src/m4/more_snapshots.s', MODS, IDS)
    read, on = built({'HX_MORE_SNAPSHOTS': '1'})
    assert 'more_snapshots' in on
    module = branch_target(ms.FS_SELECT_CALLS[0], read(ms.FS_SELECT_CALLS[0], 4)) - sym['snaps_select']
    assert read(module, len(code)) == code
    assert [branch_target(s, read(s, 4)) for s in ms.FS_SELECT_CALLS] == [module + sym['snaps_select']] * 2
    for fn, before, after in ((ms.PARSE, 'snaps_loaded', None), *((fn, 'snaps_saving', 'snaps_saved') for fn, _ in ms.SERIALIZERS)):
        stub = branch_target(fn, read(fn, 4))
        assert branch_target(stub + 6, read(stub + 6, 4)) == module + sym[before], 'push, ldm, then the before handler'
        if after:
            at = stub + len(pm.chain_cave(stub, stub, [stub], [stub])) - 12      # the after handler's bl, before the epilogue
            assert branch_target(at, read(at, 4)) == module + sym[after]


@pytest.mark.firmware
def test_build_draws_the_numbers_after_the_top_and_home_paints(m4emu):
    code, sym = m4emu.assemble('src/m4/more_snapshots.s', MODS, IDS)
    read, _ = built({'HX_MORE_SNAPSHOTS': '1'})
    module = branch_target(ms.FS_SELECT_CALLS[0], read(ms.FS_SELECT_CALLS[0], 4)) - sym['snaps_select']
    for lit, fn, handler in ((ms.TOP_PAINT_LIT, ms.TOP_PAINT, 'snaps_paint'), (ms.HOME_PAINT_LIT, ms.HOME_PAINT, 'snaps_home_paint')):
        stub = struct.unpack('<I', read(lit, 4))[0]
        assert stub & 1 and stub != fn
        stub &= ~1
        at = stub + len(pm.chain_cave(stub, stub, [], [stub])) - 12
        assert branch_target(at, read(at, 4)) == module + sym[handler]


def stock_images():
    stock = os.environ.get('HX_STOMP_HXF')
    if not stock:
        pytest.skip('HX_STOMP_HXF is not set')
    data, _ = pa.load_l6ia_from_any(stock)
    return pa.get_entry_swapped(data, 7), pa.get_entry_swapped(data, 8)


def pixels(e8, off, w, h):
    """{(x, y): pixel}, y counting up from the bottom, as the screen's column-major store."""
    px = struct.unpack_from(f'<{w * h}H', e8, off)
    return {(x, y): px[x * h + y] for x in range(w) for y in range(h)}


@pytest.mark.firmware
def test_the_number_covers_the_icon_digit_and_stays_inside_the_circle():
    """At the icon's place (top left 262, 237; anchor 6), the black box holds every white digit pixel of each snapshot icon and
    only black or digit pixels besides; hx28_boldFont's 4, 5 and 6, centred at x 291 from y 203, ink only inside the box. A lit
    camera (the labels') has a white circle and a dark digit: the box, white there, covers the digit and stays in the circle."""
    import image_store as im
    e7, e8 = stock_images()
    left, bottom = 262, 237 - 35
    box = {(x, y) for x in range(284, 300) for y in range(208, 230)}
    for name in (b'Icon_Snapshot1', b'Icon_Snapshot2', b'Icon_Snapshot3', b'Icon_Snapshot1Red', b'Icon_Snapshot2Red',
                 b'Icon_Snapshot3Red'):
        img = im.image(e7, e8, name)
        assert (img.width, img.height) == (52, 35)
        px = {(left + x, bottom + y): v for (x, y), v in pixels(e8, img.offset, 52, 35).items()}
        assert {p for p, v in px.items() if v == 0xffff} <= box, f'{name.decode()}: its digit is under the box'
        assert all(px[p] in (0, 0x0841, 0xffff) or im.pixel_rgb(px[p])[0] == im.pixel_rgb(px[p])[2] and sum(im.pixel_rgb(px[p])) > 600
                   for p in box), f'{name.decode()}: the box covers no part of the camera or its circle'
    _, table = im.font(e7, b'hx28_boldFont')
    for ch in '456':
        h, w, item = im.glyph(e7, table, ord(ch))
        off, _ = im.item(e8, item)
        ink = {(291 - w // 2 + x, 203 + y) for (x, y), v in pixels(e8, off, w, h).items() if v}
        assert ink <= box, f'{ch} inks outside the box'
    for name in (b'Icon_Snapshot1Sel', b'Icon_Snapshot2Sel', b'Icon_Snapshot3Sel'):
        img = im.image(e7, e8, name)
        assert (img.width, img.height) == (52, 35)
        px = {(left + x, bottom + y): v for (x, y), v in pixels(e8, img.offset, 52, 35).items()}
        disc = {(x, y) for x, y in px if (x - left - 29.5) ** 2 + (y - bottom - 16.5) ** 2 < 12 ** 2}
        assert {p for p in disc if px[p] != 0xffff} <= box, f'{name.decode()}: its dark digit is under the box'
        assert all((x - left - 29.5) ** 2 + (y - bottom - 16.5) ** 2 < 13.5 ** 2 for x, y in box), \
            f'{name.decode()}: the white box stays inside its white circle'


@pytest.mark.firmware
def test_without_the_flag_the_sites_stay_stock():
    read, on = built({})
    assert 'more_snapshots' not in on
    assert all(read(s, 4) == pm.thumb_bw(s, ms.SELECT) for s in ms.FS_SELECT_CALLS)
    assert read(ms.PARSE, 4) == ms.PARSE_STOCK and all(read(fn, 4) == stock for fn, stock in ms.SERIALIZERS)
    assert struct.unpack('<I', read(ms.TOP_PAINT_LIT, 4))[0] == ms.TOP_PAINT


@pytest.mark.firmware
def test_builds_alongside_the_other_features():
    _, on = built({'HX_MORE_SNAPSHOTS': '1', 'HX_BPM': '1', 'HX_DSP_METER': '1'})
    assert {'bpm', 'dsp_meter', 'more_snapshots'} <= set(on)
