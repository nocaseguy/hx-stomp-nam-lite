# NAM A2 Full in the stock firmware: measured on the unit (2026-10-29)

Kernel: tools/sharc/nam_full.py + nam_full_kernel.asm (commit 0398311 and after),
nam_a2_ffa's arithmetic, bit for bit in ssim. Weights streamed from the instance's
SDRAM block into a FIFO in Block 2 (EP DMA ch0); the 12 layers with d >= 17 keep
their rings in SDRAM, staged into two buffers in Block 3 (reads ch0, write-backs
ch1). Images run from RAM (hx_ramrun.sh), the block put in the edit buffer with
hx_ctl.py, the meter read from the USB output (tools/nam_full_meter.py). Meter
images run the model in 1 call of 8, so each full call is real and the unit
stays up; the numbers are cycles of one full call (EMUCLK), 150,900 = the DSP.

| image (build_nam_full.py --meter ...) | cycles a call | read polls | write polls |
|---|---|---|---|
| normal (overlapped DMA, the plan) | 253k median (237k..315k) | 6,169 | 2 |
| --serial (each chain waited for at once) | 197k | 3,615 | 47 |
| --nodma (no DMA at all; output noise) | 109k | 0 | 0 |
| --noring (weights only, overlapped; rings noise) | 129k | - | - |

ssim for the same kernel: 104.4k instructions + 3.4k same-block conflicts = 108k,
so the compute itself is as predicted (109k on the chip).

What it means:
- The DMA, not the arithmetic, is the cost: about 88k cycles a block when the core
  only waits (serial), and more (144k) when it runs beside the compute: the
  DMA and the core slow each other, worst for the ring staging into Block 3,
  which the core reads nearly every cycle (weights into Block 2: +20k; rings: +124k).
- With the stock base load (19.8%, ~30k cycles) the budget for the kernel is
  about 120k. The compute alone is 109k; weight streaming alone already passes
  it (129k). The full kernel at 253k is about 190% of the DSP's time with the
  base: the unit crackles, the UI hangs, then USB goes (seen with the model in
  every call).
- At dsp_cost 8500 the block could not be added at all (9000-unit check with
  what an empty preset already counts); 4000 lets it in.

Verdict: A2 Full does not fit in real time inside the stock firmware with the
chip's free memory. Even with no DMA at all it would be ~92% (109k + 30k). Ways
that remain: a lighter model (fewer channels), or the own firmware
(hx-stomp-nam: the same kernel, all in internal memory, 71-72%).

## The Full-only long shot, measured (2026-10-31): no

The idea: Full the only block in its preset, taking the stock heaps' unused memory for its
weights and the d <= 41 layers' rings, DMA only for the six d = 101/239 layers.

Memory (hx-stomp-kit meter=5 heap map, one NAM block alone, 64-word chunks; nam_meter.py --map):
all-zero chunks Block 0 heap 236/304 (~15.1k words), Block 3 heap 117/139 (~7.5k, not stable
between sweeps), Block 1 heap 197/321 (~12.6k): ~35k in all, but in pieces: Block 0 ~830..896
words a small slot (13 slots each keep a few words at their start, period 942), Block 3 4,352
and 1,792, Block 1 3 x 1,472 and 704s. A d = 41 X ring is 3,408 contiguous words (x 3): only a
channel-split rewrite of the rings would place them.

Cost (build_nam_full.py --meter --bigonly: ring DMA only for d >= 101, the d = 17/41 layers on
stale staging buffers; model 1 call in 8): 153,377 and 153,655 cycles a call, against 254,015 and
253,387 for the 12-layer image in the same session. With the weights internal (-20k, --noring
on 2026-10-29) and Lite's compute tricks at best (-15k): 118..133k + the ~30k base = 98..108% of
the DSP for Full alone. Not a usable pedal; stopped here. Full needs the own firmware.

## The Full-only hybrid, built (2026-10-31): ~103% at best so far

