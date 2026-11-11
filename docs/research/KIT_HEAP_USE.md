# Who uses the stock internal heaps (HX Stomp 3.80, measured on the unit 2026-10-31)

The question: KIT_FREE_MEMORY.md found no unused internal RAM except the Block 2 and Block 3
tails (NAM A2 Lite fills both now) and ~49k words of run-time heaps whose use was unknown.
Measured from RAM with a heap meter: hx-stomp-kit `--opt nam-a2-lite.meter=4` (nam_multi.py
METER_HEAP_EXIT; tools/nam_meter.py --heap). The NAM block, last in the chain, plays x 1e-5 one
heap's extent (top down to its highest non-zero word) or its non-zero word count (every 4th
word, x 4); Treble picks the heap. Boot zeroes every heap.

## The heap table is not a use measure

DM 0x9D5CC holds {start, end, current} triples: entries 0..4 tiny (0x150, 0xa0, 0x1e0, 0xc0,
0x20 words), 5 Block 0 0x96a9e (19,510), 6 Block 3 0xe1a00 (8,945), 7 DDR2 0x328000, 8 Block 0
0x9b7d4 (2,528), 9 Block 1 0xb2000 (20,568), 10 DDR2 0x293eac, 11.., Block 0 0x9c1b4 and
0x9cbc0 (2,571 each). With one NAM block every big entry reads current = end: sw 0x178a1c
copies entries 5..13 into a task record (DM(0x9D5F6) = the current task; its copies read all
free, 0 used: a post-boot snapshot), and slots get their memory through the instances' own 9
arena triples (KIT_DDR2_BUFFERS.md 1.1).

## What is written (words)

Crowded preset: reverb 712, delay 88, pitch 182, modulation 172, dynamics 557, filter 449,
drive 95, then the meter NAM block (path A full). Identical to the word while the user played
guitar through it, so none of this is audio buffers or filter state (those are in DDR2).

| heap | size | extent from start | non-zero | NAM alone: extent |
|---|---|---|---|---|
| Block 0 0x96a9e | 19,510 | 19,240 (top) | 1,980 | 19,240 |
| Block 1 0xb2000 | 20,568 | 20,556 (top) | 6,728 | 20,556 |
| Block 3 0xe1a00 | 8,945 | 7,420 | 916 | 1,804 |
| Block 0 0x9b7d4 | 2,528 | 2,528 | 1,004 | 2,528 |
| Block 0 0x9c1b4 | 2,571 | 832 | 352 | 832 |
| Block 0 0x9cbc0 | 2,571 | 2,568 | 804 | 2,568 |

Block 1's heap is 8 x 2,571 arenas (2,571 = 0xA0B, the size of the two small Block 0 heaps).
Per arena in the crowded preset (arena j against slot j assumed, not proven):

| arena | block | extent | non-zero |
|---|---|---|---|
| 0 | reverb 712 | 2,568 | 2,480 |
| 1 | delay 88 | 2,252 | 1,420 |
| 2 | pitch 182 | 2,204 | 1,076 |
| 3 | modulation 172 | 2,228 | 360 |
| 4 | dynamics 557 | 2,372 | 372 |
| 5 | filter 449 | 2,568 | 476 |
| 6 | drive 95 | 1,728 | 292 |
| 7 | NAM | 2,560 | 280 |

A reverb fills its arena, so no arena can shrink: there is no free internal RAM to take from
the stock firmware. The Block 3 heap grows with the preset (1,804 -> 7,420). Only the top
~1,700 words of Block 0 0x9c1b4 stayed unwritten in both presets (owner unknown: don't use).

The NAM instance record (I0) is at 0x99F8D, in the Block 0 heap (the same address in slot 0
or slot 3; a second NAM block's at 0x9A6E9, 1,884 words on): instances come from it in
creation order, not by slot.

## The lead: a NAM block's own DM

A model's memory records `{id, dm_words, pm_words, sdram_words}` (KIT_DDR2_BUFFERS.md 1.3) get
DM carved from the slot's budget, zeroed, its base in the instance's memory descriptor. The Amp
harness placeholder grants DM 0x596 (1,430 words) a slot; NAM A2 Lite declares no DM record and
uses ~280 words of its arena. So a NAM block could take up to 1,430 words of internal DM through
the stock mechanism (more if the placeholder's DM budget is raised toward the arena's 2,571),
without taking it from any other block: for its smallest far layers' rings, now in SDRAM and
staged by DMA every call. Not tried. A2 Full (~108k words) is not helped by ~2.5k a block.
