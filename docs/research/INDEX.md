# Research index

What is known about the HX Stomp 3.80.0 firmware, one note per part of the system. Read this page first, then open only the notes your work needs. Each line gives the note, what it covers, and when you'd need it.

Before writing anything, read [conventions.md](conventions.md): the status tags, the rules (addresses only, never Line 6 code or data) and where a new finding goes.

## Start here

| note | covers | read it when |
|---|---|---|
| [conventions.md](conventions.md) | status tags, rules, where to add a finding, the working method (RAM runs, `--writes pass`, build names) | always, before adding a finding or testing on the unit |
| [tools.md](tools.md) | every tool in `tools/` and the build switches | looking for a tool, or how to build an experiment |
| [features/engine.md](features/engine.md) | a feature module: its settings, flag, inputs, and the hooks it shares (`chain_*`) or owns (`own_entry`, `own_call`); Entries 7 and 8 access | starting a new feature, or hooking a site |
| [../resource-limits.md](../resource-limits.md) | which resources are nearly full and what changes cost | planning a feature |
| [ideas.md](ideas.md) | open ideas from the old notes | looking for what to do next |

## Formats

| note | covers | read it when |
|---|---|---|
| [formats/containers.md](formats/containers.md) | the `.hxf`, its L6IA archive, Entries 0, 2, 3 and 4, internal CRCs | changing any entry, or reading the build pipeline |
| [formats/image-store.md](formats/image-store.md) | Entry 7 (image index) and Entry 8 (pixels): records, pixel format (blue high, red low), appending images and items | adding or changing an image, icon or glyph |

## The M4 (CPU) side

| note | covers | read it when |
|---|---|---|
| [m4/toolchain.md](m4/toolchain.md) | disassembling Entry 0, assembling Thumb-2 with clang, no VFP in hooks | writing any M4 code |
| [m4/settings.md](m4/settings.md) | setting IDs, the stores and the Globals file, limits types, the menu, pages, feature sections, the icon strip, virtual settings | adding or changing a setting, or a Global Settings page |
| [m4/home-screen.md](m4/home-screen.md) | the Home view and divider, widget types and setters, creating widgets, the paint passes and damage rectangles, the framebuffer, the top view and Edit view, block slots | drawing anything on the Home screen or the Edit view |
| [m4/text-and-fonts.md](m4/text-and-fonts.md) | the six fonts and their glyph tables, the text widget, anchors, glyph colour, the float formatter | drawing text |
| [m4/boot-screen.md](m4/boot-screen.md) | the stock boot picture, drawn by the bootloader then by the app | changing the boot screen |
| [m4/dsp-cost.md](m4/dsp-cost.md) | per-model DSP costs, block records and block objects, block IDs and slots, the preset total and its 90% limit | anything about DSP load, or finding a block's object from its slot |
| [m4/model-browser.md](m4/model-browser.md) | the model browser's view, rows, levels, categories and items | changing the model list, or adding a model to a category |
| [m4/tempo-and-leds.md](m4/tempo-and-leds.md) | the tempo settings (IDs 14..16), the tap tempo screen, the footswitch LEDs and LED task, the stock beat, the µs clock | anything tempo-synced, or lighting the LEDs |
| [m4/footswitches.md](m4/footswitches.md) | footswitch functions, key events and holds, the event handler and key task, bypass assignment, controllers, MIDI CC bypass | changing what a footswitch does |
| [m4/snapshots.md](m4/snapshots.md) | the snapshot manager and records, select and its callers, the snapshot footswitch mode, the snapshot icon | anything about snapshots |
| [m4/presets.md](m4/presets.md) | the eMMC stores (presets, globals, IRs) and the preset file's layout | storing data in a preset, or reading preset files |
| [m4/dsp-link.md](m4/dsp-link.md) | the SPI frames between the DSP and the M4, and sending DSP values in a frame's tail | getting a value from the DSP to the screen |

## The SHARC (DSP) side

| note | covers | read it when |
|---|---|---|
| [sharc/registry.md](sharc/registry.md) | the SHARC assembler and simulator, the primitive registry, wrapping a primitive (`--wrap-prim`), custom kernels, VISA code and the control-function ABI | writing DSP code, or intercepting a primitive or its parameters |
| [sharc/model-blobs.md](sharc/model-blobs.md) | a model's parameters in Entry 3, Entry 4's parameter maps and node trees, the Entry 0 info row, tempo sync | adding a block parameter or a model |
| [sharc/cores/compressors.md](sharc/cores/compressors.md) | the compressor cores `0x271a`, `0x2719`, `0x2710`: which block uses which, wiring, pids, init values, the Deluxe core's loop | metering or changing a compressor |