The user asked to push it (Full alone, up to ~100%, no IR/cab). nam_full.py --hybrid: the six
d >= 101 layers stage by DMA; the weights (16.7k words) and the d = 17/41 rings (11.7k: ne = 3,
the largest 1,440) live in HYBRID_FREE (stock heap chunks a one-NAM preset leaves zero), copied
in at start-up (WCPY, one chunk a call); dsp_cost 7500 (build_nam_full.py --hybrid) keeps every
other block out. ssim bit for bit. Bass at 10 clears the stock tuner's detection flag each call
(the root call list scanned once for kernel 0x8e467).

On the unit (meter, model 1 call in 8), cycles a call:

| image | median | 10% .. 90% |
|---|---|---|
| hybrid, best-fit placement (weights partly in Block 3) | 132k | |
| hybrid, block-aware placement | 130.3k | 123.6k .. 139.7k |
| --wfifo (weights read from Block 2) | 129.2k | 122.7k .. 140.0k |
| --ringsb3 (the d = 17/41 rings in Block 3) | 130.0k | 124.4k .. 140.3k |
| --staged17 (all 12 long layers by DMA, weights home) | 157.9k | 145.1k .. 189.0k |
| proxy --bigonly --noweights (d = 17/41 layers on the staged path, no DMA: noise) | 116.0k | 115.2k .. 117.0k |

ssim models the same ~8.5k stalls for the hybrid and the proxy (conflicts ~4.0k, cache misses
~2.9k, loops 0.9k, fetch 0.5k, I-use 0.25k); the chip charges the d = 17/41 layers' ring path
~14k more than the staged path, wherever the rings or weights are: not explained.

With the base at ~25.5k (tuner detection off, KIT_BASE_LOAD.md section 7): median ~155k (~103%),
90% ~165k (~109%). Not run at full rate (an overload hangs UI and USB). Left: the unexplained
~14k, Lite-style stall trims (~3..4k), core-copied windows instead of the ring path for the
d = 17/41 layers (~5k net, a guess).

### The ~14k hunt, offline (2026-10-31, the Mac locked: no USB audio capture, so no unit runs)

Lead: DMA against the core in Block 3. ssim times DMA but never makes it compete for a block;
the unit does (weights in Block 3 beside the staging DMA cost ~16k). The hybrid's plan starts
SR5+SR6 at the top of the call, so the core runs layers 0-4 (their rings in Block 3) while the
DMA writes the Block 3 staging buffers; the proxy's plan starts each read late. A rough ssim
count of instructions touching the block of a running TCB, a call: proxy 12.8k, hybrid 18.8k,
hybrid --late 5 (the proxy's plan) 11.2k, + ABUF in Block 0 8.2k (what is left: the other
staging buffer 4.2k, the small rings ~2.2k, the head ring 0.8k).

Also found on the way (ssim, bit for bit, hybrid --late 5):
- ABUF in Block 0 (--abuf 0x97d6e): block conflicts 3,988 -> 2,308 a call.
- The odd pass and the 1x1 re-laid for the instruction cache (sets b and 4 of the odd pass and
  set 2 of the 1x1 each held three PM-data instructions): misses 2,910 -> 1,865, ~1.0k net.
- --bankaware (weights out of their layer's ring banks, 1x1 out of ABUF's): conflicts
  2,308 -> 2,088.
- --bankaware, then layers 10 and 19's A/BS put in Block 3 on purpose (their rings are in Block
  0 and they run before a read starts) and the K = 15 chunks placed first: conflicts -> 1,512.
- Not used: the head ring in Block 1 (--hring): DMA overlap 8.2k -> 7.4k but conflicts 2,472.
Together ~3.5k modelled (ssim 99.7k instructions + 1.5k conflicts + 1.9k misses + ~1.7k other),
and the unit's share of the DMA overlap unknown until measured.

Queued for the unit (tools/nam_full_meter.py --hist, with the poll counts): the hybrid as
committed, --late 5, --late 5 --abuf, + the cache layout, + --bankaware (all of it), and
--nodma (noise; what the DMA costs at all).

### The ~14k found: DMA waits (2026-11-01, on the unit)

