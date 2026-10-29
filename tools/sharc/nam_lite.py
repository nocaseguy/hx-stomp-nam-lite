#!/usr/bin/env python3
"""NAM A2 Lite's model format, reference and shared tables.

The kernel is tools/sharc/nam_multi.py's. This module holds what it shares
with the converter (tools/nam2ir.py) and its check: a model's layer order and
silence state (stream, silence), a model as a User IR (ir_samples,
level_word, input_trim), a made-up test model (placeholder), the tone
stack's and crossfade's tables (eq_table, fade_table), src/sharc/nam_a2.asm
run in ssim as the reference (reference), and the float32 model of the kernel
after the model (Pipe).
"""
import math
import os
import random
import sys

here = os.path.dirname(os.path.abspath(__file__))
root = os.path.dirname(os.path.dirname(here))
sys.path.insert(0, here)
import nam_pack
import sasm
import ssim

C = 3
IR_SAMPLES = 2048
# The HX Stomp's guitar input reaches 0 dBFS at about +11.5 dBu: users measured
# 0.775 V (0 dBu) at -11.4 dBFS on a Helix Floor and the same on an HX Stomp,
# one HX Stomp at -15.1 dBFS (TheGearForum, "Calibrating Input Level for
# Plugins", p.13, 2023), over USB/S/PDIF, not at the converter: a guess within
# some 3 dB until it is measured on the unit. The kernel gives a model whose
# file says its capture's input_level_dbu an input trim of STOMP_DBU - that.
STOMP_DBU = 11.5
HIST_N = 512
EQ_BANDS = (("low", 100.0), ("peak", 650.0), ("high", 2500.0), ("high", 5500.0))   # Bass Mid Treble Presence
IR_LIMIT = 15.8489                # HX Edit refuses a sample beyond +-24 dB (error -8317)
N_WEIGHTS = 1871                  # a model's weights (then its silence state, 72 words)


def layer_weights(w):
    """Per layer, the words in the order the kernel reads them: bias and mix-in
    per output channel, the taps [tap, oldest first][input][output], then per
    output channel bias1 and its three 1x1 weights. And the head: bias, then
    [tap][channel]; the rechannel weights; the scale."""
    o, out = C, []
    for k in nam_pack.KERNEL:
        conv, o = o, o + C * C * k
        bias, o = o, o + C
        mixin, o = o, o + C
        w1, o = o, o + C * C
        b1, o = o, o + C
        blk = []
        for i in range(C):
            blk += [w[bias + i], w[mixin + i]]
        for t in range(k):
            for j in range(C):
                for i in range(C):
                    blk.append(w[conv + (i * C + j) * k + t])
        for i in range(C):
            blk += [w[b1 + i]] + [w[w1 + i * C + j] for j in range(C)]
        out.append(blk)
    head = [w[o + C * nam_pack.HEAD_TAPS]] + [w[o + j * nam_pack.HEAD_TAPS + t]
                                              for t in range(nam_pack.HEAD_TAPS) for j in range(C)]
    return out, head, list(w[:C]), w[o + C * nam_pack.HEAD_TAPS + 1]


def stream(w):
    """The words a model is loaded as, in the kernel's order: rechannel (3), head
    (bias + 48), head scale, each layer's weights (layer_weights): 1,871; then its
    silence state (silence(): 72, each / 16, as the kernel keeps them)."""
    blocks, head, rech, scale = layer_weights(w)
    hs, xs = silence(w)
    return list(rech) + list(head) + [scale] + [x for b in blocks for x in b] + [v / 16 for v in hs + [v for x in xs for v in x]]


def silence(w):
    """What the rings hold after silence, in float32 op for op as the kernel adds:
    the head's input (3) and each layer's input x (23 x 3). With 0 in, every
    layer's input is a constant, so the state is that constant in every word. A
    change of model fills the rings with it (zeros swing the output by up to
    0.1 for the first 130 ms: a pop, even with nothing played)."""
    f = lambda x: ssim.b2f(ssim.f2b(x))
    blocks, head, rech, scale = layer_weights([f(v) for v in w])
    x = [f(r * 0.0) for r in rech]
    hs, xs = [0.0] * C, []
    for k, blk in zip(nam_pack.KERNEL, blocks):
        xs.append(list(x))
        a = []
        for i in range(C):
            v = f(f(blk[2 * i] + f(blk[2 * i + 1] * 0.0)) + 0.0)
            for t in range(k):
                for j in range(C):
                    v = f(v + f(blk[2 * C + (t * C + j) * C + i] * x[j]))
            a.append(max(v, f(v * f(0.01))))
        hs = [f(h + v) for h, v in zip(hs, a)]
        o = 2 * C + k * C * C
        for i in range(C):
            u = blk[o + 4 * i]
            for j in range(C):
                u = f(u + f(a[j] * blk[o + 4 * i + 1 + j]))
            x[i] = f(x[i] + u)
    return hs, xs


