"""tools/features/screen_mirror.py, src/m4/screen_mirror.s and tools/hx_mirror.py: the frame coding both ends share (a frame as its
changes since the one before), the command's registration and reply run in tests/m4emu.py against a model of the editor's reply
functions, and the build on the stock firmware."""
import random
import struct
import time
import zlib

import msgpack
import numpy as np
import pytest

import features
import hx_ctl
import hx_mirror as hm
import image_store
import usb_commands
from features import screen_mirror as sm
from firmware import branch_target, menu_entry0, reader, stock_e0

FB0, FB_BYTES = 0x28d1ce98, 0x25800
LCD = 0x40008000
REGISTER, NO_PARAMS = 0x28e165f0, 0x28e19205
WRITER, PREFIX_LEN, PREFIX, PREFIX_RESET, REPLY_HEAD = 0x28e157c8, 0x28e157ec, 0x28e15810, 0x28e15834, 0x28e15878
LOCK, UNLOCK, CLOCK = 0x28e24c00, 0x28e24bb0, 0x28da6458
TRAILER = struct.pack('<5H', 0, 250, 0, 0x2345, 1)          # coding 350 - 100 µs and sending 0x12345, from Editor's clock
MOD = 0x28e60000
STREAM, VTABLE, WRITER_OBJ, COUNT, PREFIX_BUF = 0x28f80000, 0x28f80100, 0x28f80200, 0x28f80300, 0x28f80400
WRITE, FINISH, WRITER_FN = 0x28f90000, 0x28f90010, 0x28f90020
_code = {}


def screen(seed=1, noise=(100, 140, 60, 180)):
    """A frame like the HX Stomp's: black, flat panels, a gradient, and a patch of noise (x0, x1, y0, y1) as a picture has."""
    rnd = random.Random(seed)
    f = np.zeros((hm.W, hm.H), np.uint16)                      # [x][y], y up from the bottom, as the framebuffer
    f[:, 200:240] = image_store.pixel(40, 40, 40)
    f[10:310, 120] = image_store.pixel(0, 255, 0)
    f[:, 0:40] = np.arange(hm.W, dtype=np.uint16)[:, None] >> 3 << 11
    x0, x1, y0, y1 = noise
    f[x0:x1, y0:y1] = np.array([rnd.randrange(0x10000) for _ in range((x1 - x0) * (y1 - y0))], np.uint16).reshape(x1 - x0, y1 - y0)
    return f.reshape(-1)


