#!/usr/bin/env python3
"""hx_mirror.py - the HX Stomp's screen on this computer, from a build with HX_SCREEN_MIRROR=1 (tools/features/screen_mirror.py).

Each frame is one request on HX Edit's editor service (command 0x52), so HX Edit must be closed. The reply is the frame the LCD
shows, coded as its changes since the frame before (src/m4/screen_mirror.s).

  hx_mirror.py shot screen.png [--scale 2]      # one frame as a PNG
  hx_mirror.py view [--scale 3]                 # a live window (macOS: tools/mac/mirror_mac.swift, built on first use)
  hx_mirror.py view --record demo.mov           # the same, recorded as H.264 at the times the frames arrived
  hx_mirror.py bench [--frames 50]              # frames a second

A script can drive the HX Stomp while recording: Session(record='demo.mov') mirrors in the background, and its ctl (hx_ctl.HxCtl)
selects presets and writes the edit buffer between frames. No frame arrives while a ctl call runs (a preset select waits about a
second for the unit's notifications), so the recording holds the last frame meanwhile.
"""
import argparse
import json
import os
import struct
import subprocess
import sys
import threading
import time
import zlib

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hx_ctl  # noqa: E402
import hx_dfu_reboot as hxu  # noqa: E402

CMD_SCREEN = 0x52
FPS = 15                            # each frame costs the unit ~25 ms of CPU, which its own UI then waits for: more lags it
RX_WINDOW = 0x40000                 # the receive window the mirror's stream offers: a frame never waits for a window update
W, H = 320, 240
PIXELS = W * H
RUN, SKIP = 0x8000, 0x4000
YIELD_PIXELS = PIXELS // 8              # src/m4/screen_mirror.s sleeps each time its coding passes another of these
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIEWER_SRC = os.path.join(ROOT, 'tools', 'mac', 'mirror_mac.swift')
VIEWER = os.path.join(ROOT, 'build', 'mirror_mac')
RENDER_SRC = os.path.join(ROOT, 'tools', 'mac', 'stomp_render.swift')
RENDER = os.path.join(ROOT, 'build', 'stomp_render')
CONTROLS_JSON = os.path.join(ROOT, 'build', 'controls.json')
SKINS = os.path.join(ROOT, 'tools', 'mac', 'skins')    # where each photo's controls are; the photos themselves are in ART
ART = os.path.join(ROOT, 'build', 'art')                # the user's copies of the product photos: never committed
RECORDINGS = os.path.join(ROOT, 'build', 'recordings')  # a bare --record name goes here: recordings show the HX Stomp's own UI,
                                                        # so they stay out of git (and are hosted outside the repository)


def decode(blob, prev=None):
    """The frame's pixels (framebuffer order: column-major, bottom-up) from a reply and the frame before it (None: the reply must
    code every pixel), or None when the reply does not come to one frame."""
    hw = np.frombuffer(blob[:len(blob) & ~1], '<u2')
    out = np.empty(PIXELS, np.uint16) if prev is None else prev.copy()
    i = n = 0
    while i < len(hw):
        c = int(hw[i])
        if c == 0:                                  # the trailer
            break
        if c & RUN:
            c -= RUN
            if i + 1 >= len(hw) or n + c > PIXELS:
                return None
            out[n:n + c] = hw[i + 1]
            i += 2
        elif c & SKIP:
            c -= SKIP
            if prev is None or n + c > PIXELS:
                return None
            i += 1
        else:
            if i + 1 + c > len(hw) or n + c > PIXELS:
                return None
            out[n:n + c] = hw[i + 1:i + 1 + c]
            i += 1 + c
        n += c
    return out if n == PIXELS else None


def stats(blob):
    """(µs coding the frame, µs sending it) from a reply's trailer, which every reply ends with."""
    return struct.unpack('<2I', blob[-8:]) if len(blob) >= 10 else None


def events(blob):
    """(the unit's µs when it took the frame, [(µs, the 8-byte UI event)] posted since the reply before) from a reply."""
    hw = np.frombuffer(blob[:len(blob) & ~1], '<u2')
    i = 0
    while i < len(hw) and hw[i]:
        c = int(hw[i])
        i += 2 if c & RUN else 1 if c & SKIP else 1 + c
    if i + 2 > len(hw) or len(blob) < 2 * i + 4 + 12 * int(hw[i + 1]) + 12:
        return None
    at = 2 * i + 4
    return (struct.unpack_from('<I', blob, len(blob) - 12)[0],
            [(struct.unpack_from('<I', blob, at + 12 * k)[0], bytes(blob[at + 12 * k + 4:at + 12 * k + 12]))
             for k in range(int(hw[i + 1]))])


