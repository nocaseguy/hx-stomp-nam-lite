# HX Stomp CustomOS

A custom firmware for the Line 6 HX Stomp, built by patching the stock 3.80.0 firmware on your own computer.

This repository is a fork of [nocaseguy/hx-stomp-nam-lite](https://github.com/nocaseguy/hx-stomp-nam-lite), which runs **Neural Amp Modeler (NAM) A2 Lite** captures on the HX Stomp. That work is all still here. CustomOS takes the same approach further, using the tools that taught the HX Stomp a new amp model to implement new functionality across the rest of the firmware. It grows in small steps, and each one is run on a real HX Stomp from RAM before it is kept.

> **Unofficial and experimental.** Not affiliated with, endorsed by or supported by Line 6 or Yamaha Guitar Group. Installing modified firmware is at your own risk and may void your warranty. Read [Install](#install) and [Recovery](#recovery) before you start.

## Where this came from

[hx-stomp-nam-lite](https://github.com/nocaseguy/hx-stomp-nam-lite), by Derek Bui (nocaseguy), did the hard part: it showed the HX Stomp's firmware can be changed safely. It brought a SHARC assembler and simulator, a NAM A2 Lite kernel written from scratch in SHARC assembly, tools that read and rebuild the `.hxf` container and fix every checksum, a loader that runs a build from RAM without installing it, and an in-browser setup page. It also showed that leaving the bootloader alone keeps a bricked HX Stomp recoverable.

CustomOS forks it at upstream commit `2e80164` and builds on those tools. What it adds:

- **New functionality on the Cortex-M4 application** (the HX Stomp's UI and control side), not just the DSP, added as small Thumb-2 code caves that each check the stock bytes they replace.
- **A way for the DSP to talk to the UI.** A DSP routine writes its own values into the unused tail of the frames the DSP already sends the M4, and an M4 hook reads them. This needs no knowledge of Line 6's own message formats.
- **[FIRMWARE_NOTES.md](FIRMWARE_NOTES.md)**, a shared map of what is known about the 3.80.0 firmware: addresses, formats, techniques that work, dead ends, and what is still open. Every claim is marked verified on the unit, verified offline, or a hypothesis.

The built image is `HX_Stomp_v3.80.0_CustomOS.hxf`. NAM A2 Lite is the same amp as upstream's (preset IDs 147 and 148, the same knobs), so presets made with either build open with the other.

## Custom settings

Settings this build adds to the HX Stomp's Global Settings menu (HX Stomp only; the XL build doesn't have them). `tools/patch_menu.py` adds them. Both have run from RAM on an HX Stomp.

**CustomOS** is a seventh section, after Displays (press right past Displays). It has no icon in the section strip, so none is lit while you are in it.

| Setting | Values | What it does |
|---|---|---|
| **Tuner Activation** | **Hold** (default), **Press** | A footswitch assigned TAP/Tunr normally taps the tempo, and holding it opens the tuner. On **Press**, pressing it opens the tuner at once and the tempo is no longer tapped. It follows the assignment, so it works on whichever footswitch has TAP/Tunr. |
| **Lock Tuner Settings** | **Off** (default), **On** | On stops the tuner's settings (Output, Refrnc, Type, Trails, Offsets) from changing: knob turns and the knob presses that reset an item to its default are ignored. Paging between the tuner's settings screens still works. |

Labels in these menus take at most 8 characters before the newline of the stored `Page\nName` and 9 after it; the unit shows the part after the newline first.

## NAM A2 Lite

From upstream, unchanged in this fork. 

## What this repository contains, and what it doesn't

**No Line 6 code or data is in this repository**, and no firmware file is distributed. You need your own copy of the official firmware file. The build reads it on your computer, applies the changes and writes a new `.hxf` for you. Please don't share the built `.hxf`: it is Line 6's firmware with changes, and it isn't yours or ours to redistribute.

What is here is our own work: the patchers and the offsets they patch, the M4 and SHARC code they add, a SHARC assembler and simulator, the NAM A2 Lite kernel, the RAM loader, and the tools that read the firmware container.

**No NAM captures are included.** You bring your own `.nam` files, and their licences are up to their authors.

## Requirements

- An **HX Stomp**. The **HX Stomp XL** builds too, with NAM A2 Lite only (see [HX Stomp XL](#hx-stomp-xl)). Not the Helix Floor, LT or Rack: their firmware is a different design.
- Line 6's firmware 3.80.0 for your unit. The build checks the MD5 and refuses any other file:
  - HX Stomp: `HX_Stomp_v3.80.0_0x103966115.hxf`, MD5 `a2cd8f4ae56f49415380270ebc484bf1`. Download it from [line6.com](https://line6.com/software/readeula.html?rid=12906); you need to sign in with a free Line 6 (Helix) account to get the download.
  - HX Stomp XL: `HX_Stomp_XL_v3.80.0_0x103966115.hxf`, MD5 `329e3a26d60d3de1988b6785fa833ee1`
- Python 3.10 or newer with `numpy`: `pip install numpy`. To run a build from RAM from the command line, also `pyusb` and `dfu-util`.
- **Line 6 Updater** to install, and **HX Edit** to import captures.

## Build

```sh
python3 build.py path/to/HX_Stomp_v3.80.0_0x103966115.hxf
```

This writes `build/HX_Stomp_v3.80.0_CustomOS.hxf` (from the XL's file, `build/HX_Stomp_XL_v3.80.0_CustomOS.hxf`). It takes about 30 seconds. The build:

1. Assembles the NAM kernel and runs it in the SHARC simulator, checking every block's output bit for bit against a reference NAM A2 implementation (`src/sharc/nam_a2.asm`). Add `--no-check` to skip this step.
2. Adds the NAM A2 Lite amp and its Distortion > NAM twin (`tools/patch_amp.py add-model`, `add-fx-model`), and the IR name in the block title (`ir-title`).
3. On the HX Stomp, adds the CustomOS changes to the main application (`tools/patch_menu.py`).
4. Adds the kernel to the DSP's boot code (`patch_amp.py patch`).
5. Recomputes and verifies every checksum: the container MD5, the archive Fletcher-32 and CRC-32, and the image CRCs.

The build is deterministic. The HX Stomp result has MD5 `b96a50f9e36d06067519a7ab2096f07b`, pinned in `tests/test_firmware.py`.

Only 4 of the 15 parts of the firmware change: the main application, the DSP program, the model list and the DSP graph library. **The bootloader is never touched**, which is what keeps [Recovery](#recovery) possible.

## Try it first, from RAM

You can run the built firmware from the HX Stomp's memory for one session before you install it. Nothing is written to the HX Stomp, and turning it off and on brings back what is installed. The HX Stomp must have stock 3.80.0 installed. This is how every CustomOS change is tested.

Close HX Edit, then:

```sh
python3 tools/hxf_ram.py dfu    # or hold Page Right while you power on
dfu-util -d 1fc9:000c -a 0 -D tools/ramboot/firmware-ramboot.dfu
python3 tools/hxf_ram.py run build/HX_Stomp_v3.80.0_CustomOS.hxf --stock HX_Stomp_v3.80.0_0x103966115.hxf
```

The setup page's **Run from RAM** step does the same in Chrome or Edge. Presets and IRs you change during the run are lost at power-off. [RAM_RUN.md](RAM_RUN.md) explains how it works and its limits.

## Install

1. Back up your presets and IRs in HX Edit, then **close HX Edit**.
2. Open Line 6 Updater, choose **Choose File**, and pick `build/HX_Stomp_v3.80.0_CustomOS.hxf` (on an XL, the `_XL_` file; never the other unit's).
3. Let it finish and restart the HX Stomp.

## Recovery

If the HX Stomp stops at the splash screen after an install:

1. Power it off. **Hold Page Right while powering it on.** It comes up in update mode, with the screen dark.
2. In Line 6 Updater, choose **Choose File** and pick the stock `HX_Stomp_v3.80.0_0x103966115.hxf`.

This has been done on a real unit after a modified firmware hung at the splash, and it restored stock 3.80.0. It works because the bootloader is left untouched.

## ~HX Stomp XL~

⛔️⛔️ Untested ⛔️⛔️ 

## How it works

- **The container.** `tools/hxf.py` and `tools/l6ia.py` read and write the `.hxf` container and the L6IA archive inside it, and `tools/l6ia_verify.py` checks every checksum. There is no encryption or signature.
- **The M4 application.** The HX Stomp's UI runs on an NXP LPC4350 (Cortex-M4). Patches add code caves to the application and reach them with branches from the stock code, and every patch checks the stock bytes before it writes. `patch_menu.py` assembles its caves itself.
- **The DSP.** The audio runs on an Analog Devices SHARC ADSP-21469. Kernels are hand-written SHARC assembly, assembled by `tools/sharc/sasm.py` and simulated by `tools/sharc/ssim.py`, with no vendor toolchain. A custom kernel is hooked to an unused DSP primitive.
- **NAM captures through the IR slots.** The HX Stomp already stores up to 128 User IRs of 2,048 samples and hands them to the DSP unchanged. `nam2ir.py` packs a capture's weights into those samples, behind a small header the kernel recognises.
- **The amp.** `tools/patch_amp.py` builds the amp's DSP graph, parameter map and menu entries, copied from the Line 6 Clarity amp with its amp stage replaced by the NAM kernel.

[FIRMWARE_NOTES.md](FIRMWARE_NOTES.md) has the details: addresses, the M4-to-DSP frame format, the Settings and Home screen internals, and the open problems.

## Contributing

Add what you learn to [FIRMWARE_NOTES.md](FIRMWARE_NOTES.md), with its status (verified on unit, verified offline, or hypothesis) and how you found it. Never paste Line 6 code or data there: describe it and give addresses.

Try every change from RAM on a unit before relying on it, and say in the commit what was seen on the unit and what was only checked offline.

## Tests

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -m "not slow and not firmware"   # about 1 s: the model data, the converters, the helpers
.venv/bin/pytest -m slow                          # about 20 s: the kernel in the simulator
HX_STOMP_HXF=path/to/HX_Stomp_v3.80.0_0x103966115.hxf .venv/bin/pytest -m firmware
```

GitHub Actions runs the first two on every push and pull request. The firmware tests need your own stock file (`HX_STOMP_HXF`, `HX_STOMP_XL_HXF`) and are skipped without one. They build the whole `.hxf` and compare its MD5 with the one pinned in `tests/test_firmware.py`, so a changed byte anywhere in the firmware fails until the pin is updated on purpose. `web/firmware-worker.js` carries the same pin.

M4 code (the caves `tools/patch_menu.py` writes, and each feature's `.s` module) is tested by running it in [unicorn](https://www.unicorn-engine.org) as a Cortex-M4, with `tests/m4emu.py`: it assembles a module with the generated `customos.inc` and stands in for firmware functions with Python stubs that log their calls. A call fails if it runs code that is neither loaded nor a stub (a missing stub), doesn't return (a loop), or changes SP or r4-r11. Take the `m4emu` fixture rather than importing the module, so a file's other tests still run without unicorn. `tests/test_customos_m4.py` is the example. `m4emu.assemble()` needs Apple's Command Line Tools clang and skips the test without it, so CI (Ubuntu) skips those.

## Layout

```
build.py                      one-step build from the stock .hxf
FIRMWARE_NOTES.md             what is known about the 3.80.0 firmware
tools/patch_menu.py           CustomOS: Global Settings section and M4 caves (HX Stomp)
tools/patch_amp.py            inspect / add-model / ir-title / patch
tools/nam2ir.py               .nam -> User IR .wav
tools/hxf.py, l6ia.py         .hxf container and L6IA archive
tools/l6ia_verify.py          checks every checksum in an archive
tools/hxf_ram.py              runs a build from RAM (RAM_RUN.md); tools/ramboot/ holds the built loader and hook
tools/sharc/nam_multi.py      the NAM kernel's layout, data and simulator check
tools/sharc/nam_multi_kernel.asm
tools/sharc/nam_lite.py       the model format (converter), test model, shared tables, reference run
tools/sharc/nam_pack.py       .nam loader, layer order
tools/sharc/entry4_blob.py    DSP graph library parser
tools/sharc/sasm.py, ssim.py  SHARC assembler and simulator
src/sharc/nam_a2.asm          reference NAM A2 implementation for the check
src/ramboot/                  the RAM loader and its eMMC overlay hook (C, Cortex-M4; make -C src/ramboot)
web/                          the setup page: build, RAM run and converter in the browser
tests/                        pytest: unit, M4 code in unicorn (m4emu.py), web parity, kernel (slow), firmware (needs a stock .hxf)
```

## Licence

GPL-3.0-or-later; see [LICENSE](LICENSE). Third-party notices and trademarks are listed in [NOTICE](NOTICE). NAM A2 Lite and the tools this fork builds on are © Derek Bui ([hx-stomp-nam-lite](https://github.com/nocaseguy/hx-stomp-nam-lite)).