def placeholder():
    """A made-up 3-channel A2 Lite model (seeded random weights): the kernel
    checks' test model when no .nam is given (the firmware has no built-in model;
    NAM A2 Lite plays the User IR slots only)."""
    rnd = random.Random(2026)
    n = N_WEIGHTS
    return [ssim.b2f(nam_pack.f2b(rnd.uniform(-0.3, 0.3))) for _ in range(n)]


def level_word(dbu):
    """IR word 5: 10^(-dbu/20) for a capture made at `dbu` (its interface's dBu at
    0 dBFS), which the kernel multiplies by STOMP_GAIN for the input trim; 0 (no
    trim) for None. A level the word cannot hold (HX Edit's +-15.8) is refused."""
    if dbu is None:
        return 0.0
    g = ssim.b2f(nam_pack.f2b(10.0 ** (-dbu / 20.0)))
    if not 0 < g < IR_LIMIT:
        raise ValueError(f"input_level_dbu {dbu:g}: out of range (above -24 dBu)")
    return g


def input_trim(dbu):
    """The kernel's N_TRIM for a model made at `dbu` (None: none), float32 as it
    computes it."""
    f = lambda x: ssim.b2f(ssim.f2b(x))
    g = f(level_word(dbu) * f(10.0 ** (STOMP_DBU / 20)))
    return g if g > 0 else 1.0


def ir_samples(w, dbu=None):
    """The 2,048 float samples of a NAM Lite model as a User IR (tools/nam2ir.py):
    a header (word 5 the capture's input level, level_word(dbu)), then the stream divided by 2^e (exact) so that every sample is
    within HX Edit's +-15.8 limit (the header too: the word count is stored
    / 1024; 1871.0 itself was refused, -8317); the rest 0 (sample 2047 = 0:
    no tail fade)."""
    st = stream(w)
    peak = max(abs(x) for x in st)
    e = 0
    while peak / 2.0 ** e > 15.5:
        e += 1
    head = [0.5, -0.5, float(C), 2.0 ** e, N_WEIGHTS / 1024.0, level_word(dbu), 0.0, 0.0]
    out = head + [x / 2.0 ** e for x in st]
    assert len(out) < IR_SAMPLES
    assert max(abs(x) for x in out) < IR_LIMIT, "a sample HX Edit would refuse"
    # (a slot made before the silence state has 0 there: its rings start at 0)
    return [nam_pack.f2b(x) for x in out] + [0] * (IR_SAMPLES - len(out))


def eq_coefficients(kind, f0, db, fs=48000.0):
    """RBJ cookbook biquad, normalised: (b0, b1, b2, -a1, -a2). Shelves with S = 1, the peak Q 0.7."""
    A = 10 ** (db / 40)
    w0 = 2 * math.pi * f0 / fs
    c, s = math.cos(w0), math.sin(w0)
    if kind == "peak":
        al = s / (2 * 0.7)
        b = [1 + al * A, -2 * c, 1 - al * A]
        a = [1 + al / A, -2 * c, 1 - al / A]
    else:
        al = s / 2 * math.sqrt(2)
        r = 2 * math.sqrt(A) * al
        if kind == "low":
            b = [A * ((A + 1) - (A - 1) * c + r), 2 * A * ((A - 1) - (A + 1) * c), A * ((A + 1) - (A - 1) * c - r)]
            a = [(A + 1) + (A - 1) * c + r, -2 * ((A - 1) + (A + 1) * c), (A + 1) + (A - 1) * c - r]
        else:
            b = [A * ((A + 1) + (A - 1) * c + r), -2 * A * ((A - 1) + (A + 1) * c), A * ((A + 1) + (A - 1) * c - r)]
            a = [(A + 1) - (A - 1) * c + r, 2 * ((A - 1) - (A + 1) * c), (A + 1) - (A - 1) * c - r]
    return [b[0] / a[0], b[1] / a[0], b[2] / a[0], -a[1] / a[0], -a[2] / a[0]]


def eq_table():
    """EQ_TAB: per band, per knob step 0..100 (0.0 .. 10.0 on the unit), -12 .. +12 dB."""
    out = []
    for kind, f0 in EQ_BANDS:
        for step in range(101):
            out += [nam_pack.f2b(x) for x in eq_coefficients(kind, f0, (step - 50) * 0.24)]
    return out


