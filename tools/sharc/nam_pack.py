#!/usr/bin/env python3
"""Lay a NAM A2 model out for src/sharc/nam_a2.asm.

usage: nam_pack.py <model.nam | weights.h> [--channels 3|8] [--base 0xc0100] [-o blob.bin]

pack(weights, channels, base) returns the 32-bit words of the model block
nam_a2.asm reads at `base`: header, layer table, weights in the order the
kernel reads them, then the zeroed rings; tools/sharc/nam_lite.py uses its
loader and layer order.
"""
import json
import math
import re
import struct
import sys

KERNEL = [6] * 14 + [15, 15] + [6] * 7
DILATION = [1, 3, 7, 17, 41, 101, 239] * 2 + [1, 13] + [1, 3, 7, 17, 41, 101, 239]
HEAD_TAPS = 16


def f2b(x):
    return struct.unpack("<I", struct.pack("<f", x))[0]


def load(path, channels=3):
    """Weight stream of a .nam file, or of a C header of the weights
    (`{...}` and a NAM_CHANNELS / *_CHANNELS define)."""
    text = open(path).read()
    if path.endswith(".h"):
        body = text[text.index("{") + 1: text.rindex("}")]
        w = [float(x.rstrip("f")) for x in re.findall(r"-?\d[\d.eE+-]*f?", body)]
        return w, int(re.search(r"_CHANNELS (\d+)", text).group(1))
    d = json.loads(text)
    subs = [s["model"] for s in d["config"]["submodels"]] if d.get("architecture") == "SlimmableContainer" else [d]
    for m in subs:
        if m.get("architecture") == "WaveNet" and m["config"]["layers"][0]["channels"] == channels:
            for x in (d, m):
                rate = x.get("sample_rate")
                if rate is not None and rate != SAMPLE_RATE:
                    raise SystemExit(f"{path}: a {rate:g} Hz capture; the HX Stomp runs at 48 kHz "
                                     "and does not resample (it would play with its response shifted)")
            why = a2_mismatch(m["config"], channels)
            if why:
                raise SystemExit(f"{path}: not an A2 model ({why})")
            return m["weights"], channels
    raise SystemExit(f"no {channels}-channel WaveNet in {path}")


SAMPLE_RATE = 48000      # no sample_rate in a file: NAM's default, 48 kHz


def a2_mismatch(config, channels):
    """None when a WaveNet config is the A2 shape the kernels compute, else what differs:
    NeuralAmpModelerCore's is_a2_shape (NAM/wavenet/a2_fast.cpp) rule for rule. The weight
    count alone would pass a model with another activation, dilation order or a FiLM."""
    layers = config.get("layers")
    if not isinstance(layers, list) or len(layers) != 1:
        return "one layer array"
    if config.get("head") is not None or config.get("condition_dsp") is not None:
        return "a post-stack head or a condition DSP"
    if not isinstance(config.get("head_scale"), (int, float)) or config.get("in_channels", 1) != 1:
        return "head_scale, in_channels 1"
    la = layers[0]
    if la.get("input_size") != 1 or la.get("condition_size") != 1:
        return "input_size and condition_size 1"
    if la.get("channels") != channels or la.get("bottleneck") != channels:
        return f"channels and bottleneck {channels}"
    if la.get("kernel_sizes") != KERNEL or la.get("dilations") != DILATION:
        return "A2's kernel sizes and dilations"
    act = la.get("activation")
    if (not isinstance(act, list) or len(act) != len(KERNEL)
            or any(not isinstance(a, dict) or a.get("type") != "LeakyReLU"
                   or abs(a.get("negative_slope", 0.0) - 0.01) > 1e-7 for a in act)):
        return "LeakyReLU(0.01) in every layer"
    gm, sa = la.get("gating_mode"), la.get("secondary_activation")
    if gm is not None and (gm != ["none"] * len(KERNEL)) or la.get("gated") is True:
        return "no gating"
    if sa is not None and sa != [None] * len(KERNEL):
        return "no secondary activation"
    if isinstance(la.get("head1x1"), dict) and la["head1x1"].get("active", False):
        return "head1x1 off"
    l1 = la.get("layer1x1")
    if not isinstance(l1, dict) or not l1.get("active", False) or l1.get("groups", 1) != 1:
        return "layer1x1 on, groups 1"
    h = la.get("head")
    if (not isinstance(h, dict) or h.get("out_channels") != 1 or h.get("kernel_size") != HEAD_TAPS
            or h.get("head_dilation", 1) != 1 or not h.get("bias", False)):
        return f"a {HEAD_TAPS}-tap head with a bias"
    for k in ("conv_pre_film", "conv_post_film", "input_mixin_pre_film", "input_mixin_post_film",
              "activation_pre_film", "activation_post_film", "layer1x1_post_film", "head1x1_post_film"):
        v = la.get(k)
        if not (v is None or v is False or isinstance(v, dict) and not v.get("active", False)):
            return f"no FiLM ({k})"
    if la.get("groups_input", 1) != 1 or la.get("groups_input_mixin", 1) != 1:
        return "no grouped convolutions"
    if la.get("slimmable") is not None:
        return "not slimmable"
    return None


