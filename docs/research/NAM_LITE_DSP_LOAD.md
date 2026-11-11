# NAM A2 Lite on the chip: cycles and DSP load (measured on the unit, 2026-10-30)

Meter image: hx-stomp-kit `kit.py build STOCK nam-a2-lite --ir-title --opt nam-a2-lite.meter=1`
(dsp_cost 2200 for the test, so a third block would pass the budget check), RAM run. A block
with Treble at 10 plays its call's cycles (EMUCLK) and the stock idle word (DM 0xC2FD5) as
levels; tools/nam_meter.py reads them from a 6 s USB recording. Model slot 4 (a real
capture) in every block; nothing else in the preset.

| blocks | metered block, cycles a call | DSP load (idle word) |
|---|---|---|
| 1 NAM | median 41,323 (99%: 46,231; max 49,869) | 49.0% |
| 2 NAM | median 41,327 (99%: 46,128; max 49,467) | 77.6% |

- Empty-preset base about 20% (KIT_BASE_LOAD: 19.8%, ~30k cycles). Each NAM block about
  28.6% (~43k cycles: the call plus its graph overhead).
- ssim says ~27.9k instructions a steady call; the chip takes ~41.3k, about 1.5x. (Not
  mostly the DMA: see "Where the cycles go" below.) These two rows are a meter image whose
  extra code pushed the staging buffers into Block 3; the release layout is a little cheaper.
- **Three blocks would be ~106% of the DSP**: they do not fit, whatever the browser
  category (AMP_LIMIT.md: a Distortion copy passes the 2-amp limit but not this). Not run:
  the overload hangs the UI/USB (the audio kept going in the one hang seen).
- The budget check: base ~2,300 units (drops at 2x2700 + 1,300 or more, 2x2700 + 1,250
  passes), so the 9,000-unit cap is ~13 cycles a unit, ~78% of the DSP above the base.
  With two NAMs (7,700 units, 77.6% real) the ARM still admits ~1,300 units (~13%), i.e.
  up to ~90% real. dsp_cost 2700 is a little under the measured ~28.6% (~2,850 at
  ~100 units a %).

A third block needs the kernel at or below ~30k cycles on the chip (with no other block),
i.e. the DMA/SDRAM overhead (~13k) mostly gone, or fewer far layers in SDRAM.

## Where the cycles go (release layout, 2026-10-30)

The small meter (`--opt nam-a2-lite.meter=2`: every NAM block plays the idle word; 6
instructions, so the staging buffers stay in Block 2 as in the release image), read with
`tools/nam_meter.py --idle`. One RAM run each; 1 block, then 2; Model slot 4 in both.

| image | 1 block | 2 blocks | a block |
|---|---|---|---|
| release kernel (staging Block 2) | 47.2% | 74.1% | **26.9%** (~40.6k cycles) |
| `nodma=1` (no tap staging, no write-back DMA; output wrong) | 42.9% | 65.4% | **22.5%** (~34k) |
| `staging=b3` | 49.1% | 78.0% | 28.9% |

- The DMA (setup, waits and its contention) is only ~4.4% a block (~6.6k cycles).
- The compute alone is ~22.5% on the chip (~34k cycles), against 24.3k instructions in
  ssim for the same nodma kernel: ~1.4x. So most of the chip/ssim gap is in the core:
  stalls ssim does not count (DM/PM same-block conflicts in the tap loops, where the short
  rings, X and HS share Block 3 with the weights; branch and load-use penalties).
- Staging in Block 3 (beside the weights) costs +2% a block: block conflicts are real.
- Base (empty preset) ~20.3%.

Three blocks at <= ~90% need <= ~23.3% a block. Even with no DMA at all a block is 22.5%,
so the DMA alone cannot get there: the core's stalls (~10k cycles a call) have to shrink
too, i.e. the tap loops' DM and PM operands in different blocks, which the full Block 2 /
Block 3 memory makes hard.