def reference(w, sig, rings=False):
    """src/sharc/nam_a2.asm on `sig` from the silence state (its rings filled with
    silence(), as the kernel fills its own), x1 in (Drive 5.0) and x1 out (Ch Vol
    5.0), as words. rings: also its ring memory before and after."""
    n = len(sig)
    ref_src = open(os.path.join(root, "src/sharc/nam_a2.asm")).read()
    secs, syms = sasm.assemble(ref_src, "nam_a2.asm")
    ref = ssim.Sim()
    ref.load(secs)
    words = nam_pack.pack(w, C, syms["MODEL"])
    hs, xs = silence(w)
    fill = hs * nam_pack.HEAD_TAPS                  # head ring, then each layer's: [column][channel]
    for k, d, x in zip(nam_pack.KERNEL, nam_pack.DILATION, xs):
        fill += x * ((k - 1) * d + 1)
    a_ring = words[6] - syms["MODEL"]
    assert len(words) == a_ring + len(fill)
    words[a_ring:] = [nam_pack.f2b(v) for v in fill]
    for i, v in enumerate(words):
        ref.wr(syms["MODEL"] + i, v)
    IN, OUT = 0x400000, 0x410000
    for i, x in enumerate(sig):
        ref.wr(IN + i, ssim.f2b(x))                           # Drive 5.0: 0 dB
    ref.wr(syms["NAM_IN"], IN)
    ref.wr(syms["NAM_OUT"], OUT)
    ref.wr(syms["NAM_N"], n)
    ref.call(syms["NAM_PROCESS"])
    out = [ref.rd(OUT + i) for i in range(n)]       # Level 0.5: x1
    if rings:
        return out, words[a_ring:], [ref.rd(syms["MODEL"] + i) for i in range(a_ring, len(words))]
    return out


EQ_TEST = (0.8, 0.3, 0.6, 0.2)    # Bass, Mid, Treble, Presence in the check


def fade_table():
    """FADE_TAB: the model fades in by sin(pi/2 k/16), the tail out by its mirror: equal power."""
    return [nam_pack.f2b(math.sin(math.pi / 2 * k / 16)) for k in range(17)] + [nam_pack.f2b(1.0)]


class Pipe:
    """The kernel after the model, in float32 op for op: the crossfade (the model's
    output x its fade-in gain + HIST played backwards x the tail's gain, into HIST)
    and the tone stack, whose state carries on."""

    def __init__(self):
        self.f = lambda x: ssim.b2f(ssim.f2b(x))
        self.tab = [ssim.b2f(v) for v in fade_table()]
        self.hist = [0] * HIST_N
        self.hw = self.mr = self.mg = self.gain = 0
        self.co = [[1.0, 0.0, 0.0, 0.0, 0.0] for _ in range(4)]   # flat, as at boot
        self.st = [[0.0, 0.0] for _ in range(4)]

    def knobs(self, knobs=EQ_TEST):
        tab = eq_table()
        self.co = []
        for band, k in enumerate(knobs):
            i = min(100, max(0, int(k * 100 + 0.5)))
            self.co.append([ssim.b2f(v) for v in tab[(band * 101 + i) * 5: (band * 101 + i) * 5 + 5]])

    def cut(self):
        """A model change: the tail from the last output, the model silent."""
        self.mg, self.mr, self.gain = 17, (self.hw + HIST_N - 1) % HIST_N, 0

    def block(self, words):
        """One block: the model's 16 output words (None: no model, the block is 0)."""
        f, tab = self.f, self.tab
        g1 = 0 if words is None else min(16, self.gain + 1)
        words = words or [0] * 16
        g, m1 = tab[self.gain], max(0, self.mg - 1)
        dg = f(f(tab[g1] - g) * 0.0625)
        m = tab[self.mg]
        dm = f(f(tab[m1] - m) * 0.0625)
        out = []
        for wd in words:
            x = f(f(ssim.b2f(wd) * g) + f(ssim.b2f(self.hist[self.mr]) * m))
            self.mr = (self.mr - 1) % HIST_N
            self.hist[self.hw] = ssim.f2b(x)
            self.hw = (self.hw + 1) % HIST_N
            for (b0, b1, b2, na1, na2), z in zip(self.co, self.st):
                y = f(f(b0 * x) + z[0])
                z[0] = f(f(f(b1 * x) + f(na1 * y)) + z[1])
                z[1] = f(f(b2 * x) + f(na2 * y))
                x = y
            out.append(ssim.f2b(x))
            g, m = f(g + dg), f(m + dm)
        self.gain, self.mg = g1, m1
        return out
