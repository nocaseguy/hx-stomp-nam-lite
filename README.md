# NAM A2 Lite for the HX Stomp

This repository adds **Neural Amp Modeler (NAM) A2 Lite** to the stock Line 6 HX Stomp firmware, version 3.80.0, as a new amp model. NAM captures then run on the Stomp's own DSP, like any other amp block.

**Not a programmer? Use the setup page: [nocaseguy.github.io/hx-stomp-nam-lite/web/](https://nocaseguy.github.io/hx-stomp-nam-lite/web/).** It builds the firmware from your own Line 6 file, converts your captures and guides you through every step, all in your browser, with nothing to install and nothing uploaded. See [The setup page](#the-setup-page-no-install).

## Demo

[![NAM A2 Lite running on an HX Stomp (YouTube)](https://img.youtube.com/vi/zQzj0qahJ6E/hqdefault.jpg)](https://www.youtube.com/watch?v=zQzj0qahJ6E)

Watch it on YouTube: https://www.youtube.com/watch?v=zQzj0qahJ6E

> **Unofficial and experimental.** Not affiliated with, endorsed by or supported by Line 6 or Yamaha Guitar Group. Installing modified firmware is at your own risk and may void your warranty. Read [Install](#install) and [Recovery](#recovery) before you start.

## What's new

- **HX Edit keeps NAM blocks.** With the earlier builds, some edits in HX Edit (dragging a block when the chain has gaps, for example) made NAM blocks vanish. HX Edit has its own list of models and doesn't know NAM's, and when it rewrites the whole preset it leaves out the blocks it doesn't know. On the HX Stomp, NAM A2 Lite now takes the place of a stock model HX Edit knows (MM4 Frequency Shifter), with its knobs laid out like that model's, so HX Edit keeps the blocks and their settings. HX Edit shows the block as "MM4 Frequency Shifter".
- **Four knobs: Model, Polarity, Input, Output** (HX Stomp). The tone stack is gone; the Model knob steps one slot a click.
- **All NAM blocks count as effects** (HX Stomp): the Stomp's two-amp limit doesn't apply to them, so a preset can hold three NAM blocks and two stock amps.
- **Input level trim.** A capture that records its interface's input level plays at the level it was captured at (see [Use](#use)).
- **The capture's name in the block title.** The edit screen shows the name of the User IR the Model knob selects, as it does for an IR block.

**Presets saved with an earlier NAM build don't open NAM A2 Lite in this one** (HX Stomp): NAM now has another preset ID. Re-add the block from Amp → NAM in those presets. The **HX Stomp XL** build keeps the earlier layout (Amp → NAM with eight knobs, and Distortion → NAM), so its presets are unaffected.

## What you get

- **NAM A2 Lite** in the menu under **Amp → NAM**, with four knobs (HX Stomp):

  | Knob | What it does |
  |---|---|
  | **Model** | Which capture plays: 1–128 is the User IR slot that holds it. A slot holding anything else (a cab IR, or nothing) is silent, and so is any number above 128 (the title then reads `<EMPTY>`). One slot a click. |
  | **Polarity** | Normal or Inverted. Inverted flips the output's polarity (phase), exactly. |
  | **Input** | Input gain into the capture, −20 to +20 dB; 0 dB (the capture's own level) at 5.0 |
  | **Output** | Output level; 0 dB at 5.0, +12 dB at 10 |

  The **HX Stomp XL** build has the earlier eight knobs: Model, Input, Bass, Mid, Treble, Presence (a tone stack, ±12 dB, flat at 5.0), Ch Vol and Polarity.

- **A converter** (on the [setup page](https://nocaseguy.github.io/hx-stomp-nam-lite/web/), or `tools/nam2ir.py`) turns a `.nam` file into a `.wav`. HX Edit imports that `.wav` as a User IR. The "IR" is not a sound: it carries the capture's 1,871 weights, and the amp loads them from the slot.

- Up to three NAM A2 Lite blocks at once, each with its own capture (HX Stomp: all from Amp > NAM; XL: two from Amp > NAM, the third from Distortion > NAM).
- The block's title on the edit screen shows the name of the IR in the selected slot (the knob itself shows the number).

Everything else in the firmware stays stock 3.80.0, except that the HX Stomp build removes **MM4 Frequency Shifter** (a Legacy modulation) to give NAM its place. No factory preset uses it; a preset of yours that does would open NAM A2 Lite in its place.

## What this repository contains, and what it doesn't

**No Line 6 code or data is in this repository**, and no firmware file is distributed. You need your own copy of the official firmware file. The build reads it on your computer, applies the changes and writes a new `.hxf` for you. Please don't share the built `.hxf`: it is Line 6's firmware with changes, and it isn't yours or ours to redistribute.

What is here is our own work:
- a SHARC assembler and simulator;
- the NAM A2 Lite kernel, written from scratch in SHARC assembly;
- a RAM loader that runs a build without installing it (C for the Stomp's Cortex-M4, and WebUSB for the page);
- tools that read the firmware container and patch the model tables;
- the offsets they patch.

**No NAM captures are included.** You bring your own `.nam` files, and their licences are up to their authors.

## Requirements

- An **HX Stomp**, or an **HX Stomp XL** (see [HX Stomp XL](#hx-stomp-xl): the current build has not run on an XL yet; an earlier one-block build ran from RAM). Not the Helix Floor, LT or Rack: their firmware is a different design.
- Line 6's firmware 3.80.0 for your unit. The build checks the MD5 and refuses any other file:
  - HX Stomp: `HX_Stomp_v3.80.0_0x103966115.hxf`, MD5 `a2cd8f4ae56f49415380270ebc484bf1`
  - HX Stomp XL: `HX_Stomp_XL_v3.80.0_0x103966115.hxf`, MD5 `329e3a26d60d3de1988b6785fa833ee1`
- Python 3.10 or newer with `numpy`: `pip install numpy`.
- **Line 6 Updater** to install, and **HX Edit** to import captures.
- 3-channel **A2 Lite** captures. A `.nam` with several sizes in one file (a SlimmableContainer) works too: its A2 Lite model is used.

## The setup page (no install)

**[NAM A2 Lite Setup](https://nocaseguy.github.io/hx-stomp-nam-lite/web/)** walks you through everything below in your browser: it builds the firmware from your stock `.hxf`, tells you how to install it, converts your `.nam` captures and shows how to load them. Nothing is uploaded: the page runs this repository's own Python tools in the browser (with [Pyodide](https://pyodide.org)), the same commands as `build.py` without the simulator check, and then compares the result with the tested build's MD5 (the one pinned in `tests/test_firmware.py`). It says **Verified** only when every byte matches.

The page is `web/index.html`; GitHub Pages publishes it with `tools/` (`.github/workflows/pages.yml`). The build step needs the page served over http, so to run it from a copy of the repository: `python3 -m http.server`, then open `http://localhost:8000/web/`. The capture converter also works from the file itself.

## Build

```sh
python3 build.py path/to/HX_Stomp_v3.80.0_0x103966115.hxf
```

This writes `build/HX_Stomp_v3.80.0_NAM_A2_Lite.hxf` (from the XL's file, `build/HX_Stomp_XL_v3.80.0_NAM_A2_Lite.hxf`). It takes about 2 minutes, most of it the simulator check. The build:

1. Assembles the kernel and runs it in the SHARC simulator. Each block's output must match a reference NAM A2 implementation (`src/sharc/nam_a2.asm`) bit for bit, on its own capture and input trim; the check also covers the tone stack (on the HX Stomp, `--no-tone`: the stack kept a pass-through), the crossfades, model changes, a fourth block, and the DMA that fetches the long rings and its failure path. Add `--no-check` to skip this step.
2. Adds NAM A2 Lite (`STEPS` in `build.py`). On the HX Stomp:
   - removes MM4 Frequency Shifter from the model and menu tables, freeing its preset ID 461 (`remove-model`);
   - adds NAM A2 Lite there as an effect: a DSP graph that runs the NAM kernel, its four knobs in MM4's order and value types, and each block its own DDR2 block (`add-fx-model --knobs nam4`);
   - lists it in a new **NAM** folder under Amp (`move-folder`);
   - makes the block's title show the selected IR's name, read from the Model knob (`ir-title --knob 0`).

   On the XL, as before: the amp (a copy of the Line 6 Clarity's DSP graph with the NAM kernel as its amp stage, eight knobs, Amp → NAM), the same as an effect under Distortion → NAM, and the IR-name title, with the XL's own addresses.
3. Enlarges the DSP's graph buffer to fit the extra graph (part of the steps above).
4. Adds the kernel to the DSP's boot code and hooks it to an unused DSP primitive.
5. Recomputes and verifies every checksum: the container MD5, the archive Fletcher-32 and CRC-32, and the image CRCs.

The HX Stomp result has MD5 `63d1392cf35d4833907b171e6d1d3e68` (pinned in `tests/test_firmware.py`). That exact file ran on an HX Stomp from RAM and passed the project's on-device test suite (three blocks, the DSP limits, every stock effect category beside NAM) and a check of the menu, knobs, title and sound by hand. The same layout listed under Distortion passed the HX Edit tests (its drags and whole-preset writes kept the NAM blocks and their settings) and played a fixed test signal at the same level as the earlier build, to 0.1 dB. The XL result, `3c859c455721ac02e451610a56798392`, is unchanged from the earlier release.

Only 4 of the 15 parts of the firmware change: the main application (its model tables and the title code), the DSP program, the model list and the DSP graph library. **The bootloader is never touched**, which is what keeps [Recovery](#recovery) possible.

## Try it first, from RAM

You can run the built firmware from the Stomp's memory for one session before you install it. Nothing is written to the Stomp, and turning it off and on brings back what is installed. The Stomp must have stock 3.80.0 installed.

- **On the setup page:** step 3, **Run from RAM**, in Chrome or Edge. The browser asks you to pick a device three times as the Stomp restarts.
- **From the command line:** hold Page Right while you power on, then
  ```sh
  dfu-util -d 1fc9:000c -a 0 -D tools/ramboot/firmware-ramboot.dfu
  python3 tools/hxf_ram.py run build/HX_Stomp_v3.80.0_NAM_A2_Lite.hxf --stock HX_Stomp_v3.80.0_0x103966115.hxf
  ```

Presets and IRs you change during the run are lost at power-off. [RAM_RUN.md](RAM_RUN.md) explains how it works and its limits.

## Install

1. Back up your presets and IRs in HX Edit, then **close HX Edit**.
2. Open Line 6 Updater, choose **Choose File**, and pick `build/HX_Stomp_v3.80.0_NAM_A2_Lite.hxf` (on an XL, the `_XL_` file; never the other unit's).
3. Let it finish and restart the Stomp.


### HX Stomp XL

The XL's firmware 3.80.0 is the Stomp's with another build of the main application: the DSP program, the model list and the DSP graph library, the three parts the patch changes besides the application, are byte for byte the same. `tools/patch_amp.py` holds the XL's own addresses for the application's model tables, and checks each one against the table it points to. The XL image passes the same checks as the Stomp's, and every byte it changes in the application corresponds to one the Stomp build changes.

**The one-block build has run on an XL from RAM** (see [RAM_RUN.md](RAM_RUN.md)); the current multi-block build has not run on an XL yet, and neither has been installed on one. Its kernel, graph and model-list bytes are exactly those of the earlier HX Stomp build (Amp → NAM with eight knobs, MD5 `3dd9379c…`), which runs three captures on an HX Stomp; it keeps that layout, so the XL has neither the four knobs nor HX Edit keeping NAM blocks; it differs from the earlier XL build only in that DSP side and the declared DSP cost. Its block title shows the IR name, as on the Stomp: the XL's two title functions are the Stomp's with the same stack frame and registers renamed, and `patch_amp.py` holds their XL addresses; that has not been seen on an XL screen yet. If you install it on an XL, have the stock XL file ready for recovery. The XL has the same Page Right button, so holding it while powering on should give update mode as on the Stomp, but that has not been tried on an XL either.

## Use

1. Convert a capture. Either open the **[setup page](https://nocaseguy.github.io/hx-stomp-nam-lite/web/)** (step 4) and drop your `.nam` files on it, or run:
   ```sh
   python3 tools/nam2ir.py "My Amp.nam" -o "My Amp NAM.wav"
   ```
   The web page converts several files at once. It runs entirely in your browser, uploads nothing, and writes the same bytes as `nam2ir.py`.

   **Input level.** If the capture records its interface's level (`input_level_dbu` in the `.nam` metadata), the converter stores it in the `.wav`, and the web page shows it as a "captured at … dBu" chip. The amp then trims its input by `11.5 − input_level_dbu` dB, so that at Input 5.0 the Stomp's input drives the model the way the capture's interface did. 11.5 dBu is the Stomp's input at 0 dBFS as users have measured it (one unit read 15.1). It is a constant in the firmware (`STOMP_DBU` in `tools/sharc/nam_lite.py`), so a better figure needs only a firmware rebuild, not new `.wav` files. `--no-level` leaves the level out. Captures without the level, and `.wav` files from older converters, play untrimmed.
2. In HX Edit, import the `.wav` into a User IR slot, for example slot 5.
3. On the Stomp, add **Amp → NAM → NAM A2 Lite** and set **Model** to 5. For a second capture, import it into another slot and add a second NAM A2 Lite block set to that slot.

Notes:
- The Model knob shows slot numbers. The block's title shows the name of the IR in that slot (the name HX Edit gave it).
- Changing Model (by hand or in a snapshot) crossfades with no gap: the new capture fades in over about 5 ms while the last few milliseconds of the old one play backwards and fade out.
- Presets store the slot number. If you move a capture to another slot, update the presets that use it.

## Limits

- **At most 3 NAM A2 Lite blocks in a preset**, each with its own capture. The kernel (`tools/sharc/nam_multi.py`) has 3 model slots; a fourth block would pass its input through. On the HX Stomp they are effect blocks, so the two-amp limit doesn't count them. On the XL the third is the Distortion > NAM entry (preset ID 148). Run on an HX Stomp with three blocks; the XL build has the same kernel (with the tone stack) but has not run on an XL with it.
  - Each block uses about **23% of the DSP** on the unit (two blocks about 69% with an otherwise empty preset; the empty preset alone is about 20%). Both entries declare a DSP cost of 2275, a little under what they measure, so three blocks leave room for a stereo Simple Delay (about 92% of the DSP) or a heavier effect (the heaviest admitted about 96-97%, played clean on the unit).
  - **Three blocks nearly fill the DSP** (about 93%): beside them there is room for a light effect such as a stereo Simple Delay (about 97% in all, measured on the unit), and the browser greys out anything heavier. With two NAM blocks there is room for more.
  - Each block takes its own 0x5000-word block of DDR2 for its long rings; the Amp blocks' DDR2 allowance is raised to fit.
- **In HX Edit the block shows as "MM4 Frequency Shifter"** (HX Stomp), with that model's knob names: Speed is Model, Mode is Polarity, Mix is Input, Level is Output. Editing those knobs in HX Edit works, under those names. Turning Model on the Stomp is clearer (the title shows the capture).
- Only the 3-channel A2 Lite architecture fits; standard and A2 Full captures don't.
- Names on the Stomp hold 16 characters at most.

## Recovery

If the Stomp stops at the splash screen after an install:

1. Power it off. **Hold Page Right while powering it on.** It comes up in update mode, with the screen dark.
2. In Line 6 Updater, choose **Choose File** and pick the stock `HX_Stomp_v3.80.0_0x103966115.hxf`.

This has been done on a real unit after a modified firmware hung at the splash, and it restored stock 3.80.0. It works because the bootloader is left untouched.

## How it works

- **The DSP.** The HX Stomp's audio runs on an Analog Devices SHARC ADSP-21469. The kernels are hand-written SHARC assembly, bit-exact with the reference:
  - `tools/sharc/nam_multi_kernel.asm`: the WaveNet layers run two samples at a time in SIMD. The free internal memory is split into 3 slots, one model each; the long rings live in each block's own DDR2 block, and their taps are copied in by chained external-port DMA while the previous layer computes.
- **No vendor toolchain.** `tools/sharc/sasm.py` assembles the code and `tools/sharc/ssim.py` simulates it.
- **Captures through the IR slots.** The Stomp already stores up to 128 User IRs of 2,048 samples and hands them to the DSP unchanged.
  - `nam2ir.py` packs a capture's weights into those samples, behind a small header the kernel recognises.
  - HX Edit refuses samples beyond about ±15.8, so the weights are scaled by a power of two, which is exact.
- **The title.** The application shows an IR's name in the block title only for IR blocks. `patch_amp.py ir-title` turns the two places that test for an IR block into jumps to a few added instructions that also take that path for NAM A2 Lite's preset ID. It changes what the screen shows only: the parameter, its DSP value and presets are as before.
- **HX Edit.** HX Edit keeps its own copy of the preset, built with its own model list, and for some edits writes that copy back whole: a block of a model it doesn't know is left out. On the HX Stomp, `patch_amp.py remove-model` frees a stock model's preset ID (MM4 Frequency Shifter, 461; its code stays, nothing selects it), and `add-fx-model --knobs nam4` puts NAM there with its four knobs in that model's order and value types (HX Edit writes each value in its own model's type, and the Stomp drops a whole preset holding a value of another type). Model is a float knob from 0 to 1000 on the Stomp, which steps it one slot a click; the kernel truncates it. `move-folder` lists the effect under Amp → NAM, and `ir-title --knob 0` reads the title's IR from that float knob. The kernel's `--no-tone` keeps the tone stack a pass-through, as there are no tone knobs.
- **The amp.** `tools/patch_amp.py` builds the amp's DSP graph, parameter map and menu entries. A parameter count has to agree in three places (the model table, the graph's parameter map and the menu's info row), or the Stomp shows the wrong name or crashes.
- **The container.** `tools/hxf.py` and `tools/l6ia.py` read and write the `.hxf` container and the archive inside it. These use checksums only; there is no encryption or signature.

## Tests

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -m "not slow and not firmware"   # about 1 s: the model data, the converters, the helpers
.venv/bin/pytest -m slow                          # about 20 s: the kernel in the simulator
HX_STOMP_HXF=path/to/HX_Stomp_v3.80.0_0x103966115.hxf .venv/bin/pytest -m firmware
```

GitHub Actions runs the first two on every push and pull request. The firmware tests need your own stock file (`HX_STOMP_HXF`, `HX_STOMP_XL_HXF`) and are skipped without one. They build the whole `.hxf` and compare its MD5 with the one pinned in `tests/test_firmware.py`: the build is deterministic, so a changed byte anywhere in the firmware fails until the pin is updated on purpose.

Write the test first, watch it fail, then change the code:
- **Kernel behaviour:** add a step to `KernelCheck` in `tools/sharc/nam_multi.py` and its name to `STEPS`. `tests/test_multi_kernel.py` runs them, and so does `build.py`.
- **The converters:** `tests/test_web_parity.py` checks that `web/nam2ir-core.js` writes the same bytes as `nam2ir.py` and refuses the same captures, so a change to one fails until the other matches.

## Layout

```
build.py                      one-step build from the stock .hxf
tools/nam2ir.py               .nam -> User IR .wav
web/index.html                the setup page: firmware build (web/firmware-worker.js), RAM run (web/ramrun.js) and converter (web/nam2ir-core.js)
tools/patch_amp.py            inspect / add-model / ir-title / patch
tools/hxf.py, l6ia.py         .hxf container and L6IA archive
tools/l6ia_verify.py          checks every checksum in an archive
tools/hxf_ram.py              runs a build from RAM (RAM_RUN.md); tools/ramboot/ holds the built loader and hook
tools/sharc/nam_multi.py      the kernel's layout, data and simulator check
tools/sharc/nam_multi_kernel.asm
tools/sharc/nam_lite.py       the model format (converter), test model, shared tables, reference run
tools/sharc/nam_pack.py       .nam loader, layer order
tools/sharc/entry4_blob.py    DSP graph library parser
tools/sharc/sasm.py, ssim.py  SHARC assembler and simulator
src/sharc/nam_a2.asm          reference NAM A2 implementation for the check
src/ramboot/                  the RAM loader and its eMMC overlay hook (C, Cortex-M4; make -C src/ramboot)
tests/                        pytest: unit, web parity, kernel (slow), firmware (needs a stock .hxf)
```

## Licence

GPL-3.0-or-later; see [LICENSE](LICENSE). Third-party notices and trademarks are listed in [NOTICE](NOTICE).
