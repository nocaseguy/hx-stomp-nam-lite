#!/usr/bin/env python3
"""nam2ir.py - a NAM A2 Lite model (3 channels) as an HX Stomp User IR, for NAM A2 Lite.

usage: nam2ir.py <model.nam> -o model.wav [--no-level]

A capture that gives its interface's level (metadata input_level_dbu, the dBu
at 0 dBFS) has it in IR word 5 (nam_lite.level_word); the kernel then trims
its input by STOMP_DBU - input_level_dbu (nam_lite.py), so that at Drive 5.0
the Stomp's input meets the model as the capture's interface did. --no-level
leaves word 5 at 0 (no trim).

Writes a 2,048-sample, 48 kHz, mono, 32-bit float .wav. Import it into a User
IR slot (1..128) with HX Edit and set NAM A2 Lite's Model knob to that slot's
number. A .nam holding several sizes (a SlimmableContainer) gives its 3-channel
A2 Lite one. web/index.html does the same in a browser.

The layout is tools/sharc/nam_lite.py's
ir_samples(): 0.5, -0.5, 3.0, a scale 2^e, 1871 / 1024, 0, 0, 0, then the model's
1,871 weights in the order the kernel loads them, then its silence state (72
words, each / 16: what the rings hold after silence, so a change of model does
not pop), all divided by 2^e (exact). A file made before the silence state has
zeros there and still loads (its rings start at 0).

What HX Edit 3.82 does to such a file (as tested): a float
.wav at 48 kHz is sent as it is; it would fade the last 120 samples if the
last were not 0 (it is) and refuses any sample beyond +-15.85 (2^e keeps them
under 15.5). The unit stores and passes the words to the SHARC unchanged, at
boot and on import, for every slot.
"""
import json
import os
import struct
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "sharc"))
import nam_lite   # noqa: E402
import nam_pack   # noqa: E402


def write_wav(path, words, rate=48000):
    data = struct.pack("<%dI" % len(words), *words)
    fmt = struct.pack("<4sIHHIIHH", b"fmt ", 16, 3, 1, rate, rate * 4, 4, 32)
    body = b"WAVE" + fmt + struct.pack("<4sI", b"data", len(data)) + data
    with open(path, "wb") as f:
        f.write(struct.pack("<4sI", b"RIFF", len(body)) + body)


def problems(src):
    """What would make the kernel compute something else than the capture in
    `src` (a .nam): web/nam2ir-core.js problems(), on the model nam_pack.load picks."""
    if not src.endswith(".nam"):
        return []
    d = json.load(open(src))
    subs = [s["model"] for s in d["config"]["submodels"]] if d.get("architecture") == "SlimmableContainer" else [d]
    m = next(m for m in subs if m.get("architecture") == "WaveNet" and m["config"]["layers"][0]["channels"] == nam_lite.C)
    out = []
    layers = m["config"]["layers"]
    if len(layers) != 1:
        out.append(f"{len(layers)} layer arrays; A2 Lite has 1")
    lc = layers[0]
    if "kernel_sizes" in lc and lc["kernel_sizes"] != nam_pack.KERNEL:
        out.append("kernel sizes differ from A2's")
    if "dilations" in lc and lc["dilations"] != nam_pack.DILATION:
        out.append("dilations differ from A2's")
    for i, a in enumerate(lc.get("activation") or []):
        if a and (a.get("type") != "LeakyReLU" or a.get("negative_slope") != 0.01):
            out.append(f"layer {i + 1} uses {a.get('type')}; the kernel has LeakyReLU 0.01")
    for i, g in enumerate(lc.get("gating_mode") or []):
        if g and g != "none":
            out.append(f"layer {i + 1} is gated")
    if len(m["weights"]) != 1871:
        out.append(f"{len(m['weights'])} weights; A2 Lite has 1871")
    rate = m.get("sample_rate") or d.get("sample_rate")
    if rate and rate != 48000:
        print(f"warning: trained at {rate:g} Hz; the Stomp runs at 48 kHz, so it will sound off", file=sys.stderr)
    return out


def main():
    argv = sys.argv[1:]
    if len(argv) < 3 or "-o" not in argv:
        sys.exit(__doc__)
    out = argv.pop(argv.index("-o") + 1)
    src = [a for a in argv if a not in ("-o", "--no-level")][0]
    w, c = nam_pack.load(src, channels=nam_lite.C)
    if c != nam_lite.C:
        sys.exit(f"{src}: {c} channels; NAM A2 Lite takes the 3-channel A2 Lite model")
    bad = problems(src)
    if bad:
        sys.exit(f"{src}: not an A2 Lite capture the kernel can run: " + "; ".join(bad))
    dbu = None if "--no-level" in argv else nam_pack.input_level_dbu(src)
    try:
        words = nam_lite.ir_samples(w, dbu)
    except ValueError as e:
        sys.exit(f"{src}: {e}")
    write_wav(out, words)
    scale = struct.unpack("<f", struct.pack("<I", words[3]))[0]
    print(f"input level {dbu:g} dBu: trimmed {nam_lite.STOMP_DBU - dbu:+.1f} dB on the Stomp "
          f"({nam_lite.STOMP_DBU:g} dBu at 0 dBFS)" if dbu is not None
          else "input level none: the capture gives no input_level_dbu" if "--no-level" not in argv
          else "input level left out (--no-level)")
    print(f"wrote {out}: 2048 samples, 48 kHz float, 1,871 weights (scale {scale:g}); "
          f"HX Edit: import into a User IR slot, then set NAM A2 Lite's Model knob to that slot")


if __name__ == "__main__":
    main()