def leds(blob):
    """The footswitch rings' LEDs from a reply: [(colour, mode: 0 off, 1 on, 2 blinking)] for FS1..FS3, the colour as the LED
    driver keeps it: 0xBBGGRR (red in the low byte; TAP's red is 0x0300ff)."""
    return [(v & 0xffffff, v >> 24) for v in struct.unpack_from('<3I', blob, len(blob) - 24)] if len(blob) >= 24 else None


class Clock:
    """The unit's 32-bit µs as seconds that keep counting past its wrap (every 71 minutes)."""

    def __init__(self):
        self.last, self.base = None, 0

    def __call__(self, us):
        if self.last is not None and us < self.last and self.last - us > 1 << 31:
            self.base += 1 << 32
        self.last = us
        return (self.base + us) / 1e6


def encode(frame, prev=None):
    """The device's coding of a frame against the frame before it (None: every pixel), for tests: skips of two or more pixels as
    before, runs of three or more, literals between them (src/m4/screen_mirror.s)."""
    f, out, i, n = [int(v) for v in frame], [], 0, len(frame)
    p = None if prev is None else [int(v) for v in prev]

    def run3(j):
        return j + 2 < n and f[j] == f[j + 1] == f[j + 2]

    def same2(j):
        return p is not None and j + 1 < n and f[j] == p[j] and f[j + 1] == p[j + 1]
    wake = YIELD_PIXELS                             # where the unit sleeps next: an unchanged stretch stops there
    while i < n:
        while i >= wake:
            wake += YIELD_PIXELS
        if p is not None:
            j = i
            while j < min(n, wake) and f[j] == p[j]:
                j += 1
            if j - i >= 2:
                for k in range(i, j, 0x3fff):
                    out.append(SKIP | min(0x3fff, j - k))
                i = j
                continue
        if run3(i):
            j = i + 3
            while j < min(i + 0x7fff, n) and f[j] == f[i]:
                j += 1
            out += [RUN | (j - i), f[i]]
        else:
            j = i + 1
            while j < n and j - i < 0x3fff and not run3(j) and not same2(j):
                j += 1
            out += [j - i] + f[i:j]
        if p is not None:
            p[i:j] = f[i:j]
        i = j
    return struct.pack(f'<{len(out)}H', *out)


def rgb(frame):
    """A frame as H rows of W RGB pixels, top row first; each pixel as image_store.pixel_rgb gives it, for a whole frame at once."""
    v = frame.reshape(W, H).T[::-1].astype(np.uint32)
    return np.dstack([(v & 31) * 255 // 31, (v >> 5 & 63) * 255 // 63, (v >> 11) * 255 // 31]).astype(np.uint8)


def png(image, scale=1):
    """An RGB image (rows of pixels) as a PNG file's bytes, each pixel scale x scale."""
    image = np.repeat(np.repeat(image, scale, 0), scale, 1)
    h, w = image.shape[:2]
    raw = b''.join(b'\0' + image[y].tobytes() for y in range(h))

    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))


def quiet_reads(link):
    """The link's packet reads without the hex dump hx_dfu_reboot prints of each: a dozen ms a frame."""
    def read(timeout_ms=100):
        try:
            return bytes(link.dev.read(link.ep_in, link.mtu, timeout=timeout_ms))
        except link.usb.core.USBTimeoutError:
            return b''
        except link.usb.core.USBError as e:
            if getattr(e, 'errno', None) in (60, 110) or 'timed out' in str(e).lower():
                return b''
            raise hxu.ProtocolError('bulk IN failed: %s' % e)
    link.read = read


class _Locked:
    """An hx_ctl session whose method calls take turns with the frames: one USB stream carries both."""

    def __init__(self, ctl, lock):
        self._ctl, self._lock = ctl, lock

    def __getattr__(self, name):
        v = getattr(self._ctl, name)
        if not callable(v):
            return v

        def call(*a, **kw):
            with self._lock:
                return v(*a, **kw)
        return call


