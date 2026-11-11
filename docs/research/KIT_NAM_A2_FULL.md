# NAM A2 Full (8 channels) as a module in the stock HX Stomp 3.80.0 firmware

Feasibility study, 2026-10-27. Static analysis and simulator only. Nothing
here has run on the unit. The kernel studied is the own-firmware kernel
`src/sharc/nam_a2_ffa.asm`: 16-sample blocks, a layer at a time, two-parallel
fast FIR, branch `nam-sharc`.

Confidence labels:
- **verified**: measured on the unit earlier (commit cited), or computed by a script from the repo
- **likely**: follows from verified facts plus one reasonable assumption
- **guess**: from memory of the ADI manuals, or an estimate with no direct evidence

Scripts are in `/private/tmp/claude-501/kitresearch/`: `a2full_mem.py` (footprint),
`a2full_plan.py` (hybrid layouts), `count_ddr.py` (DDR2 accesses of the
meter-era NAM Lite in ssim) and `costs.py` (stock dsp_cost table).

## Verdict

**Not feasible as the kernel stands.** It needs about **98,000 internal words**
(97,210 data plus 846 code). Today about 16,700 are free. That is 60% of the
chip's whole 163,840-word internal RAM, and the stock program's code and heaps
cover nearly all of it.

**Feasible on paper only if three things hold together.** Even then the margin
is thin.
1. **A hybrid rewrite.** The rings of the six d = 101/239 layers (59,040 words)
   move to DDR2. Each block, their tap windows are streamed in and out with
   external-port DMA (about 5.4k words read and 1.9k written per block). The
   core cannot do this copying itself: at about 20 cycles a word, the reads
   alone would cost about 107k cycles a block. This DMA path is unproven. The
   stock program never touches those registers (likely).
2. **Removing models frees at least about 26-29k more internal words**, beyond
   today's free tails, which this kernel would take over from NAM Lite. The split
   matters as much as the total:
   - about 16.8k words that can hold weights;
   - about 25-29k words in *other* blocks for the rings and scratch.
3. **The stock graph's own fixed load is at most about 15-20%.** That figure is
   unmeasured. The kernel would take about 70-75% in stock, so the total is
   about 80-95%. That leaves room for an IR cab plus a gate, an EQ or a volume,
   and nothing like a delay plus a reverb.

A total of 75% or less is **out of reach for any layout**. The kernel alone is
69.0% even in the own firmware, with no penalties.

## 1. Memory requirement of nam_a2_ffa (verified, `a2full_mem.py`, `place_ffa()`)

| item | words | read by | where it must be |
|---|---|---|---|
| A weights (even taps) | 5,102 | PM bus, one pair per MAC instruction | internal, in a block different from the layer's rings |
| B and SS weights (odd taps, H0 + H1) | 10,030 | PM bus, one pair per MAC instruction | internal, same rule |
| 1x1 weights | 1,518 | PM bus | internal; not in the same block as ABUF |
| head weights | 130 | PM bus | internal; not in the same block as the head ring |
| **weights total** | **16,780** | | the own firmware keeps all of them in block 0 |
| X rings (input, 2(ne-1)d + 16 columns) | 43,904 | DM, one broadcast read per MAC instruction | internal (or staged, see section 4) |
| S rings (x(t'-d) + x(t'), odd times) | 21,896 | DM | internal (or staged); not in the X ring's block (the S pass reads one and writes the other) |
| P rings (A and B partial sums, d + 16 columns) | 12,880 | DM, beside BM and the head ring | internal |
| head ring | 256 | DM | internal |
| **rings total** | **78,936** | | own firmware: block 1 28,576, block 2 21,896, block 3 28,464 |
| layer table (32 a layer, 24 entries) | 768 | DM, per layer per block | internal |
| mixin and bias pairs, rechannel | 376 | DM, per layer per block | internal |
| reset fills (silence state) | 1,152 | only at reset | **DDR2 is fine** |
| scratch (INB, ABUF, HOUT, BM, pointers) | 334 | DM, beside weights in the 1x1 and head | internal, not in any weights block |
| code | 564 instructions = 846 normal words | instruction fetch, ISA | internal; at a 48-bit address that is 0 mod 16 to keep the cache layout `pmcache.py` tuned (otherwise rerun it) |
| **total, all internal** | **97,210 data + 846 code** | | |

The rings are the problem, not the weights. The largest single ring is a
d = 239 X ring of 7,776 words. Each d = 239 layer needs 13,704 words of rings,
and the six d = 101/239 layers together hold 59,040 of the 78,936.

The raw `.nam` model has only **12,146** weights. The 16,780 includes the
derived SS = H0 + H1 weights, which `nam_reset` computes, and the pair padding.

