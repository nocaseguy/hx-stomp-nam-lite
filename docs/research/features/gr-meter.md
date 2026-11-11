# GR meter (`HX_GR=1`, `tools/features/gr.py`, `src/m4/gr_meter.s`, `src/sharc/frame_probe.asm`, `tools/patch_comp.py`)

Ten lights on the Home screen showing a compressor block's gain reduction, set by that block's own knobs. How it works end to end; the image-by-image history is in [gr-meter-log.md](gr-meter-log.md). Status tags as in [conventions.md](../conventions.md).

## What it does

- Ten lights at 1, 2, 3, 4, 6, 8, 10, 14, 19 and 25 dB of gain reduction, green to red (`00ff00` .. `ff0000`), on the Home divider (Middle) or along an edge of the screen (Top, Left, Bottom, Right). Middle, Top and Bottom are 30 px lights at a 32 px pitch, Middle in place of the divider's four segments; Left and Right are 21 px lights at a 24 px pitch, clear of the divider, which then stays stock. [verified on unit: Two-pass, Middle-position and Paint-layout images]
- Each compressor block gets three knobs: **Mtr Pos** (Middle, Top, Left, Bottom, Right), **Mtr Dir** (Normal: left to right or top to bottom; Reverse) and **Mtr Thk** (0..20 px; 0 is off and the default, so the meter is opt-in). Their preset keys are `GRPosition`, `GRDirection`, `GRThickness`. There are no Global Settings. [verified on unit: Value-at-R8 and Mtr-names images]
- Blocks (`COMP_MODELS` in `tools/patch_comp.py`), mono and stereo: Deluxe Comp and Rochester Comp (core `0x271a`), LA Studio Comp (`0x2719`), Kinky Comp, Ampeg Opto Comp and Red Squeeze (`0x2710`). Each was checked on the unit; see their entries in the log.
- The meter shows the core that was last given a Mtr Thk above 0 (`GR_CORE`). With several compressors in a preset, only that one is measured. [verified on unit: Metered-core image]

## How it works

1. **Knobs** (`tools/patch_comp.py`, [sharc/model-blobs.md](../sharc/model-blobs.md)): each model gets three integer parameters after its own, in Entry 3, its blob's parameter map and its Entry 0 row, with writers to the core as pids 100..102, and an init record per core, pid 103, saying whether the composite wires the core's output over its first input or its second. A model whose core had no writer gets a path word in its parameter map.
2. **DSP** (`src/sharc/frame_probe.asm`, [sharc/registry.md](../sharc/registry.md)): `patch_comp.py` places the wrapper in Block 3 right above NAM's slots (`dsp_place()`; so `HX_GR=1` builds NAM with two slots, `build.py` `GR_SLOTS`) and points each core's registry entry at a wrapper (`ENTRY_271A`, `ENTRY_2719`, `ENTRY_2710`) and its control slot at our own (`CTRL_*`). The control function, called as (pid R4, pointer to the value R8, the core's state R12), keeps pids 100..103 per core (`KN_TAB`, `ORI_TAB`), and for `0x2710` the core's Attack and Release (`KK_TAB`); every other pid goes to the stock function. The process wrapper calls the stock code, then, for the metered core only, takes the peak of its input before the call and of its output after it (`I1` or `I2`, by `ORI_TAB`: both inputs change in the call, so the output can't be found at run time); for the Deluxe Comp, A is 1 / the core's own gain `PM(1, I8)`. It keeps the largest of each over a 64-block window (about 21 ms).
3. **The frame** ([m4/dsp-link.md](../m4/dsp-link.md)): the wrapper writes into every outgoing frame's tail: 200 the marker, 216 and 217 the window peaks, 218 the knobs (tag `0x6B`, then Position, Direction, Thickness; 0 with no metered core), 250 the window count, 251 the Release coefficient to the 1024th power, 252 the Attack coefficient to the 512th. The Attack and Release come from the Deluxe core's state, the Kinky core's `KK_TAB` entry, or else a fixed 10 ms and 500 ms. A tag in word 253 never reached the M4 [verified on unit: Where-lost and Word-218 images].
4. **M4** (`src/m4/gr_meter.s`, `tools/features/gr.py`, [m4/home-screen.md](../m4/home-screen.md)): four handlers on shared hooks: `frame` before the DSP stream's receive callback, `construct` after the Home constructor (46 widgets of its own, hidden), and `erase` and `draw` around the Home paint. The frame handler turns the peaks into dB with integer maths (log2 in 1/256 octaves, within 0.14 dB; the thread has no FPU context of its own), shows the reduction as measured both ways (it already carries the comp's attack and release), and in silence (input below -72 dB) lets it decay at the comp's Release. It only records the layout (lights lit, Position, Direction, Thickness) and asks for a repaint when that changes; the paint applies it to the widgets under the widget lock, as the stock paint does, so no setter runs on the DSP stream's thread. 64 frames after the meter first shows, the paint runs the stock Home layout `0x28dc87cc(home, 0)` once, or the footswitch labels stay blank. While the meter shows, the breathing line yields to it (`SHOWN`).

## Standards

- **GR-meter standards** (`docs/gr-meter-standards.md`): meter the applied gain; keep the largest GR per display update; instant rise; do not apply the comp's attack again; 10 lights, non-linear, 1 dB first step.

## Known limits

- The Deluxe Comp in a playing preset reads low (Metered-core and Gain-read images); the Rochester Comp, on the same core, does not [verified on unit].
- The Sweep Echo and the Busy One amps and preamps run the same cores, so they go through the wrapper too: it calls their stock code and passes their own pids on, and measures only the metered core (see Shared cores in [sharc/cores/compressors.md](../sharc/cores/compressors.md)).

The compressor cores: [sharc/cores/compressors.md](../sharc/cores/compressors.md). Frame words: [m4/dsp-link.md](../m4/dsp-link.md).