class Mirror:
    """Frames from a running HX Stomp; ctl is the hx_ctl session, whose calls wait for the frame being fetched."""

    def __init__(self, ctl=None, verbose=False):
        self.lock = threading.RLock()
        if ctl is None:
            ctl = hx_ctl.HxCtl(verbose=verbose, timeout=5.0)
            if not verbose:
                quiet_reads(ctl.link)
            hxu.RX_BUF = RX_WINDOW
        self._ctl = ctl
        self.ctl = _Locked(self._ctl, self.lock)
        self.dropped, self.timing, self.prev = 0, [], None         # timing: (µs to code, µs to send, bytes) of each frame
        self.clock, self.t, self.events = Clock(), None, []          # the unit's time of the last frame; [(time, event)]
        self.leds = []                                               # [(time, leds())] each time they change

    def frame(self):
        """The screen as RGB rows, or None when the reply did not decode (the next one then codes every pixel)."""
        with self.lock:
            blob = self._ctl.ed.request(CMD_SCREEN, timeout=5)
            if not isinstance(blob, (bytes, bytearray)):
                raise hx_ctl.HxError('screen: no frame in the reply (a build without HX_SCREEN_MIRROR=1?): %r' % (blob,))
            t = stats(bytes(blob))
            if t:
                self.timing.append(t + (len(blob),))
            ev = events(bytes(blob))
            if ev:
                self.t = self.clock(ev[0])
                self.events += [(self.t + ((us - ev[0] + (1 << 31)) % (1 << 32) - (1 << 31)) / 1e6, e) for us, e in ev[1]]
            lit = leds(bytes(blob))
            if ev and lit and (not self.leds or self.leds[-1][1] != lit):
                self.leds.append((self.t, lit))
            f = decode(bytes(blob), self.prev)
            if f is None:
                self.dropped += 1
                self.prev = None
                self._ctl.ed.seq = (self._ctl.ed.seq + 1) & 0xffff     # a seq skipped: the unit codes every pixel next
                return None
            self.prev = f
        return rgb(f)

    def close(self):
        self._ctl.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def viewer(scale, record=None, title='HX Stomp', record_scale=4, codec='h264'):
    """The macOS window (and recorder): a process taking frames on stdin. Builds it on first use."""
    args = [build_tool(VIEWER_SRC, VIEWER), str(W), str(H), str(scale), title]
    if record:
        args += [os.path.abspath(record), str(record_scale), codec]
    return subprocess.Popen(args, stdin=subprocess.PIPE)


class Session(Mirror):
    """Mirrors in the background into the window (and record, a .mov, with the UI events beside it in a .json of the same name)
    while a script uses ctl; with Session(...) as s: ... on_events(new [(time, event)]) is called as they come."""

    def __init__(self, scale=3, record=None, window=True, ctl=None, verbose=False, fps=FPS, record_scale=4, codec='h264',
                 on_events=None, render=True, skin='black'):
        super().__init__(ctl, verbose)
        self.period = 1 / fps if fps else 0
        self.view = viewer(scale, record, record_scale=record_scale, codec=codec) if window or record else None
        self.record, self.on_events, self.times, self.render, self.rendered = record, on_events, [], render, None
        self.skin = skin
        self.frames, self.last, self.error = 0, None, None
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        try:
            due = time.monotonic()
            while self.running:
                time.sleep(max(0, due - time.monotonic()))
                due = max(due + self.period, time.monotonic())
                seen = len(self.events)
                img = self.frame()
                if self.on_events and len(self.events) > seen:
                    self.on_events(self.events[seen:])
                if img is None:
                    continue
                self.last = img
                self.frames += 1
                t = self.t if self.t is not None else time.monotonic()       # the unit's clock: the events' too
                self.times.append(t)
                if self.view:
                    self.view.stdin.write(struct.pack('<d', t) + img.tobytes())
                    self.view.stdin.flush()
        except (BrokenPipeError, OSError):          # the window was closed
            self.running = False
        except Exception as e:                      # noqa: BLE001 (reported by wait() and close())
            self.error, self.running = e, False

    def wait(self, seconds):
        """Lets the recording run for seconds."""
        end = time.monotonic() + seconds
        while time.monotonic() < end and self.running:
            time.sleep(0.02)
        if self.error:
            raise self.error

    def close(self):
        self.running = False
        self.thread.join(5)
        if self.view:
            try:
                self.view.stdin.close()
            except OSError:
                pass
            self.view.wait(10)
        super().close()
        if self.record and self.times:
            with open(timeline_path(self.record), 'w') as f:
                json.dump(self.timeline(), f, indent=1)
            if self.render and os.path.exists(self.record):
                self.rendered = render(self.record, skin=self.skin)
        if self.error:
            raise self.error

    def timeline(self):
        """The recording's frames and UI events, in seconds from its first frame, as the video's times are."""
        t0 = self.times[0]
        lit = [x for x in self.leds if x[0] <= t0][-1:] + [x for x in self.leds if x[0] > t0]
        return {'frames': [round(t - t0, 6) for t in self.times],
                'events': [{'t': round(t - t0, 6), 'event': e.hex()} for t, e in self.events if t >= t0],
                'leds': [{'t': round(max(0.0, t - t0), 6), 'leds': [list(x) for x in lit]} for t, lit in lit]}


