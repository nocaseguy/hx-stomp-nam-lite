# HX Edit drops NAM blocks (unit, 2026-11-03)

A user report: in HX Edit, moving blocks in a NAM preset made the amp block vanish. Repro by
the owner: two NAM A2 Lite blocks added **on the device** (path A slot 1, path B slot 2, Model
1), then in HX Edit block B dragged from B slot 2 to B slot 1: **both** NAM blocks gone, the
edit buffer empty of blocks.

## What HX Edit sent (tools/hxedit_usblog, HX Edit 3.82)

For that drag HX Edit sent **editor cmd 0x15**, a whole preset (2,234-byte blob), not moves.
The preset holds only the I/O entries (input 0, output 9, split 10, join 19): **no processing
block at all**. The unit loaded it, so both NAM blocks went. The unit is not at fault: hx_ctl
moves the same blocks (Model 1, gaps, within and across paths) and keeps them
(tools/hx_move_test.py and hand moves).

HX Edit holds its own copy of the edit buffer, built with its own model list (Helix.sym and its
catalog, never the unit's). It does not know NAM's preset ids: 147 is `HD2_AppDSPFlow1Input`
(shown as "Input", "Not Recognized in this version of HX Stomp"), 572 an empty box. Its copy
leaves such blocks out. Whenever HX Edit writes the whole preset from that copy, NAM blocks
are lost.

## When HX Edit moves and when it writes the whole preset

| drag (unit, release build 147 from RAM unless noted) | blocks before | result |
|---|---|---|
| A slot 0 -> A slot 2, blocks placed by hx_ctl (A0, B0) | contiguous | moves, kept |
| A slot 2 -> B after B's NAM | | moves, kept |
| B slot 2 -> B slot 1, blocks added on the device (A1, B2) | gaps before them | **cmd 0x15 without the blocks: both lost** |
| same kind of drag on a 486 build (NAM on Agua 51's id, a model HX Edit knows) | | one NAM kept with Model clamped to 1 (Agua's Drive range 0..1), the other lost (not logged) |

Which drags (and which other HX Edit actions) write the whole preset is not mapped yet.
HX Edit clamps knob values to its own model's ranges when it rewrites a block (a stock amp's
Drive written as 4.0 came back as 1.0 after a drag).

## Not the cause

- The stock IR limit (one 2048 IR, or two 1024 IRs; tools/hx_move_test.py notes) also drops
  presets, but this repro has no IR block.
- The DSP budget: two NAM blocks are ~6,050 units of 9,000.

## Levers