def loudness(path):
    """The capture's loudness in dB (metadata loudness, NAM's measure of the model's output on
    its standard signal) of a .nam file; None when it does not give a number (or for a .h)."""
    if path.endswith(".h"):
        return None
    x = (json.loads(open(path).read()).get("metadata") or {}).get("loudness")
    ok = isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
    return float(x) if ok else None



def input_level_dbu(path):
    """The capture's input level in dBu (its interface's dBu at 0 dBFS, metadata
    input_level_dbu) of a .nam file, or None when it does not give a number (as
    web/nam2ir-core.js)."""
    if not path.endswith(".nam"):
        return None
    dbu = (json.load(open(path)).get("metadata") or {}).get("input_level_dbu")
    ok = isinstance(dbu, (int, float)) and not isinstance(dbu, bool) and math.isfinite(dbu)
    return float(dbu) if ok else None

def _layers(w, c, simd):
    """Weight stream -> (per-layer blocks in the kernel's order, head, head bias, scale)."""
    expect = c + sum(c * c * k + c + c + c * c + c for k in KERNEL) + c * HEAD_TAPS + 2
    if len(w) != expect:
        raise SystemExit(f"{len(w)} weights, an A2 model with {c} channels has {expect}")
    if simd and c & 1:
        raise SystemExit("the SIMD layout needs an even channel count")
    o = c                                             # stream offset, after the rechannel weights
    blocks, pres = [], []
    for k in KERNEL:
        conv, o = o, o + c * c * k
        bias, o = o, o + c
        mixin, o = o, o + c
        w1, o = o, o + c * c
        b1, o = o, o + c
        rows = [[w[conv + (i * c + j) * k + t] for t in range(k) for j in range(c)] for i in range(c)]
        res = [[w[w1 + i * c + j] for j in range(c)] for i in range(c)]
        blk, pre = [], []
        if simd:                                      # channel pairs interleaved, a spare pair after
            for i in range(0, c, 2):                  # each convolution row; mix-in and bias apart
                for u, v in zip(rows[i] + [0.0], rows[i + 1] + [0.0]):
                    blk += [u, v]
                pre += [w[mixin + i], w[mixin + i + 1], w[bias + i], w[bias + i + 1]]
            for i in range(0, c, 2):
                for u, v in zip(res[i] + [w[b1 + i]], res[i + 1] + [w[b1 + i + 1]]):
                    blk += [u, v]
        else:
            for i in range(c):
                blk += [w[bias + i], w[mixin + i]] + rows[i]
            for i in range(c):
                blk += [w[b1 + i]] + res[i]
        blocks.append(blk)
        pres.append(pre)
    head = [w[o + j * HEAD_TAPS + t] for t in range(HEAD_TAPS) for j in range(c)]
    return (blocks, pres) if simd else blocks, head, w[o + c * HEAD_TAPS], w[o + c * HEAD_TAPS + 1]


def pack(w, c, base):
    """Model block words for nam_a2.asm: one run of memory at `base`."""
    n = len(KERNEL)
    blocks, head, hbias, scale = _layers(w, c, False)
    head = [hbias] + head
    a_table = base + 9
    a_rech = a_table + 7 * n
    a_head = a_rech + c
    a_w = a_head + len(head)
    a_ring = a_w + sum(len(b) for b in blocks)
    table, words = [], []
    ring = a_ring + HEAD_TAPS * c                     # head ring first, then the layers'
    for k, d, blk in zip(KERNEL, DILATION, blocks):
        ln = ((k - 1) * d + 1) * c
        table += [ring, ln, ring, (d - 1) * c, k, k * c, a_w + len(words)]
        words += blk
        ring += ln
    out = [c, n, a_table, a_rech, a_head, f2b(scale), a_ring, HEAD_TAPS * c, a_ring]
    out += table + [f2b(v) for v in w[:c]] + [f2b(v) for v in head] + [f2b(v) for v in words]
    return out + [0] * (ring - a_ring)


def main():
    a = sys.argv[1:]
    opt = {}
    for flag in ("--channels", "--base", "-o"):
        if flag in a:
            i = a.index(flag)
            opt[flag] = a[i + 1]
            del a[i:i + 2]
    if len(a) != 1:
        sys.exit(__doc__)
    w, c = load(a[0], int(opt.get("--channels", 3)))
    blob = pack(w, c, int(opt.get("--base", "0xc0100"), 0))
    if "-o" in opt:
        open(opt["-o"], "wb").write(struct.pack("<%dI" % len(blob), *blob))
    print(f"{c} channels, {len(w)} weights -> {len(blob)} words ({len(blob) - len(w)} of them state and tables)")


if __name__ == "__main__":
    main()
