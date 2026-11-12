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
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIEWER_SRC = os.path.join(ROOT, 'tools', 'mac', 'mirror_mac.swift')
VIEWER = os.path.join(ROOT, 'build', 'mirror_mac')


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


def encode(frame, prev=None):
    """The device's coding of a frame against the frame before it (None: every pixel), for tests: skips of two or more pixels as
    before, runs of three or more, literals between them (src/m4/screen_mirror.s)."""
    f, out, i, n = [int(v) for v in frame], [], 0, len(frame)
    p = None if prev is None else [int(v) for v in prev]

    def run3(j):
        return j + 2 < n and f[j] == f[j + 1] == f[j + 2]

    def same2(j):
        return p is not None and j + 1 < n and f[j] == p[j] and f[j + 1] == p[j + 1]
    while i < n:
        if p is not None:
            j = i
            while j < n and f[j] == p[j]:
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

    def frame(self):
        """The screen as RGB rows, or None when the reply did not decode (the next one then codes every pixel)."""
        with self.lock:
            blob = self._ctl.ed.request(CMD_SCREEN, timeout=5)
            if not isinstance(blob, (bytes, bytearray)):
                raise hx_ctl.HxError('screen: no frame in the reply (a build without HX_SCREEN_MIRROR=1?): %r' % (blob,))
            t = stats(bytes(blob))
            if t:
                self.timing.append(t + (len(blob),))
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


def viewer(scale, record=None, title='HX Stomp'):
    """The macOS window (and recorder): a process taking frames on stdin. Builds it on first use."""
    if not os.path.exists(VIEWER) or os.path.getmtime(VIEWER) < os.path.getmtime(VIEWER_SRC):
        os.makedirs(os.path.dirname(VIEWER), exist_ok=True)
        subprocess.run(['swiftc', '-O', VIEWER_SRC, '-o', VIEWER], check=True)
    args = [VIEWER, str(W), str(H), str(scale), title] + ([os.path.abspath(record)] if record else [])
    return subprocess.Popen(args, stdin=subprocess.PIPE)


class Session(Mirror):
    """Mirrors in the background into the window (and record, a .mov) while a script uses ctl; with Session(...) as s: ..."""

    def __init__(self, scale=3, record=None, window=True, ctl=None, verbose=False, fps=FPS):
        super().__init__(ctl, verbose)
        self.period = 1 / fps if fps else 0
        self.view = viewer(scale, record) if window or record else None
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
                img = self.frame()
                if img is None:
                    continue
                self.last = img
                self.frames += 1
                if self.view:
                    self.view.stdin.write(struct.pack('<d', time.monotonic()) + img.tobytes())
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
        if self.error:
            raise self.error


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
    sp.add_argument('--seconds', type=float, help='stop after this long (default: when the window closes)')
    sp.add_argument('--fps', type=float, default=FPS, help='frames a second to ask for, at most (default %(default)s; 0: as fast as '
                    'the unit answers, which makes its own screen and controls lag)')
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
        with Session(args.scale, args.record, verbose=args.verbose, fps=args.fps) as s:
            start = time.monotonic()
            try:
                s.wait(args.seconds if args.seconds else 1e9)
            except KeyboardInterrupt:
                pass
            took = time.monotonic() - start
        print(report(s, s.frames, took) + (', recorded to ' + args.record if args.record else ''))
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
