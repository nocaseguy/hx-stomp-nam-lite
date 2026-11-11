# Making stock effects cheaper with bit-identical output (HX Stomp 3.80.0, SHARC)

Feasibility study, 2026-11-01. Static only: listing, prim table, the ARM
cost table. Nothing has run on the unit.

Labels: **verified** (read in the listing/tables or measured earlier, cited),
**likely** (one inference step), **guess**.

## Verdict

Feasible, but the cheap wins are not in rewriting kernels.

1. **"Uses less DSP" means two things.** The unit admits a block by a static ARM
   number, `dsp_cost` (Table 1 word 3, cap 9000 a DSP, KIT_EFFECT_HOSTS 10)
   **verified**. Real cycles decide whether audio breaks up. Faster code alone gives
   the user nothing until that model's `dsp_cost` is lowered too. Lowering a
   `dsp_cost` that is set too high changes no output bit at all.
2. **Step 1 is to measure, not to optimise.** Sweep every stock model over USB
   (hx_ctl + load word; tooling exists, KIT_UNIT_MEASUREMENTS / hx_smoke) at its
   worst-case parameters, and compare measured cycles with `dsp_cost`. Any model
   whose `dsp_cost` is above its real load is a free, exactly bit-identical win
   (patch Table 1). Nobody has measured how much margin Line 6 left. **guess**: 10-30% on some models.
3. **Kernel rewrites: small gains, high cost.** 173 of the 177 primitive kernels are
   48-bit ISA code **verified** (prim_table), and what was read is hand-pipelined
   (the biquad at sw:182876: 5 instructions per section per sample, multiply and add in
   parallel with the loads) **verified**. SIMD is already used in about 90 places
   **verified**. Per-kernel headroom is probably in stalls (PM-data cache, block
   conflicts, SDRAM) rather than in instruction count. For NAM, the chip took 11% more
   cycles than instructions (tools/sharc/README). **guess**: 5-15% per kernel.
4. **Stereo as SIMD is the one big kernel-side lever, and it is hard.** Stereo models
   cost 1.4-1.9x mono **verified** (cost table). Where a stereo model runs two mono
   instances back to back, running PEx/PEy on L/R gives the same IEEE ops per channel,
   so the output stays bit-identical. That could save 25-40% on those models
   **guess**. But SIMD pairs word X with X+1, so the two instances' state has to be
   interleaved. The fn_ctrl callbacks that write coefficients into I0/I8 would then
   need patching, and so would the composite's member records. Not yet checked: how
   many stereo models are really two instances.
5. **Graph overhead is small for each effect.** About 12 dispatcher cycles per active
   member (KIT_BASE_LOAD 3) **verified**. A 30-member preamp spends about 400 cycles a
   block there, about 3-4% of a median model (~750 units, ~13-15 cycles a unit). Fusing
   unity gains and copies into neighbours is bit-identical, but each fusion is a
   graph-editing job in Blob 0.
6. **Memory: little to gain without changing output.** Whole slot budgets are carved
   when the graph is built (current == end for all nine arenas with one block,
   KIT_UNIT_MEASUREMENTS) **verified**, and there is no ARM memory admission
   **guess** (KIT_DDR2_BUFFERS). A model asking for less memory only helps in the
   combinations that fail on a chunk (the A2 Full room probe, nam-a2-full). Delay lines
   are sized for the longest time the user can set, so cutting them changes behaviour.
   Real candidates are only requests larger than what the kernel ever touches. Finding
   them needs a probe that scans for untouched words, which does not exist yet.

## Rules a bit-identical rewrite must keep

- The same float operations in the same order per sample: SHARC add/multiply are
  rounded one at a time, and a multifunction instruction is two rounded ops, so it
  can be scheduled freely but not re-associated.
- MODE1 rounding/truncation, RND32 vs 40-bit (stock code toggles MODE1 bits,
  e.g. `BIT CLR MODE1 0x10000` at sw:18290b), and ALU saturation / flush-to-zero as the
  original sets them.
- RECIPS/RSQRTS seeds are the chip's table (recips_table.json). Keep the same seed and
  the same Newton steps. Never swap in a divide.
- The same layout of the I0/I8/SDRAM blocks, because ARM-side fn_ctrl and parameter
  writes poke into them. Smoothing ramps and LFO phase keep advancing in the same
  order.
- The same block-boundary behaviour (16 samples) and the same handling of member
  `flags` / bypass.

## Verification path (needed before any of it)

- **On the unit, A/B in a shadow.** A kit module that, each block, copies a stock
  instance's input and state, runs the stock kernel and the candidate on separate
  copies, and counts output/state words that differ. It reports over the probe
  channel like kit-probe. This is the only check that covers VISA library callees
  and real stalls. The kit already places and calls custom kernels.
- **ssim.** It models 48-bit ISA only (no VISA decoder) **verified**, and the biquad
  above is a VISA callee, so most kernels cannot run whole in ssim today. The
  JP-2C work used lockstep and probe bisection (tools/jp2c/s7_lockstep.py,
  jp2c_probe.py), which is the template.

## Deployment limits

- In-place rewrite in E2, the same size or smaller: simplest and safe for memory.
  Unrolled or SIMD code is usually bigger.
- Free internal code: about 240 scattered 48-bit instructions, the largest run 57
  (KIT_FREE_MEMORY) **verified**. NAM Lite already fills its share. DDR2 has room,
  but ISA code running from there is unmeasured and probably slow.
- Every changed model needs its `dsp_cost` cut by the measured saving, and its
  worst case has to stay under the load that played clean (update-dsp-cost rule).

## Suggested order

