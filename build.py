#!/usr/bin/env python3
"""Build HX Stomp (or HX Stomp XL) firmware 3.80.0 with NAM A2 Lite, from your own copy of the stock firmware.

usage: python3 build.py <HX_Stomp_v3.80.0_0x103966115.hxf | HX_Stomp_XL_v3.80.0_0x103966115.hxf> [-o out.hxf] [--no-check]
                        [--splash picture [--splash-fit fill|fit]] [--splash-text "text" [--splash-glyph EMOJI=picture ...]]

The input is Line 6's own firmware file for your unit, version 3.80.0
(Line 6 Updater keeps a copy; see README.md). Nothing of it is in this
repository: the build reads it, adds NAM A2 Lite and writes a new .hxf
(default build/HX_Stomp_v3.80.0_CustomOS.hxf, or ..._XL_... for the XL) for Line 6 Updater.

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
     (HX Stomp only, first: tools/patch_menu.py, the CustomOS features of tools/features; --splash, --splash-fit,
     --splash-text and --splash-glyph are the splash feature's HX_SPLASH, HX_SPLASH_FIT, HX_SPLASH_TEXT and HX_SPLASH_GLYPHS;
     with HX_CLICK=1, then tools/patch_click.py: the Metronome block)
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
         "--folder", "NAM", "--preset-id", "147", "--dsp-cost", "2345", "--sdram-words", "0x5000"]
# A third NAM block: the same kernel as a mono effect under Distortion > NAM (a preset
# holds two amps). Preset ID 148 is fixed for ever, as 147.
FX_MODEL = ["--name", "HD2_DistNAMLite", "--display-name", "NAM A2 Lite", "--category", "distortion",
            "--folder", "NAM", "--preset-id", "148", "--dsp-cost", "2345", "--sdram-words", "0x5000"]
# ir-title per unit.
IR_TITLE = {"HX_Stomp": ["--preset-id", "147", "--fx-preset-id", "148"],
            "HX_Stomp_XL": ["--preset-id", "147", "--fx-preset-id", "148"]}
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
    splash = os.path.abspath(argv[argv.index("--splash") + 1]) if "--splash" in argv else None
    splash_text = argv[argv.index("--splash-text") + 1] if "--splash-text" in argv else None
    splash_fit = argv[argv.index("--splash-fit") + 1] if "--splash-fit" in argv else "fill"
    if (splash or splash_text) and unit != "HX_Stomp":
        sys.exit("build.py: --splash and --splash-text are for the HX Stomp only")
    if splash:
        os.environ.update(HX_SPLASH=splash, HX_SPLASH_FIT=splash_fit)
    if splash_text:
        os.environ["HX_SPLASH_TEXT"] = splash_text
    glyphs = [argv[i + 1].split("=", 1) for i, a in enumerate(argv) if a == "--splash-glyph"]
    if any(len(g) != 2 for g in glyphs):
        sys.exit("build.py: --splash-glyph takes EMOJI=picture")
    if glyphs:
        os.environ["HX_SPLASH_GLYPHS"] = ",".join(f"{e}={os.path.abspath(path)}" for e, path in glyphs)
    out = os.path.abspath(argv[argv.index("-o") + 1]) if "-o" in argv else \
        os.path.join(HERE, "build", f"{unit}_v3.80.0_CustomOS.hxf")
    build = os.path.join(HERE, "build")
    os.makedirs(build, exist_ok=True)
    asm = os.path.join(build, "nam_lite.asm")
    base = os.path.join(build, "nam_lite_base.l6ia")
    titled = os.path.join(build, "nam_lite_title.l6ia")
    image = os.path.join(build, "nam_lite.l6ia")
    py = sys.executable

    if os.environ.get("HX_FRAMEPROBE"):
        asm = os.path.join(HERE, "src", "sharc", "frame_probe.asm")
    else:
        run(py, KERNEL, "-o", asm, *([] if "--no-check" in argv else ["--check"]))
    run(py, "tools/patch_amp.py", "add-model", stock, base, *MODEL)
    run(py, "tools/patch_amp.py", "add-fx-model", base, titled, *FX_MODEL)
    os.replace(titled, base)
    run(py, "tools/patch_amp.py", "ir-title", base, titled, *IR_TITLE[unit])
    os.replace(titled, base)
    if unit == "HX_Stomp":
        run(py, "tools/patch_menu.py", base, titled, "--cwd", os.getcwd())
        os.replace(titled, base)
    wrap = ["--wrap-prim", "0x271a:0x8d9c9", "--wrap-prim", "0x2719:0x8d342",
                                  "--wrap-prim", "0x2710:0x8d342"] if os.environ.get("HX_FRAMEPROBE") else []
    run(py, "tools/patch_amp.py", "patch", base, image, "--asm", asm, *wrap)
    if os.environ.get("HX_CLICK") and unit == "HX_Stomp":
        run(py, "tools/patch_click.py", image, titled)
        os.replace(titled, image)
    if os.environ.get("HX_GR") and unit == "HX_Stomp":
        # last: every step that adds a model rebuilds the Entry 3 and 4 tails the knobs live in
        run(py, "tools/patch_comp.py", image, titled)
        os.replace(titled, image)
    report = run(py, "tools/l6ia_verify.py", image)
    if "ALL OK" not in report:
        sys.exit("build.py: the image failed its checksum check")
    run(py, "tools/hxf.py", "pack", image, out, "--donor", stock)
    os.remove(base)
    print(f"\nDone: {out}\nInstall it with Line 6 Updater (Choose File); see README.md first.")


if __name__ == "__main__":
    main()