Meter images (model 1 call in 8), cycles a call, median / 90%, read polls:
| image | median | 90% | polls |
|---|---|---|---|
| hybrid as committed (f98101d) | 130.5k | 140.3k | 192 |
| --late 5 | 115.6k | 115.8k | 0 |
| --late 5 --abuf + the cache layout | 112.6k | 112.8k | 0 |
| + --bankaware (all) | 112.3k | 112.6k | 0 |
| all, --late 9 | 111.8k | 112.0k | 0 |
| --nodma (noise) | 109.8k | 109.9k | 0 |
The hybrid's plan started SR5+SR6 at the top of the call: the reads ran beside the core's Block 3
work, slowed, and the core waited for them (192 polls). Started late, no waits and no spread.
Full rate (model every call, tuner off): 111.7k median, 111.9k at 90%; the stock idle word 7-10%
(two boots): **~90-93% in all**. Played; bit for bit in ssim.

### Beside other blocks: not safe (2026-11-01)

No stock effect would place on any image made by add-model alone (the bare entry, Lite's too:
every kind-1 write dropped the preset); Lite's add-fx-model step fixes it (build_nam_full.py
--fx-variant, preset 181). Then an EQ 128 or a gate 115 before Full: 6% idle; a cab 250: 4%.
But HYBRID_FREE is "zero with one NAM block", and a second block's instance comes from the Block
0 heap in creation order (the second at 0x9A6E9, inside HYBRID_FREE): a 252-unit EQ (preset 135)
in slot 0 before Full hung the unit (USB gone) at ~30% load. dsp_cost 7500 keeps every stock block
out; keep it. (Booting bare add-model images, model 147 without its kernel, with a boot preset
holding 147 also hung it.)

### The cheap effect inside Full instead (bed1753..ebe6cd6)

The hybrid has NAM A2 Lite's tone stack on Bass/Mid/Treble/Presence (4 biquads after the head,
coefficients from a DDR2 table on a knob write, coefficients and state after ABUF in Block 0):
~800 instructions a call, no stalls modelled; bit for bit against nam_lite.Pipe's arithmetic.
The tuner's detection is off always in the hybrid (Bass is the EQ's now); Treble at 10 is no
longer the meter there (--meter / --fullmeter images). build_nam_full.py --hybrid uses --late 9
--abuf 0x97d6e --bankaware by default.

On the unit (2026-11-01, after a power cycle; --fullmeter image MD5 686d0f84): 111.8k cycles a
call median at EQ all 5, all 10, all 0 and 8/3/6/2, the same as without the tone stack (111.7k):
the ~800 instructions fit in time the core spent waiting before. Stock idle 9-10%, so ~90-91%
total. The release-like image (MD5 6ddf945d) placed and the unit stayed up.

### Room for one stock block beside Full (2026-11-01)

The hang beside an EQ was the second block taking part of HYBRID_FREE. nam_full.py --probe (a
test image: no model; once a boot, armed by Bass at neither 0 nor 0.5 with Full alone, it writes
a canary over HYBRID_FREE, then plays per 64-word chunk how many words no longer hold it) mapped
it on the unit, one block a boot. HYBRID_FREE is untouched with Full alone. Of 17 block cases, the
only words taken are in the chunk at 0xB2E88 (Block 1): Simple Delays 77 (39 words), 79 and 80
(23), EQs 134 and 135 (15), compressor 124 (39); gates 122/361, EQ 131, modulation 155/163/179/
292, cab 690, volume 260 and reverb 496: none. Before or after Full, on or off, the same.
(A first probe re-armed on any new Bass value; adding delay 77 re-created Full with its default
knobs, the canary wrote over the delay and hung the unit: arm once a boot, never at defaults.)