### The block pairing it relies on (verified, `place_ffa()` and `tools/sharc/HARDWARE.md`)

A DM access and a PM access to the same internal block in one instruction cost
an extra cycle every time (measured, `make smoke-stall`). Every MAC instruction
reads a weight pair through PM and a ring value through DM. So:

- **Rule 1**: a layer's weights must not share a block with that layer's X, S
  and P rings, or with the scratch (ABUF, BM). The rule applies per layer: the
  layer table holds separate pointers for each layer.
- **Rule 2**: a layer's X and S rings go in different blocks. This only affects
  the small S pass, about 1% if broken.
- **Rule 3**: an X ring must not share a block with ABUF/BM. The 1x1 writes X
  through PM beside ABUF read through DM.

What breaking Rule 1 costs (derived from the instruction counts: fast FIR is
about 9,100 multiply-adds a sample at two per instruction):
- a K = 6 layer: +176 cycles a sample, which is **+2,816 cycles a block, +1.9%**;
- a K = 15 layer: +392 cycles a sample, **+4.2%**;
- every layer: about **+48%**, putting the kernel near 117%.

How contiguous the pieces must be (verified from the layout):
- **Weights** come in 3 arrays a layer. The largest is 898 words (wBS of a
  K = 15 layer), and 21 of the 23 layers need at most 386. So the weights can
  go into **scattered holes of about 900 words or more**.
- **Rings** need contiguous circular ranges of up to 7,776 words with everything
  internal, or up to 1,584 in the hybrid layout (section 4).

### DDR2 read cost (likely upper bound, not isolated)

The only measurement on the unit is NAM Lite's `--meter` (commit baf19cd):
about 47,000 cycles a block, against 32,309 instructions in ssim. ssim
(`count_ddr.py`, meter-era layout, d = 239 layers 6 and 13 in DDR2) shows
**576 DDR2 word reads and 96 writes a steady block**.

If the roughly 14.7k extra cycles, minus about 2k for ordinary stalls (the own
firmware runs 5.6% above ssim), all come from the DDR2 reads, a scattered core
read from DDR2 costs **about 20-25 core cycles a word**. This is not separated
from interrupt time or block conflicts.

Consequences:
- **A DDR2 ring read directly by the inner loop is ruled out.** It would cost
  about 176 × 20 = 3,500 cycles a sample per K = 6 layer, about 37% a layer.
- **Copying staged windows with the core is ruled out too.** It is about 768
  reads per staged layer per block, roughly 15k cycles (10%) per layer.
- **Only external-port DMA keeps staging cheap.** The stock image has no
  immediate reference to any register in 0x1802..0x1811 or 0x181f..0x1850. It
  uses only the DDR2 controller set-up at 0x1801, 0x1812..0x181e, 0x1851 and
  0x1856. So the EP DMA channels are probably unused: **likely**. The register
  addresses and achievable throughput are a **guess**, and they need a probe in
  the own firmware first.

## 2. Cycle budget inside stock

- **Budget**: 150,000 cycles per 16-sample block for the whole DSP (verified, CONTRACT.md).
- **The kernel alone in the own firmware**: 6,468 cycles a sample = **103,488 a block = 69.0%** (verified on the unit, commit 435e8f1).
  - The whole own-firmware pedal, with I/O, EQ, delay and level, measured 106,865 cycles a block (71.2%).
