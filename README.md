# NAM A2 Lite for the HX Stomp

This repository adds **Neural Amp Modeler (NAM) A2 Lite** to the stock Line 6 HX Stomp firmware, version 3.80.0, as a new amp model. NAM captures then run on the Stomp's own DSP, like any other amp block.

## Demo

[![NAM A2 Lite running on an HX Stomp (YouTube)](https://img.youtube.com/vi/zQzj0qahJ6E/hqdefault.jpg)](https://www.youtube.com/watch?v=zQzj0qahJ6E)

Watch it on YouTube: https://www.youtube.com/watch?v=zQzj0qahJ6E

> **Unofficial and experimental.** Not affiliated with, endorsed by or supported by Line 6 or Yamaha Guitar Group. Installing modified firmware is at your own risk and may void your warranty. Read [Install](#install) and [Recovery](#recovery) before you start.

## What you get

- **NAM A2 Lite**, a new amp in the menu under **Amp → NAM**, with seven knobs:

  | Knob | What it does |
  |---|---|
  | **Model** | Which capture plays: 1–128 is the User IR slot that holds it. A slot holding anything else (a cab IR, or nothing) is silent. |
  | **Drive** | Input gain into the capture, −20 to +20 dB; 0 dB (the capture's own level) at 5.0 |
  | **Bass / Mid / Treble / Presence** | A tone stack after the model, ±12 dB, flat at 5.0 (100 Hz shelf, 650 Hz peak, 2.5 kHz and 5.5 kHz shelves) |
  | **Ch Vol** | Output level; 0 dB at 5.0, +12 dB at 10 |

- **A converter** (a web page, `web/index.html`, or `tools/nam2ir.py`) turns a `.nam` file into a `.wav`. HX Edit imports that `.wav` as a User IR. The "IR" is not a sound: it carries the capture's 1,871 weights, and the amp loads them from the slot.

Everything else in the firmware stays stock 3.80.0.

## What this repository contains, and what it doesn't

**No Line 6 code or data is in this repository**, and no firmware file is distributed. You need your own copy of the official firmware file. The build reads it on your computer, applies the changes and writes a new `.hxf` for you. Please don't share the built `.hxf`: it is Line 6's firmware with changes, and it isn't yours or ours to redistribute.

What is here is our own work:
- a SHARC assembler and simulator;
- the NAM A2 Lite kernel, written from scratch in SHARC assembly;
- tools that read the firmware container and patch the model tables;
- the offsets they patch.

**No NAM captures are included.** You bring your own `.nam` files, and their licences are up to their authors.

## Requirements

- An **HX Stomp** (not the XL or the LT; the patch is for the Stomp's firmware only).
- `HX_Stomp_v3.80.0_0x103966115.hxf`, Line 6's firmware 3.80.0 for the HX Stomp, MD5 `a2cd8f4ae56f49415380270ebc484bf1`. The build checks the MD5 and refuses any other file.
- Python 3.10 or newer with `numpy`: `pip install numpy`.
- **Line 6 Updater** to install, and **HX Edit** to import captures.
- 3-channel **A2 Lite** captures. A `.nam` with several sizes in one file (a SlimmableContainer) works too: its A2 Lite model is used.

## Build

```sh
python3 build.py path/to/HX_Stomp_v3.80.0_0x103966115.hxf
```

This writes `build/HX_Stomp_v3.80.0_NAM_A2_Lite.hxf`. It takes about 20 seconds. The build:

1. Assembles the kernel and runs it in the SHARC simulator. The output must match a reference NAM A2 implementation (`src/sharc/nam_a2.asm`) bit for bit; the check also covers the tone stack, the fades and loading from IR slots. Add `--no-check` to skip this step.
2. Adds the amp, with the steps below:
   - copies the Line 6 Clarity amp's DSP graph and replaces its amp stage with the NAM kernel;
   - gives the copy its own seven parameters;
   - lists it in a new **NAM** folder under Amp;
   - enlarges the DSP's graph buffer to fit the extra graph.
3. Adds the kernel to the DSP's boot code and hooks it to an unused DSP primitive.
4. Recomputes and verifies every checksum: the container MD5, the archive Fletcher-32 and CRC-32, and the image CRCs.

Only 4 of the 15 parts of the firmware change: the main application's model tables, the DSP program, the model list and the DSP graph library. **The bootloader is never touched**, which is what keeps [Recovery](#recovery) possible.

## Install

1. Back up your presets and IRs in HX Edit, then **close HX Edit**.
2. Open Line 6 Updater, choose **Choose File**, and pick `build/HX_Stomp_v3.80.0_NAM_A2_Lite.hxf`.
3. Let it finish and restart the Stomp.

## Use

1. Convert a capture. Either open **`web/index.html`** in a browser and drop your `.nam` files on it, or run:
   ```sh
   python3 tools/nam2ir.py "My Amp.nam" -o "My Amp NAM.wav"
   ```
   The web page converts several files at once. It runs entirely in your browser, uploads nothing, and writes the same bytes as `nam2ir.py`.
2. In HX Edit, import the `.wav` into a User IR slot, for example slot 5.
3. On the Stomp, add **Amp → NAM → NAM A2 Lite** and set **Model** to 5.

Notes:
- The Model knob shows slot numbers, not IR names.
- Changing Model fades the old capture out and the new one in, with no pop.
- Presets store the slot number. If you move a capture to another slot, update the presets that use it.

## Limits

- **One NAM A2 Lite at a time.** A second instance passes its input through unchanged. If you delete the first, the second takes over.
- Measured in the simulator, the kernel uses about **23% of the DSP** per audio block (34,182 of 150,000 cycles). The amp declares a DSP cost of 3600, like the heaviest stock amps, so the Stomp greys out other heavy blocks next to it.
- Only the 3-channel A2 Lite architecture fits; standard and A2 Full captures don't.
- Names on the Stomp hold 16 characters at most.

## Recovery

If the Stomp stops at the splash screen after an install:

1. Power it off. **Hold Page Right while powering it on.** It comes up in update mode, with the screen dark.
2. In Line 6 Updater, choose **Choose File** and pick the stock `HX_Stomp_v3.80.0_0x103966115.hxf`.

This has been done on a real unit after a modified firmware hung at the splash, and it restored stock 3.80.0. It works because the bootloader is left untouched.

## How it works

- **The DSP.** The HX Stomp's audio runs on an Analog Devices SHARC ADSP-21469. The kernel (`tools/sharc/nam_lite_kernel.asm`) is hand-written SHARC assembly:
  - the WaveNet layers run two samples at a time in SIMD;
  - the long-dilation rings sit in external DDR2;
  - the result is bit-exact with the reference.
- **No vendor toolchain.** `tools/sharc/sasm.py` assembles the code and `tools/sharc/ssim.py` simulates it.
- **Captures through the IR slots.** The Stomp already stores up to 128 User IRs of 2,048 samples and hands them to the DSP unchanged.
  - `nam2ir.py` packs a capture's weights into those samples, behind a small header the kernel recognises.
  - HX Edit refuses samples beyond about ±15.8, so the weights are scaled by a power of two, which is exact.
- **The amp.** `tools/patch_amp.py` builds the amp's DSP graph, parameter map and menu entries. A parameter count has to agree in three places (the model table, the graph's parameter map and the menu's info row), or the Stomp shows the wrong name or crashes.
- **The container.** `tools/hxf.py` and `tools/l6ia.py` read and write the `.hxf` container and the archive inside it. These use checksums only; there is no encryption or signature.

## Layout

```
build.py                      one-step build from the stock .hxf
tools/nam2ir.py               .nam -> User IR .wav
web/index.html                the same in a browser (web/nam2ir-core.js)
tools/patch_amp.py            inspect / add-model / patch
tools/hxf.py, l6ia.py         .hxf container and L6IA archive
tools/l6ia_verify.py          checks every checksum in an archive
tools/sharc/nam_lite.py       kernel + data, and its simulator check
tools/sharc/nam_lite_kernel.asm
tools/sharc/nam_pack.py       .nam loader, layer order
tools/sharc/entry4_blob.py    DSP graph library parser
tools/sharc/sasm.py, ssim.py  SHARC assembler and simulator
src/sharc/nam_a2.asm          reference NAM A2 implementation for the check
```

## Licence

GPL-3.0-or-later; see [LICENSE](LICENSE). Third-party notices and trademarks are listed in [NOTICE](NOTICE).
