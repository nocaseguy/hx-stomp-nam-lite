#!/usr/bin/env python3
"""Build HX Stomp (or HX Stomp XL) firmware 3.80.0 with NAM A2 Lite, from your own copy of the stock firmware.

usage: python3 build.py <HX_Stomp_v3.80.0_0x103966115.hxf | HX_Stomp_XL_v3.80.0_0x103966115.hxf> [-o out.hxf] [--no-check]

The input is Line 6's own firmware file for your unit, version 3.80.0
(Line 6 Updater keeps a copy; see README.md). Nothing of it is in this
repository: the build reads it, adds NAM A2 Lite and writes a new .hxf
(default build/HX_Stomp_v3.80.0_NAM_A2_Lite.hxf, or ..._XL_... for the XL) for Line 6 Updater.

NAM A2 Lite runs as up to three blocks at once (at most two per preset, as any
amp), each playing its own capture from a User IR slot. The block's title
shows the selected IR's name. (The XL build has not run on an XL.)

Steps:
  1. tools/sharc/nam_multi.py: the SHARC kernel, checked in the simulator
     against src/sharc/nam_a2.asm bit for bit, each block on its own capture
     (--no-check skips it, ~10 s)
  2. tools/patch_amp.py add-model: the "NAM A2 Lite" amp in Amp > NAM, each
     block with its own SDRAM block
  3. tools/patch_amp.py ir-title: the IR name in the block title
  4. tools/patch_amp.py patch: the kernel into the SHARC boot stream
  5. tools/l6ia_verify.py: every checksum of the result
  6. tools/hxf.py pack: the .hxf
"""
import hashlib
import os
import subprocess
import sys

STOCK_MD5 = {
    "a2cd8f4ae56f49415380270ebc484bf1": "HX_Stomp",       # HX_Stomp_v3.80.0_0x103966115.hxf
    "329e3a26d60d3de1988b6785fa833ee1": "HX_Stomp_XL",    # HX_Stomp_XL_v3.80.0_0x103966115.hxf (untried on a unit)
}
# The kernel and the amp (tests/test_web_build.py keeps web/firmware-worker.js's copies
# equal). Preset ID 147 and the knobs are those of every NAM A2 Lite build, so presets
# saved with an earlier one open with this one.
KERNEL = "tools/sharc/nam_multi.py"
MODEL = ["--clone", "HD2_AmpLine6Clarity", "--name", "HD2_AmpNAMLite", "--display-name", "NAM A2 Lite",
         "--folder", "NAM", "--preset-id", "147", "--dsp-cost", "2380", "--sdram-words", "0x5000"]
# A third NAM block: the same kernel as a mono effect under Distortion > NAM (a preset
# holds two amps). Preset ID 148 is fixed for ever, as 147.
FX_MODEL = ["--name", "HD2_DistNAMLite", "--display-name", "NAM A2 Lite", "--category", "distortion",
            "--folder", "NAM", "--preset-id", "148", "--dsp-cost", "2380", "--sdram-words", "0x5000"]
# ir-title per unit.
IR_TITLE = {"HX_Stomp": ["--preset-id", "147", "--preset-id", "148"],
            "HX_Stomp_XL": ["--preset-id", "147", "--preset-id", "148"]}
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
    base = os.path.join(build, "nam_lite_base.l6ia")
    titled = os.path.join(build, "nam_lite_title.l6ia")
    image = os.path.join(build, "nam_lite.l6ia")
    py = sys.executable

    run(py, KERNEL, "-o", asm, *([] if "--no-check" in argv else ["--check"]))
    run(py, "tools/patch_amp.py", "add-model", stock, base, *MODEL)
    run(py, "tools/patch_amp.py", "add-fx-model", base, titled, *FX_MODEL)
    os.replace(titled, base)
    run(py, "tools/patch_amp.py", "ir-title", base, titled, *IR_TITLE[unit])
    os.replace(titled, base)
    run(py, "tools/patch_amp.py", "patch", base, image, "--asm", asm)
    report = run(py, "tools/l6ia_verify.py", image)
    if "ALL OK" not in report:
        sys.exit("build.py: the image failed its checksum check")
    run(py, "tools/hxf.py", "pack", image, out, "--donor", stock)
    os.remove(base)
    print(f"\nDone: {out}\nInstall it with Line 6 Updater (Choose File); see README.md first.")


if __name__ == "__main__":
    main()