--room N leaves N words at 0xB2E88 out of HYBRID_FREE. On the unit (full-rate meter, which now
counts the output loop too: the hybrid's meter comes after it, c8a0e28):

| room | cycles a call | idle, Full alone |
|---|---|---|
| 0 | 111.8k | 7% |
| 128 | 111.4k | 7% |
| 256 | 111.3k | 7% (6% in slot 1) |
| 624 | 112.2k | 6% |

Room 256 (6x the largest use), dsp_cost 7150 (admits a block up to ~360) and the add-fx-model
step are build_nam_full.py --hybrid's defaults now (MD5 65ec6e56). Beside one block, before
Full, on: Simple Delay 80 5% idle (~95%), EQ 135 5%, compressor 124 4%, chorus 155 2..4%. No
hang in any of these runs. Unproven: blocks not probed (any within ~360 units), two blocks.

### Room for two blocks (2026-11-01, later)

The probe (now re-armed by a rising Bass, many tests a boot; hx_ctl reads the notify stream, so no
31-write hang) mapped 79 cases: every single block of <= 470 units and Simple Delay 80 beside each
block of <= 138. Only three places are ever taken: from 0xB2E88 up to 199 words (stereo Simple
Delay 92; delay 85: 177; the rest <= 94), and with a second block 3 words in the chunk at 0xE1E48
(most) or 0x973E6 (an EQ second). --room 256 --room2 leaves all three free (ssim: +16 conflicts).
The tone stack now skips flat bands (all flat: -800 instructions a call).
On the unit (full-rate meter, knobs at noon): Full alone 8% idle (~92%); + Simple Delay + gate 5%
(~95%); + Simple Delay + EQ 132 5%. build_nam_full.py --hybrid defaults: --room 256 --room2,
dsp_cost 7040 (stock blocks up to ~470 together), --fx-variant (MD5 802b811f). No hang in any run.

### Three blocks, and the empty-slot lead (2026-11-01, later)

- A third block takes 3 words of the chunk at 0xE2008 (24 of 26 triples; nothing else): --room3.
  Every block of 471..600 units alone stays in the known spots (<= 119 words from 0xB2E88).
- On the unit with dsp_cost 6880 (the empty preset's overhead is 1,495..1,545, not 1,490: at 6930
  a 575-unit trio was refused): Simple Delay + gate + EQ 132 4% idle (~96%); delay + EQ + wah 4%.
- The empty-slot lead (KIT_BASE_LOAD: 16 slot wrappers 0x600004, ~890 cycles each, always run) is
  wrong on this unit: nam_full.py --dump (a read-only probe build: the active call list, down to 3
  levels, as audio) shows the root's 97 active entries without members 144..159. The slots that
  run are 12-member composites (root members 60, 70, 82; 60 holds Full's host composite), and an
  empty one runs 7-8 gains and taps (~300-400 cycles). Skipping them would save < 1k: dropped
  (the --skipslots test, 9fcc9fb, removed).

### Re-cost, stage 3 on the unit (2026-11-01, evening)

recost.py on stage 2's corrected summary (c8192e2), noise margin 25 units, factory-knob-only
models never lowered: 13.29 cycles a unit, 122 costs raised, 68 lowered, 73 kept; window 552
units (worst predicted 96.9%). full_combo_test.py (combo_fm.l6ia, MD5 b87fb669, Full at 6903),
one fresh boot and one preset write per set, full-rate meter:

| set | cost | predicted | measured |
|---|---|---|---|
| 414 / 432 / 81 alone | 546 / 543 / 530 | 96.7-96.8% | 97 / 98 / 97% |
| 402+274, 402+163, 285+119 | 551 / 551 / 537 | 96.9% | 98% each |
| 160+274+300, 160+300+163, 319+274+163 | 551-552 | 96.9% | 97 / 97 / 98% |
| Simple Delay 80 + gate 122 + EQ 132 | 392 | 95.4% | 96% |
| 80 + stereo Simple Delay 92 | 568 | 97.0% | 98% |
| gate 122 + EQ 132 | 204 | 93.7% | 95% |
| 80+690+266+122 (600), 414+527 (611) | over | - | refused |

All placed sets alive, worst 98% (2% idle): measured runs about 1% over predicted. 80+92 at 568 was
admitted at 6903: the empty preset's overhead is ~1,495, the low end. recost.py now uses 1,495, so
Full's cost is 6953 for the same 552 window.
Not covered: four or more blocks (the window admits cheap quads; their memory beside Full has never
been probed). The pass-overlap branch measured 111,984-112,016 cycles a call against 111,327-111,348
(+660; ssim said -790): dropped. Section meter (unit minus ssim, per layer): +300..+800 every layer,
+12.1k a call; d = 239 layers +630..806, d = 101 layers +306..480.
Section meter with --nodma (same day): 107,645 cycles a call against 111,423 with DMA, so the DMA
costs the core ~3.8k (not ~2k). The cost sits in layers 6, 7, 13, 14 and 22 and the head (375-441
each), with 100-240 in layers 2-4, 9, 10, 18, 19 and 21, and ~0 in layers 0, 1, 5, 8 and 15-17. The
d-dependence above is the DMA. Without it every d = 1, K = 6 layer runs 4,253 (ssim 3,946): a flat
+307 a layer, the cache and conflict floor.

### Four and five blocks (2026-11-01, night)

The canary probe (non-hybrid probe image, MD5 cbcf1095) on 38 quads and 2 quints of blocks <= 300
units, all alive: a fourth block takes 3 words of the chunk at 0xE2208 (33 of 38); a fifth 3 at
0xE23C8 and 31..55 at 0xB3C48 (both quints). Nothing else. **The three-block layout was not safe for
four**: A19's weights ran to 0xE220A, ring 4.0 starts at 0xE22C8 (over 0xE23C8), BS20's weights at
0xB3C48, and the cost window admits cheap quads. --room4 (0xE2208..0xE2278) and --room5
(0xE23C8..0xE2600, keeping room for an unprobed 6th/7th, and 0xB3C48 +128) are build_nam_full.py
--hybrid defaults now. ssim: bit for bit, the same 100,296 instructions, conflicts 1,720 -> 1,912 (all
from the 0xB3C48 carve: that run was full to 42 words).
Conflict calibration (hx-firmware-10's --calib, branch full-calib 138765b; section meter): 256 DM+PM
dual reads in one block vs split over two cost 2,337 vs 2,082 cycles, i.e. **1.00 chip cycle a
conflict**, as ssim models it. So the pass-overlap branch's +660 on the chip was not its +860
modelled conflicts (likely its drain stores against the staging DMA in Block 3), and room5's +192
conflicts cost ~192 cycles.
Stage 3 on the five-room layout (combo_fm MD5 73b8e9e1, Full 6953): every placed set alive at
97-98%, including Simple Delay 80 + gate + EQ + wah (4 blocks, 97%) and two 5-block sets (98%). Sets
of 548-552 units were refused: totals <= 7,490 are admitted, 7,504 refused, so the overhead is
~1,510. recost.py now uses 1,510: Full 6938 for the 552 window. The room4/5 layout runs ~111.7k a call
(+400 over the three-room layout).
best_fit fix (hx-firmware-10, cherry-picked): keys kept out of the spill's banks are placed first too,
so staged layers' weights stop landing in Block 3 beside their rings (A21, A22 out). ssim conflicts
1,912 -> 1,439. Chip, Full alone, three alternating rounds: 111,758 / 111,747 / 111,569 -> 110,772 /
110,760 / 110,766 (-930, better than the three-room layout's 111.3k). DMA-quiet (SR reads moved into
low-Block-3 layers): 111,328 -> 111,315, noise; its section meter shows the cost moving with the
reads (L2/9/18 -128, L3/10/11/19/20 +70..98): the DMA costs per word (~0.35 a read word, ~1.2 a
write-back word), wherever it runs. Dropped.
Stage 3 at Full 6938 on the fixed five-room layout (combo_fm MD5 d2937f27): all 15 admitted sets of
1..5 blocks (recost.py's three worst of each size 1..4, two quints, delay+gate+EQ+wah) 96-98%, all
alive; 568 and 611 refused. build_nam_full.py --hybrid now defaults to dsp_cost 6938 and the
re-costed stock models (tools/full_stock_costs.txt, 190 changes; --stock-costs keeps Line 6's): the
default fullmeter image is byte-identical to the one tested.
Blocks 0 and 1 are 64k words on the chip (hx-firmware-10's stall scan: the L0/L1/L8 +113 were 112
DM 0x12 / PM 0x13 pairs a call, the 1x1's ABUF reads against W1 weights). --calib xbank (DM
0x970e6.., PM 0x98226..) vs split: 2,337 vs 2,085 = 0.98 a pair on the chip: ssim's conflict rule
is now mem_block = a >> 17 (27c0a31; the shipped layout counts 2,504, not 1,439). ABUF moved to
Block 1's free 0xb3308 (--abuf 0xb3308, the default now): ssim 2,504 -> 2,136; chip 110,802 /
110,700 / 110,729 -> 110,487 / 110,446 / 110,402 (-300).
Release candidate (build_nam_full.py --hybrid -o, payload MD5 1d2e274b; fullmeter twin b9858826):
stage 3 again, all 15 admitted sets 96-98%, alive, 611 refused; the release image RAM-booted with
Full + Simple Delay 80 + gate 122 + EQ 132 + wah 266 in one write, then Full alone: placed, alive.
If Line 6's costs were kept instead (typical load), the same 97% peak target allows a 319-unit
window (Full 7171), not 552.

### Pass overhead: the next pass set up in each pass's drain (2026-11-01, night)

Branch full-overhead (eab16e8, merged into nam-sharc). Each 4-sample pass used to spend about 12 (1x1) or 13
(even) instructions outside its multiply-adds, filling and draining the multiply/add pipeline. The 1x1
now brings the residuals in through the product registers (sums start at 0, then 0 + r and the products in
order: the same sums, signed zeros too). Its drain loads the next pass's residuals in instructions with no
DM access and stores while clearing its sums, so a load never pairs with a store. hx-firmware-10's earlier
overlap (be87209) paired them: +860 conflicts, +660 cycles on the chip. The next pass's data and weights
go in the last group's free slots. That's 8 instructions outside the multiply-adds, was 12. The even pass
does the same, 10 instead of 13. sync moved to the cold code because the larger hot code had pushed layer
15/16 weights into conflicts. tools/sharc/nam_full_icache.py placed the padding NOPs. ssim: -1,436
instructions a call; stall model (nam_full_stalls.py) -1,181.
On the chip (hx-firmware-dc, three alternating rounds, Full alone at full rate): 110,478 / 110,452 / 110,495
-> 108,920 / 108,716 / 108,866, **-1,641 a call**. Section meter: every layer gains (-28 to -192, layers 15/16
the most), the staged layers too, so the drain's stores don't fight the staging DMA. Full alone ~91%.
Then (14a9857, not yet on the chip): the odd pass's drain clears the next pass's first sum and product,
stall model -116, inside the chip's round-to-round spread.
Dead ends: odd-pass S-ring reads through another I register. Only I1 loads are broadcast (BDCST1), so
191 of 192 outputs differed. The 3-way fast FIR nets ~1k at best: 6/5/5-sample classes need partial
passes, and there are more pre-sums and recombining adds. What is left outside the multiply-adds is mostly
arithmetic the model needs (bm/A/B combines, activations, head sums, residual adds), so further kernel
overhead work is worth a few hundred cycles at most.

### At most four blocks (2026-11-01, late)

More canary probing (non-hybrid probe image, dsp_cost 5800 so cheap sets fit): 24 sets of 6-7 blocks
hit 16 places, 11 of them on Full's data (rings 11 and 20, weights BS10/13/17/19, A19); 24 more sets
of 5 blocks hit ring 11 (64-77 words, 7 sets), 0xB3C48.. up to 135 words (past room5's 128) and A19
(up to 32 words, 14 sets). Four blocks: 38 + 8 heavy quads (recost's worst 3/4-block sets among them)
all inside the rooms. The window admits six cheap blocks, so the release candidate before this was
not safe. Fix: build_nam_full.py --max-blocks 4 (default) raises every other model's dsp_cost to at
least (9,000 - 1,495 - Full's) / 5 + 1 (patch_amp.py set-cost --floor), so a fifth block never fits.
With the pass-overlap kernel (Full ~91%, eab16e8/14a9857), recost.py --full-load 91 gives a 660-unit
window: Full 6830, floor 136.
Stage 3 at Full 6830, floor 136 (combo_fm MD5 21f1dbbe): all 11 admitted sets of 1..4 blocks 96-98%
(worst block 99%: 319+119+159), alive; both five-block sets and 506+122 (794) refused. A cab beside
Full (711) raises Full's own cycles to ~111.3k (vs ~109.3k). Release candidate 2 (payload MD5
3d4c187e): ssim bit for bit; RAM boot + Full with Simple Delay/gate/EQ/wah, then alone: placed, alive.