1. A USB sweep: measured load against `dsp_cost` for all 823 cost entries, worst-case
   params, unattended (hx_ctl). Output: a table of over-costed models.
   Bit-identical by construction.
2. A kit-prof cycle profile of the 10-20 most-used heavy models, broken down per
   primitive, to see whether stereo double instances, stalls or overhead dominate.
3. Only then pick one kernel (likely a widely shared biquad/delay primitive or a
   stereo pair) for a shadow-verified rewrite.

## Stage 1 measured (2026-11-01, `tools/stock_cost_sweep.py`, cb6b260)

What was measured: the stock load word, factory knobs, silence in, each model alone with Kit Probe
after it. The image was stock + kit-probe + kit-fx-gain. An image that adds only an amp model makes
the unit drop every stock kind-1 effect, and after one drop the boot drops the following writes
too. 263 models placed, 263 measured, none dropped. The base was 20.9-21.4% over 9 RAM runs.
Results are in `build/stock_cost_sweep.json` (format in the script's docstring) and the table in
`build/stock_cost_sweep.report.txt`. **verified** (on the unit).

- **Median 13.4 cycles a dsp_cost unit** over the 260 models with cost >= 100. Line 6's costs
  track real load closely for most models: amps 14.6, reverbs 14.6, delays 13.5, drives 13.0,
  modulation 12.9 (category medians).
- **21 models measure more than 25% below their cost** at factory/silence. Cost and fair cost
  (at 13.4 cycles a unit) for each:
  - 786 dynamics: 2200 -> ~577 (a feedback simulator, signal-dependent);
  - eq 130, 131, 134: 217 / 244 / 271 -> 81 / 139 / 147;
  - wahs 266-274: 128 -> 68-90;
  - filter 300: 280 -> 139;
  - dynamics 123, 557, 597: 150 / 450 / 300 -> 89 / 310 / 205;
  - Simple Delay Mono 80: 332 -> 178, with factory TempoSync on, so its Time knob is not used;
  - six cabs: 250 -> 174-187.
- **15 models measure more than 25% above their cost**:
  - reverbs 238 / 248: 1338 / 1350 -> ~1947;
  - reverb 493: 1300 -> 1644;
  - delays 76 / 81: 564 / 478 -> 709 / 649;
  - distortion 389: 910 -> 1241;
  - modulation 391: 170 -> 246;
  - eq 129 / 132: 182 / 128 -> 323 / 192;
  - six cabs: 250 -> 316-374.

  So a preset built of these can run past what the cap stands for on stock firmware as well.
  Any plan that relies on their declared cost, for example next to NAM A2 Full, should use the
  measured one.
- Cabs all declare 250 but measure 174-374.

Not a safe cost yet: these are averages with factory knobs and silence. Stage 2
(`tools/stock_cost_peak.py`: Kit Prof per-block peaks, Kit Noise signal, knob corners) is
running. Its first run on the unit passed (Kit Prof and Kit Noise held, B max ~14.3k, load ~22%).

## Stage 2 measured (2026-11-01, `tools/stock_cost_peak.py`)

What was measured: Kit Noise (-12 dB white noise) first, then the model, then Kit Prof, on stock
+ kit-prof + kit-noise from RAM. Each model was run at its factory knobs with and without signal,
plus up to 7 knob corners for the 215 models whose Entry 3 layout matched. 263 models, 1,766
points, none dropped, run unattended. Base peaks were 14.3-15.3k over 47 RAM runs. **verified**
(on the unit).

What the measures mean (learned on the way):
- Kit Prof's B (cycles from the block start to its call) sees only work done before it in the
  block. Pitch 620's B rose 9.2k, while the load word rose 22 -> 58% (+54.5k). Its work runs
  after Kit Prof's call. So the B delta alone under-states such models badly.
- The B-mean delta reads ~1-1.2k high for small blocks: adding a block moves Kit Prof one slot
  on, so that slot's plumbing comes before its call.
- So **worst cycles = max over points of max(load delta x 1,509, peak delta)**. A peak more
  than 3k over its own mean is a transient (three of them: cab 687's 24.7k right after a preset
  write, likely its IR loading). Transients are listed, not counted.
- Signal matters. 786 (feedback sim) was 7.7k at silence and 30.2k with noise, so 2200 is
  honest. Stage 1 had made it look 74% over-costed.

Results (`research/stock_cost_stage2.txt`, per-model `research/stock_cost_stage2_summary.json`):
median 13.2 cycles a unit. Stage 2 against stage 1: median 1.00, but more than 1.25x for 21
models. At 13.4 cycles a unit:
- **21 over-costed by more than 25%**:
  - EQs 527, 130, 131: 200-244 -> 64-112;
  - dynamics 123, 597, 557, 122, 361;
  - filter 300: 280 -> 155;
  - Simple Delay 80: 332 -> 187, with TempoSync off and Time at its corners;
  - modulation 163, 293, 159;
  - wahs 266-268: 128 -> ~80;
  - distortion 525: 650 -> 470;
  - four cabs (factory knobs only).
- **23 under-costed by more than 25%**:
  - reverbs 238 / 248: ~1,912 / 2,026 against 1338 / 1350;
  - modulation 393: 1410 -> 1803, and 167, 179, 295;
  - pitch 182, 183, 296, 299;
  - delays 85, 348, 404, 489;
  - distortion 98, 388;
  - preamp 501: 1850 -> 2313;
  - dynamics 120, 124;
  - eq 129, wah 269;
  - cabs 711, 795.

Still lower bounds: the 48 factory-only models, the moment of a knob change or model switch,
and blocks together. Stage 3 (the other session's `full_combo_test.py`) plays the combinations
a re-costing admits.