- Users: move NAM blocks on the unit, not in HX Edit (moving on the device keeps them).
- A preset id HX Edit knows (a stock model's, removed from the unit): HX Edit then keeps the
  block but rewrites its values in that model's ranges (Model clamped). Costs that stock model;
  old 147 presets no longer open as NAM.

## The donor test (unit, 2026-11-03, from RAM)

HX Edit keeps a block in its copy only if it knows the model, and the unit then takes HX Edit's
whole-preset write only if every value has the **type** the unit's own definition gives that
position (hx_ctl writes on the unit: a float where it has an int, an int where it has a bool,
an int where it has a float: each drops the whole preset). HX Edit writes values in its model's
types and clamps them to its ranges.

| build | HX Edit shows | the B2 -> B1 drag | unit after |
|---|---|---|---|
| release, 147 | "Input", Not Recognized | 0x15 with no blocks | both NAM gone |
| 572/768 | empty box | (gone) | gone |
| 486 (Agua 51's id) | Agua 51 | (not logged) | one kept with Model clamped to 1 |
| 555, NAM's knobs in its own types | Xenomorph Fuzz | 0x15 with both, Model 4.0 (float) | **preset dropped**: type mismatch |
| **555 v2, Xenomorph's types** | Xenomorph Fuzz | four 0x15 writes and two moves (cmd 0x2b) | **both kept, every value exact** |

Stock control: two stock Xenomorph blocks in the same gap layout, values kept exactly by HX
Edit's 0x15 (MinFreq 5/6/7/8). HX Edit's copy of a preset with gaps can be wrong for stock
blocks too: it duplicated block A (the owner saw 3 blocks), an HX Edit bug apart from NAM.

v2 (`tools/nam_donor/build_xeno.sh`): Xenomorph Fuzz Mono (555) removed from the unit (Table 1
row and browser items, `tools/nam_donor/remove_model.py`; its code stays), NAM A2 Lite added as
Distortion > NAM on 555 (`tools/nam_donor/patch_amp_xeno.py`), the same kernel, no Amp entry.
Knobs, position by position against Xenomorph's:

| # | Xenomorph (HX Edit) | NAM | type, NAM range |
|---|---|---|---|
| 1 | Gain | Input (pid 5) | float 0..1 |
| 2 | Tone | Bass (8) | float 0..1 |
| 3 | Level | Mid (9) | float 0..1 |
| 4 | Clipping | Polarity (15) | int 0..1 (labels Soft/Hard) |
| 5 | OscLevel | Treble (10) | float 0..1 |
| 6 | OscTone | Presence (11) | float 0..1 |
| 7 | MinFreq 0..6000 | Model (7) | float 1..128 (the kernel TRUNCs a float Model) |
| 8 | MaxFreq 0..6000 | Ch Vol (6) | float 0..1 |
| 9 | WaveShape | unused (DM 19) | int 0..2 |
| 10 | Sensitivity | unused (DM 20) | float 0..1 |

v3 (same build script): the IR-name title again, from knob 6 (`tools/nam_donor/ir_title_knob.py`:
patch_amp's ir-title sites and checks, a cave that makes the stock IR Single branch's value read
with q = {-2, 6} and truncates the float with integer code, no VFP; the redraw on knob 6); Model
shown as the IR block's IR Select (displayType dynamicList); Polarity labelled Normal/Inverted.
On the unit (owner, from RAM): the titles show the captures' names, the Model knob steps through
the slots, Polarity reads Normal/Inverted, both blocks play their captures.

Still open: Xenomorph Fuzz Mono is gone (Stereo, 556, stays); presets saved with NAM on 147/148
no longer open as NAM; no Amp > NAM entry; the knob order is Xenomorph's (Input, Bass, Mid,
Polarity, Treble, Presence, Model, Ch Vol, two unused); HX Edit shows the block as Xenomorph
Fuzz with its knob names; hx_smoke not run on it (it assumes 147/148).

## hx_smoke on the donor build (unit, 2026-11-03, from RAM)

`tools/hx_smoke.py` picks the NAM profile from the image (release 147/148, or donor 555: kind
1, Xenomorph's value types, Model 7th as a float; not an amp, so `amp_limit` checks NAM + two
amps load and three amps are refused). Donor v3: **48 pass, 1 skip (soak)**; the one failure
of the first run, `stress_model`, was the test reading Model at knob 0 (fixed, then PASS).
Recorded clean everywhere (no repeated block, dropout or click). Budget as the release: NAM x3
(6,825) + a 600-unit effect admitted, + 745 refused; NAM x3 + delay 88 (628) clean, 348 (730)
refused.

Levels, input open (the unit's noise floor only), User IR 4 = "NAM JP2C RHY", 5 = "NAM JP2C
LEAD", same session, back to back:

| blocks | release | donor |
|---|---|---|
| 1 x Model 4 | -71.3 dBFS | -72.3 |
| 1 x Model 5 | -65.7 | -65.5 |
| 3 x Model 5 | -28.4 | -26.9 |
| 3 x Model 4 | **-72.1, peak 0.000** (also 3 x 148 alone) | -43.8 |

That input was a guitar at volume 0, almost silence. Reamped with a fixed signal instead
(tools/hx_reamp.py: input block on USB 5/6, tools/play_mac.swift plucks, 110 Hz sawtooth, peak
0.3), both builds measure the same to 0.1 dB in every case, and three RHY blocks are not silent:

| blocks | release | donor |
|---|---|---|
| none (a gain block) | -19.8 dBFS | -19.8 |
| 1 x Model 4 (RHY) | -30.0 | -30.0 |
| 1 x Model 5 (LEAD) | -29.5 | -29.5 |
| 3 x Model 4 | -26.1 (147, 147, 148 and 3 x 148 alike) | -26.1 |
| 3 x Model 5 | -26.3 | -26.3 |

The difference at the noise floor is not audible in use; not chased. hx_smoke's click count
reports 0 or 2 on the same case run to run with the plucks (their onsets), either build.

## The 4-knob donor build (unit, 2026-11-03, from RAM)

`tools/nam_donor/build_mm4.sh` (MD5 e220d4f1 from stock 3.80.0): NAM A2 Lite as Distortion > NAM
on MM4 Frequency Shifter's id 461 (the stock model removed; Xenomorph Fuzz stays stock), four
knobs type for type on MM4's:

| # | MM4 (HX Edit) | NAM on the unit |
|---|---|---|
| 1 | Speed, float 0..3520 | Model, float 0..1000, shown as IR Select; 1..128 select a capture, the rest nothing (`<EMPTY>`) |
| 2 | Mode, int 0..2 | Polarity, int 0..1, Normal / Inverted |
| 3 | Mix, float 0..1 | Input |
| 4 | Level, float -60..6 | Output (Ch Vol), 0..1 |

No tone knobs: kernel `nam_multi.py --no-tone` (1,093 instructions, Block 2 7 words free) keeps
the tone stack a pass-through. The IR-name title reads knob 0, a float, out-of-range values to
the stock `<EMPTY>` (ir_title_knob.py). The unit steps a float knob by a size it picks from the
range: Model 0..100 stepped 0.2 a click, 0..500 0.5, 0..1000 1.0 (owner), hence 0..1000.

Unit: HX Edit drags with the logging copy (2 whole-preset writes, 5 moves) keep both NAM blocks;
reamped levels identical to the release (-30.0 / -29.5 single, -26.1 / -26.3 three); hx_smoke
48 pass, 1 skip (soak).

## No tone bands, DSP cost 2220, the XL (2026-11-03)

`nam_multi.py --no-tone` now also leaves the four bands out of the per-sample loop (32 of the
loop's instructions; 1,061 instructions in Block 2, 55 words free). The check's reference
(Pipe) leaves them out too: flat bands are not quite an identity, they turn -0.0 into +0.0
(the first check failed on exactly that, "differ by up to 0"). Both checks pass.

Meter (meter 2, the Amp > NAM 4-knob layout, back to back, two rounds each): 1 / 2 / 3 blocks
41.5 / 64.6-64.7 / 87.7-87.9% with the bands, 41.0 / 63.6-63.7 / 86.1% without: 0.57% a block.
dsp_cost 2275 -> 2220: three blocks free 165 units, at most ~1.65% of real load for the
dearest stock effects (~100 units a %), within the 1.7% saved.

HX Stomp XL: the same layout. Its title cave uses the XL's branch (read from its Entry 0):
layout byte in r6, slot in r8, ctx 0x28d95248, value 0x28e0aa8c, on at 0x28dc1f24, <EMPTY>
0x28dc1fcc (literal -> "<EMPTY>"), redraw 0x28dc28d6. The Python encoder matches the toolchain
for both units. Static checks only; never run on an XL.

Flash files: HX Stomp dcb425f1, XL 109caca2 (tools/nam_donor/build_mm4.sh).
