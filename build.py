#!/usr/bin/env python3
"""Build HX Stomp (or HX Stomp XL) firmware 3.80.0 with NAM A2 Lite, from your own copy of the stock firmware.

usage: python3 build.py <HX_Stomp_v3.80.0_0x103966115.hxf | HX_Stomp_XL_v3.80.0_0x103966115.hxf> [-o out.hxf] [--no-check]

The input is Line 6's own firmware file for your unit, version 3.80.0
(Line 6 Updater keeps a copy; see README.md). Nothing of it is in this
repository: the build reads it, adds NAM A2 Lite and writes a new .hxf
(default build/HX_Stomp_v3.80.0_NAM_A2_Lite.hxf, or ..._XL_... for the XL) for Line 6 Updater.

NAM A2 Lite runs as up to three blocks at once, each playing its own capture
from a User IR slot. The block's title shows the selected IR's name.
Amp > NAM > NAM A2 Lite, four knobs (Model, Polarity, Input, Output). The XL
build has not run on an XL. See STEPS.

Steps:
  1. tools/sharc/nam_multi.py: the SHARC kernel, checked in the simulator
     against src/sharc/nam_a2.asm bit for bit, each block on its own capture
     (--no-check skips it, ~2 min)
  2. tools/patch_amp.py, STEPS[unit]: the model (each block with its own
     SDRAM block), its menu entry and the IR name in the block title
  3. tools/patch_amp.py patch: the kernel into the SHARC boot stream
  4. tools/l6ia_verify.py: every checksum of the result
  5. tools/hxf.py pack: the .hxf
"""
import hashlib
import os
import subprocess
import sys

STOCK_MD5 = {
    "a2cd8f4ae56f49415380270ebc484bf1": "HX_Stomp",       # HX_Stomp_v3.80.0_0x103966115.hxf
    "329e3a26d60d3de1988b6785fa833ee1": "HX_Stomp_XL",    # HX_Stomp_XL_v3.80.0_0x103966115.hxf (untried on a unit)
}
# The kernel and the patch_amp.py steps (tests/test_web_build.py keeps web/firmware-worker.js's copies
# equal), per unit: the same on both. Each step reads the previous one's output: patch_amp.py CMD IN OUT ARGS...
#
# NAM A2 Lite with four knobs (Model, Polarity, Input, Output) in Amp > NAM, on MM4 Frequency Shifter's
# preset ID 461 (that stock model is removed). HX Edit knows that ID, so it keeps NAM blocks when it
# rewrites a preset (it drops blocks of models it doesn't know); the knobs follow MM4's types, so HX
# Edit keeps their values too. The block is an effect: the two-amp rule doesn't count it. No tone
# knobs (the kernel's --no-tone, ~0.5% of the DSP less a block, hence DSP cost 2220, was 2275).
# Presets saved with an earlier NAM build (IDs 147/148) don't open as NAM in this one.
KERNEL = {"HX_Stomp": ["tools/sharc/nam_multi.py", "--no-tone"],
          "HX_Stomp_XL": ["tools/sharc/nam_multi.py", "--no-tone"]}
NAM4 = [
    ["remove-model", "--preset-id", "461"],
    ["add-fx-model", "--knobs", "nam4", "--name", "HD2_DistNAMLite", "--display-name", "NAM A2 Lite",
     "--category", "distortion", "--folder", "NAM", "--preset-id", "461", "--dsp-cost", "2220",
     "--sdram-words", "0x5000", "--dm-words", "0x303", "--pm-words", "0x147"],
    ["move-folder", "--name", "NAM", "--from", "2", "--to", "12"],
    ["ir-title", "--fx-preset-id", "461", "--knob", "0"],
]
STEPS = {"HX_Stomp": NAM4, "HX_Stomp_XL": NAM4}
HERE = os.path.dirname(os.path.abspath(__file__))


def run(*args):
    print("$ " + " ".join(args[1:] if args[0] == sys.executable else args), flush=True)
    r = subprocess.run(list(args), cwd=HERE, capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.returncode:
        sys.stderr.write(r.stderr)
        sys.exit(f"build.py: step failed ({args[1]})")
    return r.stdout


def main():
    argv = sys.argv[1:]
    if not argv or argv[0].startswith("-"):
        sys.exit(__doc__)
    stock = os.path.abspath(argv[0])
    md5 = hashlib.md5(open(stock, "rb").read()).hexdigest()
    if md5 not in STOCK_MD5:
        sys.exit(f"{stock}: MD5 {md5}, not the HX Stomp or HX Stomp XL 3.80.0 firmware. "
                 "The patch is made for those files only.")
    unit = STOCK_MD5[md5]
    print(f"stock firmware: {unit.replace('_', ' ')} 3.80.0")
    out = os.path.abspath(argv[argv.index("-o") + 1]) if "-o" in argv else \
        os.path.join(HERE, "build", f"{unit}_v3.80.0_NAM_A2_Lite.hxf")
    build = os.path.join(HERE, "build")
    os.makedirs(build, exist_ok=True)
    asm = os.path.join(build, "nam_lite.asm")
    image = os.path.join(build, "nam_lite.l6ia")
    py = sys.executable

    run(py, *KERNEL[unit], "-o", asm, *([] if "--no-check" in argv else ["--check"]))
    src = stock
    for k, step in enumerate(STEPS[unit]):
        dst = os.path.join(build, f"nam_lite_{k}.l6ia")
        run(py, "tools/patch_amp.py", step[0], src, dst, *step[1:])
        if src != stock:
            os.remove(src)
        src = dst
    base = src
    run(py, "tools/patch_amp.py", "patch", base, image, "--asm", asm)
    report = run(py, "tools/l6ia_verify.py", image)
    if "ALL OK" not in report:
        sys.exit("build.py: the image failed its checksum check")
    run(py, "tools/hxf.py", "pack", image, out, "--donor", stock)
    os.remove(base)
    print(f"\nDone: {out}\nInstall it with Line 6 Updater (Choose File); see README.md first.")


if __name__ == "__main__":
    main()