- **Stock graph baseline: not measured.**
  - The NAM Lite figure of "about 47k cycles = 31%" is the kernel's own EMUCLK
    count (`--meter` reads EMUCLK at the kernel's entry and exit), not the whole
    graph. So **the baseline cannot be derived from it** (verified from
    `nam_lite.py` METER_ENTRY/METER).
  - Indirect bound: the ARM caps each DSP at 9,000 cost units (verified,
    `0x28e01e88`). NAM Lite's measured 47k cycles was declared as 3,600 units,
    about 13 cycles a unit. On that scale, 9,000 units is about 117k cycles
    (78%). So Line 6 holds back about 22% for the fixed graph, interrupts and
    margin. **Guess**: the baseline is about 5-20%.
- **Total**: kernel in stock about 70-75% (section 3) plus the baseline. That
  is **about 80-95%**. It fits under 100% only if the baseline is 20% or less,
  and keeps a 10% margin only if the baseline is 15% or less.
- **What else could run** (stock costs read from Entry 0 Table 1, verified with
  `costs.py`):
  - At about 13 cycles a unit, an honest dsp_cost for NAM Full is about
    **8,200-8,600 units** of the 9,000.
  - That leaves about 400-800 units. Cab IR or User IR: 250. Noise gate:
    115-190. Simple 3-band EQ: 128. Volume: 35.
  - So **an IR cab plus a gate or an EQ** fits. A simple delay (332) and a
    reverb (750) together do not, and neither does a second amp.
  - Declaring a lower dsp_cost would let the user add more blocks, but the
    dispatcher has no watchdog or early exit, so an overrun means dropouts
    (verified absence, KIT_PRIMITIVE_LIFECYCLE 3.4).
- **Measurement to do**: a kit "meter" kernel like `nam_lite.py --meter`, but
  playing the idle-thread load word **DM 0xc2fd5** as the square wave's
  amplitude. Record it once with an otherwise empty preset and once with
  NAM Lite. That gives the baseline directly.

## 3. Own firmware vs the stock primitive environment

| difference | effect on nam_a2_ffa | estimate | label |
|---|---|---|---|
| 16-sample calls | same block size; the outer block loop goes, so loop nesting drops from 5 to **4**, exactly the contract's limit (dispatcher 1 + 4 + 1 left for interrupts) | 0 | verified (nesting counted) |
| Entry and exit | save and restore R/S, I/M/B, MODE1. `I7` (used for the output) must be saved: the dispatcher needs I7/B7/L7, and M15 = 0 on return (ffa sets M15 = 10). Set RND32 (stock runs with RND32 off) and restore MODE1 exactly. Move MODEL/scratch off 0xc0000/0xc0100 (stock memory) | about 150 cycles a call | likely |
| CBUFEN | the kernel already needs circular buffering on and sets every L register itself | 0 | verified |
| Interrupts on (block interrupt, SPI host link, timer) | interrupt time lands inside the kernel's 70% of the block | +1-3% (1.5-4.5k cycles) | guess |
| Instruction cache with stock code between calls | the cache is cold at each call. The ffa already refills it at every pass of every layer, so it is one extra refill a call, worth tens of cycles. Placing the code off the `pmcache.py` alignment (48-bit address mod 16) costs up to about +6% (measured 11.5% vs 5.6% over ssim before and after alignment) | about 0.1k cycles if aligned, up to +6k if not | verified (alignment effect), likely (the rest) |
| DM/PM block pairing with stock's memory map | the Rule 1 penalty in section 1, if the free memory forces weights and rings into one block | 0 to +48% | verified (per-instruction cost) |
| DDR2 contention | none if everything is internal. With the hybrid layout: DMA set-up and polls for 6 layers, address switches, and core stalls if DMA is late, while stock VISA code and delay/looper buffers share the DDR2 | +0.5-2k cycles | guess |
| I/O | the stock graph's, not the kernel's: part of the baseline | — | — |

**Estimated kernel cost in stock**, with a correct layout (Rules 1-3 met, code
aligned, hybrid staging by DMA):
103.5k + 0.15k + 1.5-4.5k + 0.5-2k ≈ **105.5-110k cycles a block = 70-73%**.
Worst case about 75% (likely).

Any layout that breaks Rule 1 for the big layers, or core-copies DDR2, pushes
it over 80% for the kernel alone.

## 4. Layout plan, as requirements for KIT_REMOVE_MODELS

Notation:
- *F_b* is the internal words free in block *b* after removal (blocks 0..3,
  normal words), counting only holes of the sizes given.
- *WB* is the set of blocks used for weights; *RB* is the set used for rings,
  staging and scratch.
- Rule 1 means a layer's weights block is not one of its RB blocks. The simplest
  form: WB and RB are disjoint.

### Plan A: everything internal, today's kernel unchanged except relocation

- WB: at least **16,780 words** in holes of 900 words or more.
- RB: at least **78,936 + 1,478 ≈ 80.4k words**, including a 7,776-word
  contiguous hole for each of the three d = 239 X rings.
- Code: 846 words.
- **Total about 98k.** This would mean freeing about 81k of the chip's 164k
  internal words. **Not achievable** while the stock dispatcher, host link,
  RTOS and remaining models must live (likely).

### Plan B: hybrid, the d ≥ 101 layers staged by EP DMA (the recommended target)

In DDR2:
- the six big layers' X and S rings, 59,040 words; and
- the reset fills, 1,152.
DDR2 0x2f0000.. (65,536 words, likely free, KIT_FREE_MEMORY) holds them, with
about 5k words to spare.

Internal:

| piece | words | blocks | largest contiguous |
|---|---|---|---|
| weights | 16,780 | WB | 898 |
| rings of the 17 other layers, head ring, last X | 19,896 | RB | 1,584 |
| staging windows, 3-deep ring of per-layer windows (K × 16 × 8 X + ne × 8 × 8 S + 2 × 16 × 8 P = 1,216 each) | 3,648 (7,296 if all six layers are prefetched at block start) | RB | 1,216 |
| table, mixin/bias, rechannel, scratch, header | 1,494 | RB (scratch not in WB) | 768 |
| code | 846 | any, aligned | 846 |
| **total** | **about 42.7k (46.3k with full prefetch)** | | |

So Plan B needs:
- **ΣF over WB ≥ 16.8k** and **ΣF over RB ≥ 25.0k (28.7k with full prefetch)**;
- RB holes of 1,584 words or more for the rings.

Today's free internal memory:
- block 3 tail 0xe4842..0xe7fff, 14,270 words;
- block 2 tail 0xc7672..0xc7fff, 2,446 words, shared with the code;
- both now taken by NAM Lite, which this would replace.

With those tails as RB:
- RB still needs about **9-13k more**, in blocks 2 or 3, or in block 0 or 1 if
  that block holds no weights. The block 3 heap 0xe1a00..0xe3cf1 (8,945 words),
  if it can be shrunk, is the obvious first piece.
- **All 16.8k of the weights must come from removal**, most likely from
  freed code or heap in blocks 0 and 1.

DMA traffic: 5,376 words read and 1,920 written per block (about 16M + 6M
words a second), well under the DDR2 peak (guess: 16-bit DDR2 at up to 225 MHz,
about 225M words a second).

### Plan C: weights streamed by DMA too

Weights move to DDR2 and are DMA'd a layer ahead into a double buffer of
2 × 1,542 words.
- Internal: about **27.6-31k**, all of it RB-type except the 3k weight buffers,
  which must sit in a block apart from the rings.
- DMA: about 22-25k words read per block (about 70M words a second), sharing
  the DDR2 with the stock program.
- This fits only a little beyond today's free memory, but it rests entirely on
  unmeasured DMA throughput and contention: guess, high risk.

### Minimum internal for ≤ 75% total

**None.** The kernel alone is 69% at best and 70-73% in stock. With any
plausible baseline the total is 80% or more.

For **≤ 75% for the kernel alone**, the minimum is Plan B: **about 42.7k
internal words**, split at least 16.8k (WB) against at least 25.0k (RB). Plan C
reaches about 28k only on unproven DMA.

### Getting the weights in

The model has 12,146 floats.
- One User IR slot holds 2,048 floats. With NAM Lite's 8-word header, 2,040 are
  payload.
- **6 slots** hold the weights (12,146 / 2,040 = 5.95). **7 slots** hold the
  weights plus the precomputed silence state (1,152 fills, 13,298 words). That
  silence state avoids the pop on a model change that NAM Lite needed it for.
- Slot *s* is the DDR2 block at `0x2abded + s*0x800`, read top-down (verified
  earlier, memory notes). Consecutive slots are consecutive 0x800-word blocks
  of the 0x2ab5ee pool, so 7 adjacent slots form one DDR2 run.
- The Model knob picks the first slot, and the header says "slot k of 7".
- Each slot needs its own scale header because HX Edit refuses |x| > 15.85
  (NAM Lite's 2^e scheme).
- A 2048-float slot is the largest stock store a user can fill from HX Edit
  (verified for 2048 Mono). No other user-writable bulk path is known.

What a load costs: about 13.3k DDR2 reads at about 20 cycles is roughly 266k
cycles, plus SS synthesis and clearing about 20k internal ring words. With
only about 15% of a block spare beside the running model, the load takes about
15-20 blocks, **about 5-7 ms of silence or crossfade**. A DMA load would
shorten it.

The memory belongs to one instance (`instances = "one"`) and replaces NAM Lite.

## 5. Numbers to check against the removal results

1. Is there a set of blocks WB with at least **16,780** freed words in holes of
   900 words or more, holding no rings or scratch?
2. Do the remaining blocks RB have at least **25.0k** (Plan B, 3-deep staging)
   or **28.7k** (full prefetch) words? That counts today's 14,270 + 2,446
   tails, in holes of 1,584 words or more for 17 rings and 1,216 for staging.
3. Is there **846 words** for code at a 48-bit address that is 0 mod 16?
4. Is DDR2 **0x2f0000..0x2fffff** free (KIT_FREE_MEMORY test 2) for 60,192 words?
5. On the unit, before writing any of this:
   - the baseline load from DM 0xc2fd5 must be **20% or less** (15% or less for margin);
   - an EP DMA probe in the own firmware must move at least **7.3k words a
     block** between DDR2 and internal memory without stalling the core.

If 1 and 2 fail, or the baseline is over 20%, A2 Full in the stock firmware is
**not feasible**. A lighter model, such as NAM Lite or a reduced-channel A2,
remains the stock-firmware option, and A2 Full stays in the own firmware.
