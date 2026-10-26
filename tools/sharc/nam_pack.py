#!/usr/bin/env python3
"""Lay a NAM A2 model out for src/sharc/nam_a2.asm.

usage: nam_pack.py <model.nam | weights.h> [--channels 3|8] [--base 0xc0100] [-o blob.bin]

pack(weights, channels, base) returns the 32-bit words of the model block
nam_a2.asm reads at `base`: header, layer table, weights in the order the
kernel reads them, then the zeroed rings; tools/sharc/nam_lite.py uses its
loader and layer order.
"""
import json
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
            return m["weights"], channels
    raise SystemExit(f"no {channels}-channel WaveNet in {path}")


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