TICK = 3                            # the class of the UI's 100 Hz tick, which is no control
CONTROLS = ([('fs%d' % k, 'press footswitch %d' % k) for k in (1, 2, 3)] +
            [('fs%d' % k, 'press footswitch %d, on the attachment' % k) for k in (4, 5)] +
            [(f'knob{k}{what}', f'{verb} knob {k}{how}') for k in range(1, 6)
             for what, verb, how in (('_cw', 'turn', ' a few clicks clockwise'), ('_ccw', 'turn', ' back, anticlockwise'),
                                     ('_press', 'press', ''))] +
            [('view', 'press the home button, marked view'), ('action', 'press the action button'),
             ('page_left', 'press page left'), ('page_right', 'press page right'), ('volume', 'turn the volume knob')])
BUTTONS = ('view', 'action', 'page_left', 'page_right')


def learn(path, controls=CONTROLS, quiet=1.0, timeout=30, say=True, settle=1.0, session=None):
    """Asks for each control in turn (spoken, with macOS say) and writes, by control, every UI event it gave until quiet seconds
    passed without one, as [class, code, type, the event's hex]: to learn which event is which control."""
    import queue
    got, out = queue.Queue(), {}
    with (session or Session)(on_events=lambda new: [got.put(e) for _, e in new if e[0] != TICK]) as s:
        s.wait(settle)
        for name, prompt in controls:
            while not got.empty():
                got.get()
            print(prompt, flush=True)
            if say:
                subprocess.run(['say', prompt])
            seen = []
            try:
                seen.append(got.get(timeout=timeout))
                while True:
                    seen.append(got.get(timeout=quiet))
            except queue.Empty:
                pass
            out[name] = [[e[0], e[1], e[4], e.hex()] for e in seen]
            print('   ', name, out[name][:6], '...' if len(seen) > 6 else '', flush=True)
        if say:
            subprocess.run(['say', 'done'])
    with open(path, 'w') as f:
        json.dump(out, f, indent=1)
    return out


# The HX Stomp's controls as its UI events give them [learned on the unit, 2026-11-12]: each footswitch's click (class 1, codes
# 12..16 for FS1..FS5; FS4/FS5 come from the attachment through EXP), FS1..FS3's touch sensors (codes 9..11, before the click),
# each knob's press (class 1, codes 0..4) and turn (class 2, codes 0..4, +1 a click clockwise), the buttons (class 1, codes 5..8)
# and the volume knob (class 4: its level, a float)
STOMP = {**{f'fs{k}': {'press': [1, 11 + k]} for k in range(1, 6)},
         **{f'fs{k}': {'press': [1, 11 + k], 'touch': [1, 8 + k]} for k in range(1, 4)},
         **{f'knob{k}': {'press': [1, k - 1], 'turn': [2, k - 1, 1]} for k in range(1, 6)},
         **{name: {'press': [1, 5 + k]} for k, name in enumerate(BUTTONS)},
         'volume': {'level': [4, 0]}}