## Section by section (step 1, 2026-10-30)

Section probes (`--opt nam-a2-lite.prof=A-B`: EMUCLK stamped at A and B, the difference
played at unity gain, `tools/nam_meter.py --cycles`; at most 11 instructions, the release
layout kept), one RAM run each, one block, Model slot 4. ssim's count of the same span,
and `tools/sharc/nam_stalls.py`'s modelled extras (HARDWARE.md costs):

| section | chip | ssim | chip - ssim | model: conflicts / I load-use / cache misses / loops |
|---|---|---|---|---|
| pre (slot, knobs) | 706 | 152 | +554 | 0 / 13 / 0 / 1; the rest ~20 core SDRAM reads (the model's signature check, every call) |
| input | 278 | 228 | +50 | 0 / 6 / 1 / 3 |
| **layers** | **35,242** | **26,498** | **+8,744** | 3,552 / 408 / 1,777 / 340 = 6,077; the rest branches and DMA contention |
| head | 1,144 | 643 | +501 | 440 / 25 / 8 / 12 = 485 |
| mix + tone stack | 1,020 | 682 | +338 | 128 / 0 / 113 / 1 = 242, plus HIST's SDRAM writes |
| end wait | 87 | 46 | +41 | |
| **total** | **38,514** (parts 38,477) | 28,244 | +10,270 | |

Where in the layer loop (per call):
- conflicts: the near layers' tap reads `DM(I0..I2)` (rings in Block 3) beside the weights'
  `PM(I9)` (Block 3), ~2,000; `n_put` writing x into the near rings, 576; the per-pair
  epilogue's X and HS (Block 3) accesses beside PM weight reads, ~740.
- cache misses: 9 instructions of the pair loop miss on every pass (184 passes), ~1,700:
  the loop has ~30 PM-data instructions and some cache sets get 3+.
- DMA: its bookkeeping is ~3.6k instructions a call (ssim with vs without), the rest of the
  4.4% (6.6k cycles) waits and contention.

What could come off (estimates), against the ~5.4k cycles a block three blocks need:
| change | saves | risk |
|---|---|---|
| pair loop laid out so no cache set holds 3+ PM-data instructions | ~1.7k | low (reorder / pad) |
| model signature check every N calls instead of every call | ~0.5k | low |
| I-register load-use: reorder the loads | ~0.4k | low |
| lighter DMA bookkeeping (pump calls, TCB rewriting) | ~1-2k | medium |
| X and HS out of Block 3 (run-once code to block 0's free holes to make room in Block 2) | ~0.7k | high |
| near rings out of Block 3 | ~2.6k | no room |
So ~4.3-5.3k reachable: three blocks at ~90-94% at best, borderline.

## The three low-risk fixes (2026-10-30)

In the kernel (hx-stomp-kit modules/nam-a2-lite/src, copied to tools/sharc here and to
hx-stomp-nam-lite; all three build the same image again, Stomp 939b1dfe..., XL 55b3df60...):
1. The pair loop's two "+0" steps merged into the weight reads before them, and 2 NOPs in
   its epilogue: no instruction-cache set holds 3 PM-data instructions of the loop (was 3
   sets with 3, 9 misses a pass). Same length (47).
2. The model's signature check (~20 SDRAM reads) only after a knob write, with no model
   known (P_SIGN zeroed with S_SIG in m_init and n_zero), or every SIGCHK_N = 64 calls: a
   capture replaced in its slot loads within 64 calls (KernelCheck step capture_replaced).
3. I-register loads moved away from their first use (pump's I5, n_put's I8, fcopy's I5,
   p_next's I5). No instruction added.
Code +10 instructions: Block 2 keeps the staging buffers (2 words left; nothing else fits
beside the release kernel now, nor the meter=2 image: measure with staging=b3).
nam_stalls.py: misses 1,899 -> 274, I load-use 454 -> 120 a call; output bit for bit.

On the unit (meter=2, staging=b3 for both, as the release layout has no room for it):
| kernel | 1 block | 2 blocks | a block |
|---|---|---|---|
| before | 49.1% | 78.0% | 28.9% |
| after | 47.9% | 75.4% | 27.5% |
-1.4% a block (~2.1k cycles; the model said ~2.5k). In the release layout that is
~25.5% a block, two blocks ~71%, three ~97%: still not three.
The release image ran from RAM with two blocks (alive, output at the input noise level).

## Layout work and three blocks (2026-10-30, hx-stomp-kit f7281cf, 6c4cc29)

The stall model gained the fetch conflict: an instruction without a PM data access is
fetched from its own block, so its DM access to that block costs a cycle (HS in Block 2
cost ~1.1k this way, measured; the model then predicted the next layout to 0.0%).

| kernel (release layout, meter=2) | 1 block | 2 blocks | a block |
|---|---|---|---|
| morning | 47.2% | 74.1% | 26.9% |
| + 3 low-risk fixes, cold code in Block 3, X/HS/IN in Block 2 | 46.1% | 71.9% | 25.8% |
| HS back in Block 3, fcopy reads X through PM | 45.5% | 70.6% | 25.1% |
| + near layers' weights copied to WBUF (Block 2), fcopy SIMD | 45.0% | 69.7% | **24.7%** |
| (WBUF put in Block 3: copy without the conflict gain) | 46.2% | 72.1% | 25.9% |
| (the copy in two registers by turns) | 45.0% | 69.7% | 24.7% |

The copy costs ~0.8% on the chip, ~2x its instructions; not a load-use stall (the
two-register form is no faster). Likely the near layers' weight reads in Block 2 slowing
the DMA into the staging buffers (Block 2), not measured.

Three blocks (RAM run, dsp_cost 2200 for the test so the budget check lets them in; two
NAM A2 Lite + the Distortion entry, preset_id 148, all on a real capture):
**95.5% load**, idle 1% low 4.4% over 24k blocks, the unit responsive. They run, but
past Line 6's own margin (the 9,000-unit cap is ~90% here), and only with a dsp_cost
under the real ~2,470 units a block, which would let other combinations overload.

Listening test (same image without the meter, RAM run, 147 slot 4 + 147 slot 5 + 148 slot
4, the user playing): 20 s recorded from USB with no repeated block, dropout or click
(the scan finds a planted repeated block and a 2 ms dropout). Then the user picked a
heavy delay in the browser: the budget check, fooled by dsp_cost 2200, let it in, and the
unit hung (UI and USB; power cycle). So three blocks play cleanly alone, but at ~95% there
is no room for anything else, and an honest dsp_cost (~2,470) keeps the third one out.

## Shipped (2026-10-30): two blocks, dsp_cost 2500

hx_firmware 16401be, hx-stomp-kit a309d2c, hx-stomp-nam-lite 79920b6: the 24.7% kernel,
dsp_cost 2500, the same images in all three (Stomp a819de1c, XL 44102876). The Distortion
entry is a stash in the kit, not shipped. On the unit (RAM run of the release image): two
blocks load and play (recordings clean); next to them the budget admits a 1,250-unit
distortion and refuses a 1,920-unit delay. A 1,300-unit stock reverb (493) is refused next
to two NAM blocks as it was with the old kernel: something other than the DSP cost (memory,
likely), not looked into.

## The budget, calibrated, and three blocks honestly (2026-10-30, kit e7d1b9a)

Correction: the "reverbs and delays refused next to two NAM blocks, then a hang after a few
refusals" seen earlier today was hx_ctl's doing. Its set-model cannot place a kind-8 block
(delay, reverb): the unit drops even a bypassed one alone in an empty preset with a factory
preset's values. A few such malformed edit-buffer writes in a row then hang the unit (the
installed firmware too). The unit's own UI never sends them. Not a NAM or memory bug.
(Fixed 2026-10-31: the malformed part was the value list's key-3 count. Kinds 8, 9, 15 and 16
count one less than they list (every such factory block), and hx_ctl wrote the full length.
With that count set_model rebuilds all 679 non-cab factory blocks byte for byte, and on the
unit 3 NAM + mono Simple Delay (80, 332) loads and records clean, + stereo Simple Delay (92,
455) is refused, and a reverb loads alone. hx_smoke covers delays and reverbs now.)

Calibration, on the 24.7% kernel, meter=2, NAM last (real load added / declared cost):
distortion 521 +13.0% / 1,250; drive 566 +7.9% / 800; drive 443 +4.0% / 440: ~100 units a
1%. NAM 24.7% / ~2,470. The empty preset is 20.6% real but counts 1,476..1,500 units
(probes with kind-1 blocks: 2 NAM at 2500 + 2,500 declared loads, + 2,525 is refused). So
the 9,000 cap sits at ~95.7% real for any preset (7,490 declared measured 94.2%).

With dsp_cost 2500, three NAM blocks (the third the Distortion entry) declare 7,500 and fill
the budget exactly: ~95.5% real, the browser greys out everything else (the heavy delay
that hung the dsp_cost-2200 test included). On the unit (RAM): 20 s of playing with a Model
switch and a block moved to path B, no repeated block, dropout or click.

Ported (2026-10-30): hx_firmware ccc95a9 (build_nam.py), hx-stomp-nam-lite 0f31004 (build.py,
web builder): patch_amp.py add-fx-model through tools/kit_patch_amp.py (a verbatim copy of the
kit's patcher). All three build the image the unit played: Stomp d119ad50, XL 8c264d78.
Next target (user): room for a simple delay beside three blocks, ~300-400 units, i.e. each
block ~1.2% (1.8k cycles) cheaper and dsp_cost lowered to match.

## Looking for room for a simple delay (2026-10-30, not found yet)

Target: the Simple Delay Mono is 332 units; beside three blocks that needs dsp_cost <= ~2,389,
i.e. a block ~23.6% real (now 24.7%): ~1.65k cycles a call. Tried on the unit (meter
images, release layout; shipped kernel 45.0% / 69.7% for 1 / 2 blocks):
| change | 1 block | 2 blocks | |
|---|---|---|---|
| WBUF copy from even addresses (odd first word alone; WBUF even) | 45.4% | 70.2% | worse, reverted |
| copy loop unrolled to 4 moves a pass (short-loop theory) | 45.4% | 70.2% | worse, reverted |
DMA waits (meter=3): ~29 polls a call, the same with WBUF in Block 2 or 3, so the copy's
extra ~0.8% is not the DMA either. Two unrelated changes landing on the same worse numbers,
while nam_stalls.py sees ~0.1k between them, say small layout shifts move the chip by
~0.5% through something the model lacks (fetch/bank effects around the pair loop?). The
shipped layout is a good spot. Next ideas: plain instruction cuts in the DMA bookkeeping
(~5k instructions a call: TCB building ~0.9k, pump/polls ~1.7k, fcopy), which move the
count, not stalls; or microbenchmarks to characterise the layout effect first.

## More room: 24.0% a block, three blocks and a Simple Delay (2026-10-30, kit c81ef5e..6ee64d2)

| change (kept) | 1 block | 2 blocks | a block |
|---|---|---|---|
| shipped (24.7% kernel) | 45.0% | 69.7% | 24.7% |
| n_put two words a move (even ring lengths and bases; head ring 32) | 44.8% | 69.1% | 24.3% |
| + head weights to WBUF, p_rl folded stores, n_put guard through I12 | 44.6% | 68.6% | 24.0% |
Tried and dropped: dummy PM reads to cache two X instructions (the cache misses cost more).
Three blocks: 92.6%; with a mono Simple Delay (332 units, ~1.9% real: delays are declared at
~175 units a %, drives ~100) 94.5%, idle steady. dsp_cost 2380 admits exactly that.
Played on the unit: three blocks and the delay, clean. Stereo Simple Delay (455) would need
dsp_cost ~2345, which would also admit 3 NAM + ~460 units of drives (~97% real): better to
make the block ~0.5% cheaper first.
Builds: hx_firmware and hx-stomp-nam-lite = the kit: Stomp 2265557c, XL 32e9c2de.
Then (not kept): staging buffers [tap][channel][16] so fcopy is one loop of 24, and p_next's
I0 loaded three instructions before its MODIFY: bit for bit, ~60 cycles in nam_stalls.py,
no change on the unit (44.6% / 68.6%), reverted. What is left is below the meter's ~0.1%.

## The USB hang is the stock firmware's (2026-10-31)

tools/hx_smoke.py hung the unit twice, after ~15..20 hx_ctl preset writes, at different
cases. Its opt-in rewrites cases (the edit buffer rewritten from empty, the unit asked after
each): on the **stock 3.80 firmware from RAM, one stock distortion (521), no NAM**, write 31
got no answer and the unit was gone (power cycle). So whole-preset writes over USB (hx_ctl's
set-model, load-preset, select: one each) wear something out in the stock firmware within
one boot; not the NAM kernel or our patches. The Stomp's own UI and HX Edit's normal edits
are other paths. hx_smoke now reboots the image from RAM before a case once 10 writes are
used (WRITE_BUDGET), and its stress cases fit that budget.
On our build (d450c571 from RAM, rewrites_nam3: three NAM blocks, three hx_ctl writes a
rewrite) the unit died on rewrite 11 = USB write 31, the same count as stock: no worse.
The limit counts writes, not blocks or DSP load. With the reboots the full suite passes
(40 cases, 0 fail, 2026-10-31), nam_takeover included: its 2026-10-30 hang was this limit.

## dsp_cost 2345: the stereo delay, measured over USB (2026-10-31)

Kit 7ad7f9c with dsp_cost 2345 (both entries), meter=2 image, NAM blocks last, built and
measured by hx_ctl (delays place since c943b53), 10 s of the idle word each:

| three NAM blocks plus | declared | DSP load |
|---|---|---|
| nothing | 7,035 | 92.9% |
| mono Simple Delay (80) | 332 | 93.8% |
| drive 102, the dearest admitted drive | 459 | 95.4% |
| stereo Simple Delay (92) | 455 | 96.7% |
| drive 95 / delay 81 | 476 / 478 | refused |

The stereo delay is the heaviest thing 2345 admits (~120 units a 1%, nearer drives than the
mono delay), ~1 point past the 9,000 cap's ~95.7% real that stock presets stay under. Release
image (no meter) from RAM: 3 NAM + stereo delay, 120 s recorded and 20 s after a Model change,
no repeated block, dropout or click; unit up. Not shipped without the user's listening test.

## DM rings: two far layers in the block's own DM, 23.3% a block, dsp_cost 2275 (2026-10-31)

research/KIT_HEAP_USE.md: the model member's word 13 (dm_words) sizes the instance's I0 block,
carved per slot from Block 0 (the Amp harness allows 0x596, the Distortion entry's mono FX
slot 0x38b), not zeroed. nam_multi DM_LAYERS = 2: layers 3 and 10 (d = 17, 3 x 104 words each)
are near rings from (I0 + 0x92) & ~1 (slot word S_DMB, set by m_init; table word T_BS picks a
near ring's base), dm_words 0x303 for both entries; the other 10 far layers stay in SDRAM. ssim
bit for bit (stale words in the DM block, odd I0s).

Meter=2 on the unit, back to back, the same session (load 1 / 2 / 3 blocks):

| image | 1 | 2 | 3 |
|---|---|---|---|
| before (dsp_cost 2345 meter) | 44.6% | 68.9% | 93.3% |
| DM rings | 44.0% | 67.4% | 91.1% |

0.73% a block, as estimated (nodma's ~0.37% a far layer). The user played 3 NAM + stereo Simple
Delay on the release image: clean; hx_smoke 46 pass, 0 fail.

dsp_cost then lowered by the saving (~73 units at ~100 units a 1%), 2345 -> 2275, so the worst
admitted case stays at the level already played clean. Three blocks declare 6,825 and leave
~690 units. Measured with three blocks (meter=2, dsp_cost 2275): alone 90.9%; stereo Simple
Delay (455) 93.5%; dynamics 651 (600) 95.5%; delay 75 (655) 95.6%; distortion 432 (650) 95.9%;
distortion 525 (650) 96.2%; pitch 183 (660) 96.4%, the dearest admitted; modulation 158 (689)
refused. Pins: Stomp 76ffd014, XL c04b2af5 (not run on an XL), kit plain d616ccd4.

## PM rings: a third far layer in the block's own PM block, 23.1% a block (2026-10-31)

The member's word 14 (pm_words) sizes the instance's I8 block (probed on the unit: 0xE33C4 for
an amp, 0xE1B15 for the Distortion entry, both in Block 3's heap); stock writes PM(0..12) only.
nam_multi PM_LAYERS = 1: layer 19 (d = 17) is a near ring from (I8 + 0xE) & ~1 (S_PMB, set by
m_init from the entry's I8 at SAVE + 46), pm_words 0x147 (<= 0x14e, the mono FX slot). 9 far
layers stay in SDRAM. ssim bit for bit; steady worst 30,791 -> 30,254 instructions.

Meter=2, two rounds each, back to back: three blocks 91.1% -> 90.0% (1 / 2 blocks 44.0 -> 43.5,
67.5 -> 66.7): 0.37% a block as estimated. Three NAM blocks alone 89.6..90.0%.

dsp_cost kept at 2275: lowered to 2240 (the saving), it admits delay 348 (730 units) at 97.3%
and modulation 167 (759) at 96.8%, over the 96.7% already played clean; anything under ~2271
admits the 714..730-unit delays. So the saving is headroom. Pitch 183 (660), the dearest 2275
admits, varies on its own: 96.1, 96.4, 96.9, 97.0% in its first ~40 s, then a steady 95.9%
(the 96.4% recorded for the DM-rings build was an early reading: there it likely peaked ~98%).
Stereo Simple Delay 92.3%, distortion 525 94.2%. The user played pitch 183 + 3 NAM on the
release image: clean; hx_smoke 46 pass. Pins: Stomp 3dd9379c, XL 3c859c45, kit plain cfe64de2.

## Stalls after the PM rings: branches are not the gap (2026-10-31)

ssim + tools/sharc/nam_stalls.py on the PM-rings kernel: ~26.6k instructions and ~2k modelled
stalls a call against ~34.9k cycles on the unit (23.1%): ~6k unexplained. Of its 2,646 "jumps"
a call almost all are hardware loop wraps (free); ~390 are non-delayed branches, calls and
returns (n_putw's RTS ~45, pump's not-ready RTS ~42, the layer loop's CALL n_put 42, N_IN ...).
Delayed versions of the hot ones (CALL n_put (DB) with the next R10 step and M1 in the slots,
n_putw RTS (DB), pump IF NE RTS (DB)): bit for bit, but the moved code costs ~40 more PM-cache
misses; on the unit, A/B twice: 2 blocks 66.7/66.7 -> 66.6/66.5%, 3 blocks 90.4/89.9 ->
89.7/89.7%: ~0.1% a block, at the meter's noise. Not shipped (kit stash). The rest of the gap is
most likely the 9 far layers' DMA against the core's memory accesses (nodma: ~3.3% a block for
9 layers), which only more internal memory would remove.
