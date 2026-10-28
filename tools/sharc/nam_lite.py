#!/usr/bin/env python3
"""NAM A2 Lite for the stock HX Stomp firmware: kernel + model data, and its check.

usage: nam_lite.py [model.nam | weights.h] [-o out.asm] [--check [blocks]] [--layers N] [--meter]

Without a model file the built-in model is a made-up placeholder (see
placeholder()): NAM A2 Lite plays the models in the User IR slots only.

Writes tools/sharc/nam_lite_kernel.asm with the model's data after it (header,
layer table, weights; booted into Block 3 by the INIT blocks patch_amp.py
makes of .section dm) as the file to give `patch_amp.py patch --asm`.

--check runs the result in ssim as the stock dispatcher calls it (I0 knobs at
0.5: gain 1, level 1, I1/I2 16-sample blocks) and compares it with src/sharc/nam_a2.asm
on the same weights, and checks that the registers it promises to keep are kept.

--layers N (a test on the unit, not NAM): run only the first N layers, for a
fraction of the load; the head still runs.

--meter (a test on the unit, not NAM): the output is a 187.5 Hz square wave
whose amplitude is each block's cycle count (EMUCLK, entry to exit) x 1e-6
for 2048 blocks, then 0.05 for 2048, and so on, to be recorded over USB: at
one frequency any filter after the block scales both alike.
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
CODE = 0xC4EF8                    # where patch_amp.py puts the kernel (48-bit address, Block 2)
B2_END = 0xC8000                  # the end of Block 2 (normal words)
MODEL = 0xE4A30                   # nam_lite_kernel.asm's MODEL
B3_END = 0xE8000                  # the end of Block 3
DDR2 = 0x324500                   # after Heap 6 as patch_amp moves it (ends 0x324497)
DDR2_END = 0x328000               # the stock Heap 4 starts here
T_SIZE = 11
BUILTIN_TOP = 0x326200 + 2047     # the built-in model, laid out as an IR slot (DDR2, after the rings)
IR_SAMPLES = 2048
IR_HEAD = 8                       # s[0..7]: 0.5, -0.5, 3.0 (channels), 2^e (scale), words / 1024, level, 0, 0
EQ_C, EQ_S, EQ_IDX = 0xE7FE0, 0xE7FF4, 0xE7FFC   # nam_lite_kernel.asm's tone stack
EQ_TAB = 0x326A00                 # DDR2, after the built-in model
LISTS = 0x327200                  # DDR2: the clear list and the load map (read on a load or a clear)
DRIVE_TAB = 0x327400              # DDR2: Drive's gain per step, 0 dB at 5.0, -20 .. +20 dB (linear in dB)
STOMP_GAIN = 0x327465             # DDR2: 10^(STOMP_DBU/20), after DRIVE_TAB
# The HX Stomp's guitar input reaches 0 dBFS at about +11.5 dBu: users measured
# 0.775 V (0 dBu) at -11.4 dBFS on a Helix Floor and the same on an HX Stomp,
# one HX Stomp at -15.1 dBFS (TheGearForum, "Calibrating Input Level for
# Plugins", p.13, 2023), over USB/S/PDIF, not at the converter: a guess within
# some 3 dB until it is measured on the unit. The kernel gives a model whose
# file says its capture's input_level_dbu an input trim of STOMP_DBU - that.
STOMP_DBU = 11.5
FADE_TAB = 0x327480               # DDR2: the crossfade's gains, sin(pi/2 k/16), k = 0 .. 16, then 1.0
HIST = 0x327500                   # DDR2: the last 512 outputs (the crossfade's tail plays them back)
HIST_N = 512
EQ_BANDS = (("low", 100.0), ("peak", 650.0), ("high", 2500.0), ("high", 5500.0))   # Bass Mid Treble Presence
IR_LIMIT = 15.8489                # HX Edit refuses a sample beyond +-24 dB (error -8317)
HEAD_L = nam_pack.HEAD_TAPS - 1 + 16
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
    """A made-up 3-channel A2 Lite model (seeded random weights), for building
    without a .nam: it fills the built-in model's place, which NAM A2 Lite's
    Model knob (1 .. 128) never selects, and drives --check."""
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


def model_words(w, n_code, layers=None, dbu=None):
    """{address: word} for the model data, the memory to clear, and a summary."""
    blocks, head, rech, scale = layer_weights(w)
    n = len(nam_pack.KERNEL)
    b2 = 0xC0000 + -(-(CODE - 0xC0000 + n_code) * 3 // 2)      # Block 2 after the code (normal words)
    rings = [((k - 1) * d + 16) for k, d in zip(nam_pack.KERNEL, nam_pack.DILATION)]
    mem = {}

    def put(a, vals):
        for i, v in enumerate(vals):
            assert a + i not in mem
            mem[a + i] = v

    # weights: Block 2 after the code while they fit, then Block 3
    wt, b3_weights = [], []
    for blk in blocks + [head]:
        if b2 + len(blk) <= B2_END:
            wt.append(b2)
            b2 += len(blk)
        else:
            wt.append(None)
            b3_weights.append(len(blk))
    # Block 3: header (9 + the clear list), table, rechannel, weights that did not fit, rings
    for n_ddr in range(0, 4):
        far = [i for i, (k, d) in enumerate(zip(nam_pack.KERNEL, nam_pack.DILATION)) if d == 239][:n_ddr]
        n_clr = C * (1 + n)                                     # each channel's head ring and layer rings
        n_load = 3 + n                                          # rechannel, head, scale, layers
        a = MODEL + 12
        table = a
        a += T_SIZE * n
        a_rech = a
        a += C
        a += sum(b3_weights)
        a += 3 * (HEAD_L + 1)
        a += sum(3 * (rings[i] + 1) for i in range(n) if i not in far)
        if a <= EQ_C:
            break
    else:
        raise SystemExit("the rings do not fit")
    a = a_rech + C
    for i, blk in enumerate(blocks + [head]):
        if wt[i] is None:
            wt[i] = a
            a += len(blk)
        put(wt[i], [nam_pack.f2b(x) for x in blk])
    put(a_rech, [nam_pack.f2b(x) for x in rech])
    clr = []                                        # (address, length), filled with the silence state
    hb = [a + j * (HEAD_L + 1) for j in range(C)]
    clr += [(b, HEAD_L + 1) for b in hb]
    a += 3 * (HEAD_L + 1)
    far_a = DDR2
    tab = []
    for i, (k, d) in enumerate(zip(nam_pack.KERNEL, nam_pack.DILATION)):
        L = rings[i]
        if i in far:
            bases = [far_a + j * L for j in range(C)]
            for b in bases:
                clr.append((b, L))
            far_a += C * L
            s = 16
        else:
            bases = [a + j * (L + 1) for j in range(C)]
            clr += [(b, L + 1) for b in bases]
            a += C * (L + 1)
            s = d
        steps = [-(k - 1) * s, 2 - 2 * s, 2 - s]
        assert all(abs(x) < L for x in steps + [-(k - 1) * d]), "a step as long as the ring"
        tab += [bases[0], bases[1] - bases[0], L, 0, k, s, wt[i], -(k - 1) * d & 0xFFFFFFFF,
                1 if i in far else 0, (d - 16) & 0xFFFFFFFF, steps[0] & 0xFFFFFFFF]
    assert a <= EQ_C and far_a <= DDR2_END
    assert len(clr) == n_clr, (len(clr), n_clr)
    # the clear list: (address, length, value) - the value the built-in model's
    # silence state, replaced by each model's as it loads (the load map's last 72 runs)
    hs, xs = silence(w)
    vals = [v / 16 for v in hs + [v for x in xs for v in x]]
    clr_list = [n_clr] + [x for r, v in zip(clr, vals) for x in (r[0], r[1], nam_pack.f2b(v))]
    runs = [(a_rech, C), (wt[n], len(head)), (MODEL + 4, 1)] + [(wt[i], len(blocks[i])) for i in range(n)]
    runs += [(LISTS + 3 + 3 * r, 1) for r in range(n_clr)]
    assert sum(ln for _, ln in runs) == len(stream(w))
    load_map = [len(runs)] + [x for r in runs for x in r]
    put(LISTS, clr_list + load_map)
    header = [layers or n, table, a_rech, wt[n], nam_pack.f2b(scale)] + hb + [0, LISTS + len(clr_list),
                                                                             BUILTIN_TOP, LISTS]
    assert MODEL + len(header) <= table
    assert BUILTIN_TOP - IR_SAMPLES >= far_a
    for k, v in enumerate(ir_samples(w, dbu)):     # the built-in model, top-down as in an IR slot
        mem[BUILTIN_TOP - k] = v
    put(EQ_TAB, eq_table())
    assert EQ_TAB > BUILTIN_TOP and EQ_TAB + 4 * 101 * 5 <= LISTS
    put(EQ_IDX, [0x80000000] * 4)                  # no step yet: the first call loads them
    put(EQ_C, [nam_pack.f2b(x) for x in [1.0, 0.0, 0.0, 0.0, 0.0] * 4])   # flat until then
    put(EQ_S, [0] * 8)                             # the tone stack's state: 0 at boot, never cleared
    put(FADE_TAB, fade_table())
    put(HIST, [0] * HIST_N)
    assert DRIVE_TAB + 101 <= FADE_TAB and FADE_TAB + 18 <= HIST and HIST + HIST_N <= DDR2_END
    assert LISTS + len(clr_list) + len(load_map) <= DRIVE_TAB
    put(DRIVE_TAB, [nam_pack.f2b(10.0 ** ((step - 50) * 0.4 / 20)) for step in range(101)])   # 0.4 dB a step
    assert DRIVE_TAB + 101 <= STOMP_GAIN < FADE_TAB
    put(STOMP_GAIN, [nam_pack.f2b(10.0 ** (STOMP_DBU / 20))])
    put(MODEL, header)
    put(table, tab)
    used = {"block 2 to": b2, "block 3 to": a, "DDR2 to": far_a, "layers in DDR2": far}
    return mem, used


METER_ENTRY = '''    DM(N_SAVE + 63) = R0;               // --meter: EMUCLK at entry
    R0 = EMUCLK;
    DM(N_T0) = R0;
    R0 = DM(N_SAVE + 63);
'''


METER = '''    R0 = EMUCLK;                        // --meter: a 187.5 Hz square wave (16 blocks a period)
    R1 = DM(N_T0);                      // whose amplitude is the block's cycles x 1e-6 for
    R0 = R0 - R1;                       // 2048 blocks, then 0.05 for 2048: a filter after
    F0 = FLOAT R0;                      // the block scales both alike
    F1 = 0.000001;
    F0 = F0 * F1;
    R2 = DM(N_MCNT);
    R1 = 1;
    R1 = R2 + R1;
    DM(N_MCNT) = R1;
    BTST R2 BY 11;
    IF SZ JUMP n_m2;
    F0 = 0.05;
n_m2: BTST R2 BY 3;
    IF NOT SZ F0 = -F0;
    I11 = B11;
    LCNTR = 16, DO n_m0 UNTIL LCE;
n_m0: PM(I11, M9) = F0;
'''


def build(w, layers=None, meter=False, dbu=None):
    src = open(os.path.join(here, "nam_lite_kernel.asm")).read()
    if meter:
        src = src.replace("    // METER (nam_lite.py --meter puts code here)\n", METER)
        src = src.replace("    // METER ENTRY (nam_lite.py --meter puts code here)\n", METER_ENTRY)
    secs, _ = sasm.assemble(src, "nam_lite_kernel.asm")
    n_code = sum(len(s.words) for s in secs if s.kind == "pm")
    mem, used = model_words(w, n_code, layers, dbu)
    lines = ["", "// ---- model data, written by tools/sharc/nam_lite.py ----"]
    last = None
    for a in sorted(mem):
        if a != (last or 0) + 1:
            lines.append(f".section dm {a:#x}")
        lines.append(f"    .word {mem[a]:#010x}")
        last = a
    return src + "\n".join(lines) + "\n", used


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


MAX_CYCLES = 35000                # a block's cycles at most (steady): a slower kernel fails the check


class CheckFailed(Exception):
    pass


class KernelCheck:
    """The kernel in ssim as the stock dispatcher calls it, step by step (STEPS, in
    order: each carries on from the sim's state the ones before it left). A step
    raises CheckFailed with what is wrong; tests/test_kernel.py runs one test a step."""

    STEPS = ("silence_fixed_point", "first_call_passes_through", "plays_while_second_passes_through",
             "bit_exact", "cycle_budget", "second_takes_over", "slot_model_crossfades", "cab_ir_is_silent",
             "model_0_is_builtin")

    def __init__(self, asm, w, nblk=6, dbu=None):
        self.w, self.nblk, self.n = w, nblk, 16 * nblk
        self.g0 = input_trim(dbu)                      # the built-in model's input trim
        self.sig = [0.3 * math.sin(0.031 * i) * math.exp(-i / 300) + 0.1 * math.sin(0.41 * i) + (0.5 if i == 7 else 0)
                    for i in range(self.n)]
        secs, self.syms = sasm.assemble(asm, "nam_lite.asm")
        self.code = sum(len(s.words) for s in secs if s.kind == "pm")
        sim = self.sim = ssim.Sim()
        sim.strict_cbufen = True
        sim.load(secs)
        rnd = self.rnd = random.Random(1)
        for a in range(0xE4842, 0xE8000):              # the rings start as whatever was there
            if a not in sim.dm:
                sim.wr(a, rnd.getrandbits(32))
        self.PA, self.PB, self.ST, self.BI, self.BO = 0xB3000, 0xB3400, 0x91000, 0xB3100, 0xB3200
        for p in (self.PA, self.PB):
            sim.wr(p + 5, ssim.f2b(0.5))
            sim.wr(p + 6, ssim.f2b(0.5))
            for j, k in enumerate(EQ_TEST):
                sim.wr(p + 8 + j, ssim.f2b(k))
        self.keep = [c for c in range(0x10, 0x40) if c not in (0x11, 0x12)]   # all DAG registers but I1, I2
        self.worst = 0
        self.blocks = [[ssim.f2b(x) for x in self.sig[16 * b: 16 * b + 16]] for b in range(nblk)]
        self.noise = [[ssim.f2b(rnd.uniform(-0.5, 0.5)) for _ in range(16)] for _ in range(nblk)]
        self.zero = [0] * 16
        self.pipe = Pipe()
        self.got, self.want = [], []

    def trimmed(self, sig):
        """What the built-in model sees of `sig` at Drive 5.0: x its trim, in float32."""
        return [ssim.b2f(ssim.f2b(ssim.b2f(ssim.f2b(x)) * self.g0)) for x in sig]

    def run(self):
        for name in self.STEPS:
            getattr(self, name)()

    def call(self, p, block, label):
        """One call as the dispatcher makes it, for the instance whose block is p."""
        sim, rnd = self.sim, self.rnd
        for k in range(16):
            sim.wr(self.BI + k, block[k])
        for r in range(16):
            sim.setR(r, rnd.getrandbits(32))
            sim.alt[r] = rnd.getrandbits(32)        # PEy's registers (S0-S15)
        for c in range(0x30, 0x40):                 # L registers 0, as the dispatcher leaves them
            sim.set(c, 0)
        for c, v in ((0x10, p), (0x18, self.ST), (0x11, self.BI), (0x12, self.BO)):
            sim.set(c, v)
        sim.u[ssim.U_MODE1] &= ~0x1000000           # CBUFEN off: the kernel must set it itself
        mode1 = sim.u[ssim.U_MODE1]
        before_s = list(sim.alt[:16])
        before_r = [sim.R(r) for r in range(16)]
        before_u = {c: sim.get(c) for c in self.keep}
        cyc = sim.call(self.syms["CUSTOM_AMP_ENTRY"])
        if label.startswith("A block") and label != "A block 0":     # steady state: no clearing
            self.worst = max(self.worst, cyc)
        bad = [f"R{r}" for r in range(16) if sim.R(r) != before_r[r]]
        bad += [f"{c:#x}" for c in self.keep
                if sim.get(c) != before_u[c] and not (0x30 <= c < 0x40 and sim.get(c) == 0)]
        bad += [f"S{r}" for r in range(16) if sim.alt[r] != before_s[r]]
        if sim.u[ssim.U_MODE1] != mode1:
            bad.append("MODE1")
        if bad:
            raise CheckFailed(f"{label}: registers changed: {bad}")
        if sim.loops or sim.pcstk:
            raise CheckFailed(f"{label}: returns with the loop or PC stack not empty")
        return [sim.rd(self.BO + k) for k in range(16)]

    def expect(self, p, block, label, words):
        """A call whose output must be the pipe's on the model's words (None: no model)."""
        got = self.call(p, block, label)
        if got != self.pipe.block(words):
            raise CheckFailed(f"{label}: not the expected output")
        return got

    def silence_fixed_point(self):
        """silence() is nam_a2.asm's steady state: zeros in leave its rings as they were."""
        _, before, after = reference(self.w, [0.0] * 32, rings=True)
        if before != after:
            raise CheckFailed("silence(): not a fixed point of nam_a2.asm")

    def first_call_passes_through(self):
        """A's first call passes through (no owner yet); then A owns the memory and
        loads the model (a block with only the tail, of nothing yet)."""
        if self.call(self.PA, self.zero, "A first") != self.zero:
            raise CheckFailed("A's first call (no owner yet) did not pass its input through")
        self.pipe.cut()
        if self.expect(self.PA, self.zero, "A load", None) != self.zero:
            raise CheckFailed("A's first owned call (loading the model) is not silent")
        self.pipe.knobs()

    def plays_while_second_passes_through(self):
        """A plays the built-in model; B, called after A every block, passes its input through untouched."""
        ref = reference(self.w, self.trimmed(self.sig))
        for b in range(self.nblk):
            self.want += self.pipe.block(ref[16 * b: 16 * b + 16])
            self.got += self.call(self.PA, self.blocks[b], f"A block {b}")
            if self.call(self.PB, self.noise[b], f"B block {b}") != self.noise[b]:
                raise CheckFailed(f"B block {b}: a second instance did not pass its input through")

    def bit_exact(self):
        """A's output is nam_a2.asm's, then the tone stack in float32, bit for bit."""
        same = sum(a == b for a, b in zip(self.want, self.got))
        peak = max(abs(ssim.b2f(a)) for a in self.want)
        err = max(abs(ssim.b2f(a) - ssim.b2f(b)) for a, b in zip(self.want, self.got))
        if same != self.n:
            raise CheckFailed(f"{self.n - same} of {self.n} samples differ, by up to {err:.3g}")
        if peak <= 1e-3:
            raise CheckFailed(f"peak {peak:.3g}: the test signal is too quiet to show anything")

    def cycle_budget(self):
        if self.worst > MAX_CYCLES:
            raise CheckFailed(f"{self.worst} cycles a block, over MAX_CYCLES {MAX_CYCLES}")

    def second_takes_over(self):
        """A removed: B's next call finds the tick where it left it and takes over,
        from the silence state, fading in, with no tail."""
        self.pipe.gain = self.pipe.mg = 0
        self.ref4 = reference(self.w, self.trimmed(self.sig[:64]))
        for b in range(min(self.nblk, 4)):
            self.expect(self.PB, self.blocks[b], f"B owner block {b}", self.ref4[16 * b: 16 * b + 16])

    def slot_model_crossfades(self):
        """Another model in User IR slot 3 (Model 3, an integer), whose capture was
        made at 15 dBu: at once a crossfade, the loading block with the tail alone,
        then nam_a2.asm's output for that model on the input x its trim
        (STOMP_DBU - 15 dB), from its silence state fading in as the tail fades out."""
        sim = self.sim
        w2 = [x * (1 + 0.05 * math.sin(i)) for i, x in enumerate(self.w)]
        top = 0x2ABDED + 2 * 0x800
        for k, v in enumerate(ir_samples(w2, dbu=15.0)):
            sim.wr(top - k, v)
        sim.wr(0x2AB56E + 2, 1)
        sim.wr(self.PB + 7, 3)
        self.pipe.cut()
        if self.expect(self.PB, self.blocks[4 % self.nblk], "B to slot 3 (load)", None) == self.zero:
            raise CheckFailed("no tail while the slot-3 model loads")
        # (past the test signal's end the input is 0: nam_a2.asm sees the same)
        sig2 = [ssim.f2b(x) for x in self.sig[:16 * 20]] + [0] * max(0, 16 * 20 - len(self.sig))
        g = input_trim(15.0)
        ref2 = reference(w2, [ssim.b2f(ssim.f2b(ssim.b2f(v) * g)) for v in sig2])
        for b in range(20):
            self.expect(self.PB, sig2[16 * b: 16 * b + 16], f"B slot-3 block {b}", ref2[16 * b: 16 * b + 16])

    def cab_ir_is_silent(self):
        """An ordinary IR in slot 5 (Model 5.0, a float as an older blob sends): the tail
        fades out to silence (the tone stack's own tail after it)."""
        sim = self.sim
        top = 0x2ABDED + 4 * 0x800
        for k in range(2048):
            sim.wr(top - k, ssim.f2b(self.rnd.uniform(-1, 1) * math.exp(-k / 300)))
        sim.wr(0x2AB56E + 4, 1)
        sim.wr(self.PB + 7, ssim.f2b(5.0))
        self.pipe.cut()
        for k in range(20):
            self.expect(self.PB, self.blocks[k % self.nblk], f"B to a cab IR, {k}", None)

    def model_0_is_builtin(self):
        """Model 0 (a model without the parameter): the built-in model again, crossfaded,
        and without the slot-3 model's trim (the built-in one has no level)."""
        self.sim.wr(self.PB + 7, 0)
        self.pipe.cut()
        self.expect(self.PB, self.zero, "B back to built-in (load)", None)
        for b in range(4):
            self.expect(self.PB, self.blocks[b], f"B built-in block {b}", self.ref4[16 * b: 16 * b + 16])


def check(asm, w, nblk, dbu=None):
    k = KernelCheck(asm, w, nblk, dbu)
    try:
        k.run()
    except CheckFailed as e:
        sys.exit(str(e))
    peak = max(abs(ssim.b2f(a)) for a in k.want)
    print(f"nam_lite: {k.code} instructions of code; {k.worst} instructions a block at most (steady) "
          f"= {k.worst / 1500:.1f}% of 150,000 cycles; {k.n} samples, peak {peak:.4f}: {k.n} equal bit for bit; "
          f"registers kept; a second instance passes through and takes over; models from IR slots load, a cab IR "
          f"is silence, Model 0 the built-in one; tone stack as in float32; model changes crossfade with the reversed tail")
    return True


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-") and not a.isdigit()]
    if "-o" in sys.argv:
        args.remove(sys.argv[sys.argv.index("-o") + 1])
    if args:
        w, c = nam_pack.load(args[0], channels=C)
        if c != C:
            sys.exit(f"{args[0]}: {c} channels, NAM Lite has {C}")
        dbu = nam_pack.input_level_dbu(args[0])
    else:
        w, dbu = placeholder(), None
    layers = int(sys.argv[sys.argv.index("--layers") + 1]) if "--layers" in sys.argv else None
    asm, used = build(w, layers, "--meter" in sys.argv, dbu)
    out = sys.argv[sys.argv.index("-o") + 1] if "-o" in sys.argv else None
    if out:
        open(out, "w").write(asm)
        print(f"wrote {out}: " + ", ".join(f"{k} {v:#x}" if isinstance(v, int) else f"{k} {v}" for k, v in used.items()))
    if "--check" in sys.argv and not layers and "--meter" not in sys.argv:
        i = sys.argv.index("--check")
        nblk = int(sys.argv[i + 1]) if i + 1 < len(sys.argv) and sys.argv[i + 1].isdigit() else 6
        if not check(asm, w, nblk, dbu):
            sys.exit("MISMATCH")
        print("NAM LITE MATCHES nam_a2.asm")


if __name__ == "__main__":
    main()