def controls_map(learned):
    """{control: {'press': [class, code], 'turn': [class, code, sign]}} from learn()'s events: a footswitch's or knob press's
    press is its class-1 code no other press prompt gave (a footswitch's touch sensor may come with it), else its commonest, or
    the class-4 event (EXP) it gave; a knob's turn is the class-2 code its clockwise prompt gave, signed so clockwise counts up."""
    def presses(name):
        return [(cls, code) for cls, code, typ, _ in learned.get(name, []) if cls == 1 and typ == 1]
    names = [n for n in learned if n.startswith('fs') or n.endswith('_press') or n in BUTTONS]
    out = {}
    for name in names:
        mine = presses(name)
        others = {p for n in names if n != name for p in presses(n)}
        pick = [p for p in mine if p not in others] or mine
        if not pick:
            pick = [(cls, code) for cls, code, _, _ in learned[name] if cls == 4]
        if pick:
            out.setdefault(name.replace('_press', ''), {})['press'] = list(max(set(pick), key=pick.count))
    level = [(cls, code) for cls, code, _, _ in learned.get('volume', []) if cls == 4]
    if level:
        out['volume'] = {'level': list(max(set(level), key=level.count))}
    for name in [n for n in learned if n.endswith('_cw')]:
        turns = [(code, struct.unpack('<i', bytes.fromhex(h)[4:8])[0]) for cls, code, _, h in learned[name] if cls == 2]
        if turns:
            codes = [c for c, _ in turns]
            code = max(set(codes), key=codes.count)
            sign = 1 if sum(v for c, v in turns if c == code) >= 0 else -1
            out.setdefault(name.replace('_cw', ''), {})['turn'] = [2, code, sign]
    return out


def tracks(timeline, cmap):
    """What stomp_render draws, from a recording's timeline and controls_map(): each control's press intervals and knob clicks."""
    end = timeline['frames'][-1] if timeline['frames'] else 0

    def held(code):
        spans, start = [], None
        for ev in timeline['events']:
            t, e = ev['t'], bytes.fromhex(ev['event'])
            if [e[0], e[1]] != code:
                continue
            if e[0] != 1:
                spans.append([t, t])                    # EXP: a moment, as there is no release
            elif e[4] == 1:
                start = t
            elif e[4] == 2 and start is not None:
                spans.append([start, t])
                start = None
        return spans + ([[start, end]] if start is not None else [])
    out = {}
    for name, how in cmap.items():
        out[name] = {'down': held(how['press']) if 'press' in how else [], 'turns': [
            [ev['t'], struct.unpack('<i', bytes.fromhex(ev['event'])[4:8])[0] * how['turn'][2]] for ev in timeline['events']
            if 'turn' in how and list(bytes.fromhex(ev['event'])[:2]) == how['turn'][:2]]}
        if 'touch' in how:
            out[name]['touch'] = held(how['touch'])
        if name in ('fs1', 'fs2', 'fs3'):
            k = int(name[2]) - 1
            out[name]['led'] = [[x['t'], *x['leds'][k]] for x in timeline.get('leds', [])]
        if 'level' in how:
            out[name]['levels'] = [[ev['t'], round(struct.unpack('<f', bytes.fromhex(ev['event'])[4:8])[0], 4)]
                                   for ev in timeline['events'] if list(bytes.fromhex(ev['event'])[:2]) == how['level']]
    return {'duration': end, 'controls': out}


def build_tool(src, exe):
    if not os.path.exists(exe) or os.path.getmtime(exe) < os.path.getmtime(src):
        os.makedirs(os.path.dirname(exe), exist_ok=True)
        subprocess.run(['swiftc', '-O', '-suppress-warnings', src, '-o', exe], check=True)
    return exe


def render(record, cmap=STOMP, skin='black'):
    """The recording set in a photo of the HX Stomp (skin: black or white, tools/mac/skins/) with its controls moving, as
    <take>.mp4 beside it, small enough to attach on GitHub."""
    with open(timeline_path(record)) as f:
        timeline = json.load(f)
    base = os.path.splitext(record)[0]
    with open(base + '-tracks.json', 'w') as f:
        json.dump(tracks(timeline, cmap), f)
    out = base + '.mp4'
    subprocess.run([build_tool(RENDER_SRC, RENDER), record, base + '-tracks.json', out, os.path.join(SKINS, skin + '.json'), ART],
                   check=True, stdout=subprocess.DEVNULL)
    return out


def timeline_path(record):
    return os.path.splitext(record)[0] + '.json'


