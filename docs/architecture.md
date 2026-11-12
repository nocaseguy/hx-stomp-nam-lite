# How HXtra works

HXtra changes the HX Stomp's firmware file on your computer: no Line 6 code is in this repository, and the bootloader is never touched. This page is the map for contributors; the [research notes](research/INDEX.md) have the details.

## Where it came from

[hx-stomp-nam-lite](https://github.com/nocaseguy/hx-stomp-nam-lite), by Derek Bui (nocaseguy), did the hard part: it showed the HX Stomp's firmware can be changed safely. It brought a SHARC assembler and simulator, a NAM A2 Lite kernel written from scratch in SHARC assembly, tools that read and rebuild the `.hxf` container and fix every checksum, a loader that runs a build from RAM without installing it, and an in-browser setup page. It also showed that leaving the bootloader alone keeps a bricked HX Stomp recoverable.

HXtra forks it at upstream commit `2e80164`, has merged upstream up to `01c0bb0`, and builds on those tools. What it adds:

- **New functionality on the Cortex-M4 application** (the HX Stomp's UI and control side), not just the DSP, added as small Thumb-2 code caves that each check the stock bytes they replace.
- **A feature engine.** Each feature is its own module in `tools/features/`, with its own settings, hooks and tests, and features that hook the same place in the firmware share it instead of overwriting each other (see [How it works](#the-pieces)).
- **A way for the DSP to talk to the UI.** A DSP routine writes its own values into the unused tail of the frames the DSP already sends the M4, and an M4 hook reads them. This needs no knowledge of Line 6's own message formats.
- **[Research notes](research/INDEX.md)**, a shared map of what is known about the 3.80.0 firmware, one note per part of the system: addresses, formats, techniques that work, dead ends, and what is still open. An index says what each note covers and when you'd need it. Every claim is marked verified on the unit, verified offline, or a hypothesis.

## The pieces

- **The container.** `tools/hxf.py` and `tools/l6ia.py` read and write the `.hxf` container and the L6IA archive inside it, and `tools/l6ia_verify.py` checks every checksum. There is no encryption or signature.
- **The M4 application.** The HX Stomp's UI runs on an NXP LPC4350 (Cortex-M4). Patches add code caves to the application and reach them with branches from the stock code, and every patch checks the stock bytes before it writes.
- **Features.** `tools/patch_menu.py` is the engine and `tools/features/<name>.py` the features. A feature module declares its switch (`FLAG`, and `INPUTS` for values such as a picture's path), its `SETTINGS`, and `apply(p)` for its code and hooks:
  - **M4 code** is a `src/m4/<name>.s` file, which `p.module()` assembles at build time (`tools/m4asm.py`) with a generated `hxtra.inc` that defines each setting's ID, range and default.
  - **Setting IDs** are claimed in one place, `tools/setting_ids.py`, and the tests fail on a duplicate.
  - **Writes are checked:** every write goes through `Patch.put`, which fails the build if two features write the same bytes.
  - **Shared hooks:** a place several features need is hooked once, with `p.chain_ptr` (a function pointer), `p.chain_bl` (a call) or `p.chain_entry` (a function's start). Its stub runs each feature's handlers around the stock function.
  - **Owned hooks:** a place that can't be shared (stack arguments, or a handler that rewrites them) is taken by one feature with `p.own_entry` (a function's start) or `p.own_call` (a call, such as a tail call).
  - **Other parts:** the image store and fonts (Entries 7 and 8) are changed through `p.entry(n)`, `add_item` and `p.add_glyph` (`tools/image_store.py`), never by hand.
- **The DSP.** The audio runs on an Analog Devices SHARC ADSP-21469. Kernels are hand-written SHARC assembly, assembled by `tools/sharc/sasm.py` and simulated by `tools/sharc/ssim.py`, with no vendor toolchain. A custom kernel is hooked to an unused DSP primitive.
- **NAM captures through the IR slots.** The HX Stomp already stores up to 128 User IRs of 2,048 samples and hands them to the DSP unchanged. `nam2ir.py` packs a capture's weights into those samples, behind a small header the kernel recognises.
- **The NAM block.** `tools/patch_amp.py` builds the block's DSP graph, parameter map and menu entries on Xenomorph Fuzz Mono's identity, with the NAM kernel as its DSP stage (`build.py`'s `STEPS`).

The [research notes](research/INDEX.md) have the details: addresses, the M4-to-DSP frame format, the Settings and Home screen internals, and the open problems. Start from their index.

## Repository layout

```
build.py                      one-step build from the stock .hxf
docs/features.md              every feature and setting, for players
docs/building.md              building from the command line, the browser build, RAM runs
docs/research/INDEX.md        what is known about the 3.80.0 firmware: the index of the research notes
tools/patch_menu.py           HXtra: the feature engine, the Global Settings section and its caves (HX Stomp)
tools/features/               the features: tuner.py, bpm.py, breathing_line.py, dsp_meter.py, long_press.py, more_snapshots.py, splash.py
tools/setting_ids.py          which setting ID each feature's setting uses
tools/m4asm.py                assembles a feature's src/m4/*.s with Apple's clang, or takes it from a release's m4cache.json
tools/m4cache.py              a release's m4cache.json: the M4 code of the setup page's features
tools/release.py              makes a release: its m4cache.json on a GitHub release, which publishes the setup page
src/m4/                       the features' M4 code (tuner.s, bpm.s, breathing_line.s, dsp_meter.s, long_press.s, more_snapshots.s)
tools/image_store.py          the image store (Entries 7 and 8): images, fonts, items
tools/icon_library.py         the icon library: every stock icon drawn from your firmware file (docs/icons.md)
tools/patch_splash.py         boot screen pictures; splash_hxtra.py relabels the stock one, splash_topo.py draws one, splash_emoji.py and emoji_png.swift make emoji glyphs
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
web/                          the setup page: build, RAM run and converter in the browser (published per release: .github/workflows/pages.yml)
tests/                        pytest: unit, M4 code in unicorn (m4emu.py), web parity, kernel (slow), firmware (firmware.py; needs a stock .hxf)
```