## Features

| note | covers | read it when |
|---|---|---|
| [features/gr-meter.md](features/gr-meter.md) | the GR meter end to end: knobs, DSP wrapper, frame words, M4 drawing | working on the GR meter, or another DSP-measured display |
| [features/gr-meter-log.md](features/gr-meter-log.md) | every GR meter image and its result, in order | checking whether an idea was already tried |
| [features/dsp-meter.md](features/dsp-meter.md) | per-block DSP cost in the Edit view and the model browser | working on the DSP meter |
| [features/dsp-meter-log.md](features/dsp-meter-log.md) | the DSP meter's images and results | checking what was tried |
| [features/bpm.md](features/bpm.md) | the BPM on Home and its beat dot, the hooks, the boot stagger, the half-drawn-dot known issue | working on the BPM, or the beat |
| [features/breathing-line.md](features/breathing-line.md) | the animated Home divider | working on the breathing line, or any animation on Home |
| [features/tuner-page.md](features/tuner-page.md) | the tuner settings view and the page HXtra adds to it | changing the tuner's settings view |
| [features/long-press.md](features/long-press.md) | holds per footswitch, FS6..FS10 on CC 20..24, CC text, the footswitch probes | working on long press, or footswitch holds |
| [features/more-snapshots.md](features/more-snapshots.md) | bank B (snapshots 4..6), the bank marker, saving and the preset file key, next and previous across the banks | working on more snapshots |
| [features/metronome.md](features/metronome.md) | the Metronome block: model, browser folder, look, kernel | working on the Metronome, or adding an effect model |
| [features/boot-splash.md](features/boot-splash.md) | a custom boot picture, the boot line's text, colour emoji | working on the boot screen |

## Other docs

| note | covers |
|---|---|
| [../gr-meter-standards.md](../gr-meter-standards.md) | how hardware GR meters behave, which the GR meter follows |
| [../icons.md](../icons.md) | picking a stock icon for a feature section |
| [../../RAM_RUN.md](../../RAM_RUN.md) | running a build from RAM on the unit |
| [../../QA.md](../../QA.md) | the on-unit test tools |

## NAM A2 Lite research

Measurements and studies from building NAM A2 Lite into the stock firmware, copied from the upstream project's working repository: see [README.md](README.md) for the list. In short:

| note | read it when |
|---|---|
| [NAM_LITE_DSP_LOAD.md](NAM_LITE_DSP_LOAD.md) | measuring or budgeting DSP cycles |
| [AMP_LIMIT.md](AMP_LIMIT.md) | the 2-amp limit per preset |
| [HX_EDIT_DROPS_NAM.md](HX_EDIT_DROPS_NAM.md) | a new model doesn't survive HX Edit |
| [NAM_INPUT_CALIBRATION.md](NAM_INPUT_CALIBRATION.md) | input levels in dBu |
| [STOMP_TEST_A_PRESET_SWEEP.md](STOMP_TEST_A_PRESET_SWEEP.md) | checking stock presets against new memory use |
| [KIT_HEAP_USE.md](KIT_HEAP_USE.md) | using stock DSP heaps |
| [KIT_UNIT_MEASUREMENTS.md](KIT_UNIT_MEASUREMENTS.md) | the DSP call rate and load word |
| [KIT_EP_DMA.md](KIT_EP_DMA.md) | external-port DMA on the SHARC |
| [STOCK_BITEXACT_OPT.md](STOCK_BITEXACT_OPT.md) | stock models' declared cost against their measured cycles |
| [KIT_NAM_A2_FULL.md](KIT_NAM_A2_FULL.md), [NAM_A2_FULL_STOCK_UNIT.md](NAM_A2_FULL_STOCK_UNIT.md) | NAM A2 Full, studied and stopped |
| [HELIX_FLOOR_FEASIBILITY.md](HELIX_FLOOR_FEASIBILITY.md), [HELIX_FLOOR_KERNEL_COST.md](HELIX_FLOOR_KERNEL_COST.md), [HELIX_FLOOR_RECALL.md](HELIX_FLOOR_RECALL.md) | the Helix Floor / LT |