def report(m, frames, took):
    """Frames a second, and where a frame's time goes on the HX Stomp."""
    out = '%d frames in %.1f s: %.1f a second, %d dropped' % (frames, took, frames / took, m.dropped)
    if m.timing:
        code, send, size = (sum(t[k] for t in m.timing) / len(m.timing) for k in range(3))
        out += '; on the unit, a %.1f KB reply: %.1f ms to code, %.1f ms to send, busy %.0f%% of the time' % (
            size / 1024, code / 1000, send / 1000, (code + send) / 1e6 * frames / took * 100)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('-v', '--verbose', action='store_true')
    sub = ap.add_subparsers(dest='cmd', required=True)
    sp = sub.add_parser('shot', help='one frame as a PNG')
    sp.add_argument('out')
    sp.add_argument('--scale', type=int, default=1)
    sp = sub.add_parser('view', help='a live window, and with --record a .mov')
    sp.add_argument('--scale', type=int, default=3)
    sp.add_argument('--record')
    sp.add_argument('--record-scale', type=int, default=4, help='the recording\'s pixels a screen pixel, each way (default 4: '
                    'an even scale keeps H.264\'s half-resolution colour inside each pixel)')
    sp.add_argument('--prores', action='store_true', help='record ProRes 4444, every pixel\'s colour kept (a master; big files)')
    sp.add_argument('--skin', default='black', choices=['black', 'white'], help='the HX Stomp photo the recording is set into')
    sp.add_argument('--seconds', type=float, help='stop after this long (default: when the window closes)')
    sp.add_argument('--fps', type=float, default=FPS, help='frames a second to ask for, at most (default %(default)s; 0: as fast as '
                    'the unit answers, which makes its own screen and controls lag)')
    sp = sub.add_parser('events', help='the window, and each UI event printed as it comes: to learn which control is which')
    sp.add_argument('--seconds', type=float, default=120)
    sp = sub.add_parser('learn', help='asks for each control in turn, aloud, and writes which events it gave')
    sp.add_argument('--out', default=os.path.join(ROOT, 'build', 'controls.json'))
    sp.add_argument('--only', help='these controls (comma-separated names, e.g. view,action), not all of them')
    sp = sub.add_parser('bench', help='frames a second')
    sp.add_argument('--frames', type=int, default=50)
    args = ap.parse_args()

    if args.cmd == 'shot':
        with Mirror(verbose=args.verbose) as m:
            for _ in range(5):
                img = m.frame()
                if img is not None:
                    break
            else:
                raise SystemExit('hx_mirror: every frame changed while it was sent')
        with open(args.out, 'wb') as f:
            f.write(png(img, args.scale))
        print(args.out)
    elif args.cmd == 'view':
        if args.record and not os.path.dirname(args.record):
            os.makedirs(RECORDINGS, exist_ok=True)
            args.record = os.path.join(RECORDINGS, args.record)
        with Session(args.scale, args.record, verbose=args.verbose, fps=args.fps, record_scale=args.record_scale,
                     codec='prores' if args.prores else 'h264', skin=args.skin) as s:
            start = time.monotonic()
            try:
                s.wait(args.seconds if args.seconds else 1e9)
            except KeyboardInterrupt:
                pass
            took = time.monotonic() - start
        print(report(s, s.frames, took) + (', recorded to ' + args.record if args.record else '') +
              (', assembled into ' + s.rendered if s.rendered else ''))
    elif args.cmd == 'events':
        def show(new):
            for t, e in new:
                print('%9.3f  class %d  code %3d  bytes 2-3 %02x %02x  type %d  bytes 5-7 %02x %02x %02x  (%s)' % (
                    t, e[0], e[1], e[2], e[3], e[4], e[5], e[6], e[7], e.hex()), flush=True)
        with Session(verbose=args.verbose, on_events=show) as s:
            try:
                s.wait(args.seconds)
            except KeyboardInterrupt:
                pass
    elif args.cmd == 'learn':
        only = args.only.split(',') if args.only else None
        learn(args.out, [c for c in CONTROLS if not only or c[0] in only])
        print(args.out)
    elif args.cmd == 'bench':
        with Mirror(verbose=args.verbose) as m:
            m.frame()
            start = time.monotonic()
            for _ in range(args.frames):
                m.frame()
            took = time.monotonic() - start
        print(report(m, args.frames, took))


if __name__ == '__main__':
    main()