def worst():
    """A literal pixel then a run of three, again and again: a halfword a pixel, the most the coding takes."""
    return np.array([k // 4 * 2 + (k % 4 == 0) for k in range(hm.PIXELS)], np.uint16)


def flicker(frame):
    """frame with every third pixel changed: as many short literals between skips as there can be."""
    f = frame.copy()
    f[::3] ^= 0x0841
    return f


# --- the coding, on the host ---

FRAMES = [np.zeros(hm.PIXELS, np.uint16), screen(), np.array([random.Random(2).randrange(0x10000) for _ in range(hm.PIXELS)],
          np.uint16), np.tile(np.array([1, 1, 2, 2, 2, 3], np.uint16), hm.PIXELS // 6), worst()]
IDS = ['black', 'screen', 'noise', 'pairs-and-threes', 'worst']


@pytest.mark.parametrize('frame', FRAMES, ids=IDS)
def test_a_frame_coded_whole_decodes_to_itself(frame):
    assert np.array_equal(hm.decode(hm.encode(frame)), frame)


@pytest.mark.parametrize('frame', FRAMES, ids=IDS)
def test_a_frame_coded_as_changes_decodes_against_the_one_before(frame):
    for before in (screen(5), flicker(frame), frame):
        assert np.array_equal(hm.decode(hm.encode(frame, before), before), frame)


def test_an_unchanged_frame_is_skips_only():
    f = screen()
    assert hm.encode(f, f) == struct.pack('<5H', *[hm.SKIP | 0x3fff] * 4, hm.SKIP | hm.PIXELS - 4 * 0x3fff)


def test_whole_frames_are_runs_and_literals():
    assert hm.encode(np.zeros(hm.PIXELS, np.uint16)) == struct.pack('<6H', 0xffff, 0, 0xffff, 0, 0x8000 | hm.PIXELS - 2 * 0x7fff, 0)
    noise = np.arange(hm.PIXELS, dtype=np.uint16)
    assert struct.unpack_from('<H', hm.encode(noise))[0] == 0x3fff
    assert len(hm.encode(worst())) == 2 * hm.PIXELS, 'a halfword a pixel'


def test_changes_cost_at_most_a_halfword_a_pixel():
    for f in FRAMES:
        assert len(hm.encode(flicker(f), f)) <= 2 * hm.PIXELS + 2


def test_stats_read_the_trailer():
    assert hm.stats(hm.encode(screen()) + struct.pack('<5H', 0, 0x5678, 1, 2, 3)) == (0x15678, 0x30002)
    assert hm.stats(b'') is None


def test_a_cut_frame_or_skips_with_no_frame_before_do_not_decode():
    blob = hm.encode(screen())
    assert hm.decode(blob[:-2]) is None
    assert hm.decode(blob[:len(blob) // 4 * 2] + bytes(len(blob) - len(blob) // 4 * 2)) is None
    assert np.array_equal(hm.decode(blob + bytes(10)), screen())
    assert hm.decode(hm.encode(screen(), screen(6))) is None


def test_rgb_puts_the_bottom_left_pixel_bottom_left_in_the_screens_colours():
    f = np.zeros(hm.PIXELS, np.uint16)
    f[0] = image_store.pixel(255, 0, 0)                         # x 0, y 0: the bottom left
    f[hm.H - 1] = image_store.pixel(0, 0, 255)                  # x 0, y 239: the top left
    f[(hm.W - 1) * hm.H + hm.H - 1] = 0x1234                    # the top right
    img = hm.rgb(f)
    assert img.shape == (hm.H, hm.W, 3)
    assert tuple(img[hm.H - 1, 0]) == (255, 0, 0) and tuple(img[0, 0]) == (0, 0, 255)
    assert tuple(img[0, hm.W - 1]) == image_store.pixel_rgb(0x1234)


def test_png_is_a_scaled_rgb_png():
    img = hm.rgb(screen())
    data = hm.png(img, 2)
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    assert struct.unpack('>II', data[16:24]) == (2 * hm.W, 2 * hm.H)
    raw = zlib.decompress(data[data.index(b'IDAT') + 4:data.index(b'IEND') - 8])
    row = 1 + 2 * hm.W * 3
    assert raw[2 * row + 1:2 * row + 4] == img[1, 0].tobytes(), 'output rows 2 and 3 are image row 1'


class FakeCtl:
    """An hx_ctl session whose editor answers the screen command with replies[0], replies[1], ..., the last one again and again."""

    def __init__(self, *replies):
        self.replies, self.busy, self.overlaps, self.closed, self.seq, self.seqs = list(replies), False, 0, False, 0, []
        self.ed = self

    def request(self, cmd, params=None, timeout=None):
        assert cmd == hm.CMD_SCREEN and params is None
        self.seq += 1
        self.seqs.append(self.seq)
        self.overlaps += self.busy
        self.busy = True
        time.sleep(0.002)
        self.busy = False
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]

    def select(self, preset):
        self.overlaps += self.busy
        time.sleep(0.001)
        return preset

    def close(self):
        self.closed = True


def test_a_mirror_decodes_each_reply_against_the_frame_before():
    t = struct.pack('<5H', 0, 1000, 0, 3000, 0)
    whole, changes = hm.encode(screen()) + t, hm.encode(screen(7), screen()) + t
    ctl = FakeCtl(whole, changes)
    m = hm.Mirror(ctl)
    assert np.array_equal(m.frame(), hm.rgb(screen()))
    assert np.array_equal(m.frame(), hm.rgb(screen(7)))
    assert m.timing == [(1000, 3000, len(whole)), (1000, 3000, len(changes))] and ctl.seqs == [1, 2]


def test_a_reply_that_does_not_decode_is_dropped_and_skips_a_seq_for_a_whole_frame():
    t = struct.pack('<5H', 0, 1000, 0, 3000, 0)
    ctl = FakeCtl(hm.encode(screen(7), screen()) + t, hm.encode(screen()) + t)
    m = hm.Mirror(ctl)
    assert m.frame() is None and m.dropped == 1 and m.prev is None
    assert np.array_equal(m.frame(), hm.rgb(screen()))
    assert ctl.seqs == [1, 3], 'seq 2 skipped: the unit sends every pixel when the seq does not follow'

    with pytest.raises(hx_ctl.HxError, match='HX_SCREEN_MIRROR'):
        hm.Mirror(FakeCtl(None)).frame()


def test_a_sessions_ctl_calls_wait_for_the_frame_being_fetched():
    ctl = FakeCtl(hm.encode(screen()))
    with hm.Session(window=False, ctl=ctl) as s:
        for k in range(40):
            assert s.ctl.select(k) == k
        s.wait(0.05)
    assert ctl.overlaps == 0 and s.frames > 0 and ctl.closed


# --- the command, in the M4 ---

class Editor:
    """screen_mirror.s in the M4 with the editor's reply functions modelled: the prefix they build, a stream that collects writes."""

    def __init__(self, m4emu, text, sym):
        self.sym, self.out, self.prefix, self.locked, self.events, self.on_head = sym, b'', b'', False, [], None
        self.m = m = m4emu.M4(text, MOD)
        m.map(LCD, 0x1000)
        m.u32(STREAM, VTABLE)
        m.u32(VTABLE + 4, WRITE | 1)
        m.u32(VTABLE + 0xc, FINISH | 1)
        m.write(WRITER_OBJ, struct.pack('<II', 0x1234, WRITER_FN | 1))
        m.stub(WRITER, lambda m: self.service(m, WRITER_OBJ))
        m.stub(PREFIX_LEN, lambda m: self.service(m, COUNT))
        m.stub(PREFIX, lambda m: self.service(m, PREFIX_BUF))
        m.stub(PREFIX_RESET, self.reset)
        m.stub(REPLY_HEAD, self.head)
        m.stub(WRITER_FN, lambda m: self.add(m.read(m.reg('r1'), m.reg('r2'))))
        m.stub(LOCK, lambda m: self.lock(m, True))
        m.stub(UNLOCK, lambda m: self.lock(m, False))
        m.stub(WRITE, self.write)
        m.stub(FINISH, self.finish)
        m.stub(REGISTER, lambda m: m.reg('r0', 0))
        self.clock = [100, 350, 1000, 0x12345 + 1000]
        m.stub(CLOCK, lambda m: m.reg('r0', self.clock.pop(0)))
        self.show(FB0)

    def service(self, m, ret):
        assert m.reg('r0') == 6, 'the editor service'
        m.reg('r0', ret)

    def reset(self, m):
        self.prefix = b''
        m.u32(COUNT, 0)

    def add(self, data):
        self.m.write(PREFIX_BUF + len(self.prefix), data)
        self.prefix += data
        self.m.u32(COUNT, len(self.prefix))

    def head(self, m):
        assert m.reg('r0') == WRITER_OBJ and m.reg('r2') == 0
        self.add(bytes([0x83, 0x66, 0xcd]) + struct.pack('>H', m.reg('r1')) + bytes([0x67, 0, 0x68]))
        self.events.append('head')
        if self.on_head:
            self.on_head()

    def lock(self, m, on):
        assert m.reg('r0') == STREAM - 8 and self.locked != on
        self.locked = on

    def write(self, m):
        assert m.reg('r0') == STREAM and self.locked, 'writes hold the stream lock'
        self.out += m.read(m.reg('r1'), m.reg('r2'))
        m.reg('r0', m.reg('r2'))

    def finish(self, m):
        assert m.reg('r0') == STREAM and m.reg('r1') == 0 and self.locked
        self.events.append('finish')
        m.reg('r0', 0)

    def show(self, fb):
        self.m.u32(LCD + 0x10, fb)

    def frame(self, frame, fb=FB0):
        self.m.write(fb, frame.astype('<u2').tobytes())

    def prev(self):
        return np.frombuffer(self.m.read(MOD + self.sym['sm_prev'], FB_BYTES), '<u2')

    def screen(self, seq=1):
        """The command's reply {key: value}, to a request with seq."""
        self.out, self.events, self.clock = b'', [], [100, 350, 1000, 0x12345 + 1000]
        self.m.u32(0x28f81000 + 0xc, seq)
        assert self.m.call(MOD + self.sym['sm_cmd'], STREAM, 0x28f81000) == 0
        assert not self.locked and self.events == ['head', 'finish']
        a, s, n = struct.unpack_from('<HHI', self.out)
        assert (a, s, n) == (0, 6, len(self.out) - 8), 'the message header: the reply, the editor, the length'
        return msgpack.unpackb(self.out[8:], raw=True, strict_map_key=False)


@pytest.fixture
def editor(m4emu, monkeypatch):
    monkeypatch.setattr(m4emu, 'STEPS', 20_000_000)             # a frame of literals takes some 3 M instructions
    if 'mirror' not in _code:
        _code['mirror'] = m4emu.assemble('src/m4/screen_mirror.s', features.load(), {}, inc={'usb.inc': usb_commands.inc('screen_mirror')})
    return Editor(m4emu, *_code['mirror'])


def test_register_adds_the_command_with_no_parameters(editor):
    editor.m.call(MOD + editor.sym['sm_register'])
    (cmd, desc, _, _), = editor.m.calls(REGISTER)
    assert cmd == sm.CMD == hm.CMD_SCREEN == 0x52
    assert struct.unpack('<3I', editor.m.read(desc, 12)) == (MOD + editor.sym['sm_cmd'] | 1, NO_PARAMS | 1, 0)


def test_the_reply_carries_the_shown_frame_coded_as_the_host_codes_it(editor):
    frame = screen()
    editor.frame(frame)
    rep = editor.screen(seq=1)
    assert rep[0x66] == 1 and rep[0x67] == 0
    assert rep[0x68] == hm.encode(frame) + TRAILER
    assert np.array_equal(hm.decode(rep[0x68]), frame)
    assert hm.stats(rep[0x68]) == (250, 0x12345)
    assert np.array_equal(editor.prev(), frame)


def test_the_next_seq_gets_the_changes_and_any_other_the_whole_frame(editor):
    a, b = screen(), screen(8, (30, 90, 100, 130))
    editor.frame(a)
    editor.screen(seq=1)
    assert editor.screen(seq=2)[0x68] == hm.encode(a, a) + TRAILER
    editor.frame(b)
    blob = editor.screen(seq=3)[0x68]
    assert blob == hm.encode(b, a) + TRAILER and len(blob) < len(hm.encode(b)) // 2
    assert np.array_equal(hm.decode(blob, a), b) and np.array_equal(editor.prev(), b)
    assert editor.screen(seq=5)[0x68] == hm.encode(b) + TRAILER, 'seq 4 went to another command, or was lost'
    assert editor.screen(seq=1)[0x68] == hm.encode(b) + TRAILER, 'a new session'


def test_seq_follows_across_its_wrap(editor):
    editor.frame(screen())
    editor.screen(seq=0xffff)
    assert editor.screen(seq=0)[0x68] == hm.encode(screen(), screen()) + TRAILER


def test_the_reply_follows_the_lcd_to_the_buffer_it_shows(editor):
    for k in range(3):
        editor.frame(screen(k, (10 + k, 40, 10, 30)), FB0 + FB_BYTES * k)
    editor.show(FB0 + 2 * FB_BYTES)
    assert np.array_equal(hm.decode(editor.screen(seq=1)[0x68]), screen(2, (12, 40, 10, 30)))
    editor.show(0)                                              # before the LCD is set up: the first buffer
    assert np.array_equal(hm.decode(editor.screen(seq=2)[0x68], screen(2, (12, 40, 10, 30))), screen(0, (10, 40, 10, 30)))


def odd_runs():
    """Runs of every length from 1 to 9 starting on odd and even pixels, then black: the word-at-a-time scans' edges."""
    f, v, k = [], 1, 0
    while len(f) < hm.PIXELS - 100:
        f += [v] * (1 + k % 9)
        v, k = v + 1, k + 1
    return np.array(f + [0] * (hm.PIXELS - len(f)), np.uint16)


@pytest.mark.parametrize('frame', FRAMES[3:] + [odd_runs()], ids=IDS[3:] + ['odd-runs'])
def test_the_device_codes_awkward_frames_as_the_host(editor, frame):
    editor.frame(frame)
    assert editor.screen(seq=1)[0x68] == hm.encode(frame) + TRAILER
    for k, after in enumerate((flicker(frame), odd_runs(), frame)):
        before = editor.prev().copy()
        editor.frame(after)
        assert editor.screen(seq=2 + k)[0x68] == hm.encode(after, before) + TRAILER


def test_one_changed_pixel_at_each_place_in_an_eight_word_step(editor):
    """The unchanged scan's exits: in the step's first four words or its last four, or in the two-word and one-pixel tails."""
    f = screen()
    editor.frame(f)
    editor.screen(seq=1)
    for k in range(20):
        before = editor.prev().copy()
        after = before.copy()
        after[4000 + k] ^= 0x1f
        editor.frame(after)
        assert editor.screen(seq=2 + k)[0x68] == hm.encode(after, before) + TRAILER, k


def test_a_redraw_while_the_reply_goes_out_does_not_change_it(editor):
    """The frame is coded whole before any of it is sent."""
    before, after = screen(3), screen(4)
    editor.frame(before)
    editor.on_head = lambda: editor.frame(after)
    assert editor.screen(seq=1)[0x68] == hm.encode(before) + TRAILER


def test_the_largest_codings_fit_the_output(editor):
    editor.frame(np.arange(hm.PIXELS, dtype=np.uint16) * 7)
    assert len(editor.screen(seq=1)[0x68]) == 2 * hm.PIXELS + 2 * 5 + len(TRAILER), 'five literal counts'
    editor.frame(worst())
    assert len(editor.screen(seq=1)[0x68]) == 2 * hm.PIXELS + len(TRAILER)
    editor.frame(flicker(worst()))
    blob = editor.screen(seq=2)[0x68]
    assert blob == hm.encode(flicker(worst()), worst()) + TRAILER and len(blob) <= FB_BYTES + 16 + len(TRAILER)


# --- the build, on the stock firmware ---

@pytest.mark.firmware
def test_build_registers_the_command_after_the_editors():
    e0 = stock_e0()
    new, on = menu_entry0(e0, None, {'HX_SCREEN_MIRROR': '1'})
    assert 'screen_mirror' in [features.name(m) for m in on]
    read, stock = reader(new), reader(e0)
    assert branch_target(sm.REGISTER_ALL_CALL, stock(sm.REGISTER_ALL_CALL, 4)) == sm.REGISTER_ALL
    assert read(sm.REGISTER_ALL_CALL, 4) != stock(sm.REGISTER_ALL_CALL, 4)
    for va, code, _ in sm.CALLED:
        assert read(va, len(bytes.fromhex(code))) == bytes.fromhex(code)
    assert 'screen_mirror' not in [features.name(m) for m in menu_entry0(e0, None, {})[1]], 'opt-in'


def test_the_web_page_does_not_offer_it():
    import m4cache
    assert sm.FLAG not in m4cache.web_flags() + m4cache.web_options()
