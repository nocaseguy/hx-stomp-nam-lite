#!/usr/bin/env python3
"""nam2ir.py - a NAM A2 Lite model (3 channels) as an HX Stomp User IR, for NAM A2 Lite.

usage: nam2ir.py <model.nam> -o model.wav

Writes a 2,048-sample, 48 kHz, mono, 32-bit float .wav. Import it into a User
IR slot (1..128) with HX Edit and set NAM A2 Lite's Model knob to that slot's
number. A .nam holding several sizes (a SlimmableContainer) gives its 3-channel
A2 Lite one. The layout is tools/sharc/nam_lite.py's
ir_samples(): 0.5, -0.5, 3.0, a scale 2^e, 1871 / 1024, 0, 0, 0, then the model's
1,871 weights in the order the kernel loads them, divided by 2^e (exact).

What HX Edit 3.82 does to such a file (as tested): a float
.wav at 48 kHz is sent as it is; it would fade the last 120 samples if the
last were not 0 (it is) and refuses any sample beyond +-15.85 (2^e keeps them
under 15.5). The unit stores and passes the words to the SHARC unchanged, at
boot and on import, for every slot.
"""
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


def main():
    args = [a for a in sys.argv[1:] if a != "-o"]
    if len(sys.argv) < 4 or "-o" not in sys.argv:
        sys.exit(__doc__)
    out = sys.argv[sys.argv.index("-o") + 1]
    src = [a for a in args if a != out][0]
    w, c = nam_pack.load(src, channels=nam_lite.C)
    if c != nam_lite.C:
        sys.exit(f"{src}: {c} channels; NAM A2 Lite takes the 3-channel A2 Lite model")
    words = nam_lite.ir_samples(w)
    write_wav(out, words)
    scale = struct.unpack("<f", struct.pack("<I", words[3]))[0]
    print(f"wrote {out}: 2048 samples, 48 kHz float, 1,871 weights (scale {scale:g}); "
          f"HX Edit: import into a User IR slot, then set NAM A2 Lite's Model knob to that slot")


if __name__ == "__main__":
    main()
