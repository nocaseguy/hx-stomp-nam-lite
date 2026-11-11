# NAM A2 Lite on the Helix Floor/LT: DSP cost of an all-Block-3 layout (step 1, modelled)

2026-11-04. Static model only (ssim + `tools/sharc/nam_stalls.py`), no unit. Context:
`HELIX_FLOOR_SHARC_MAP.md` (the Floor has 3,430 free words, all in Block 3, Block 2 none).

## Question

On the Floor, the kernel's code and all its data have to share Block 3. How much does that
layout alone cost compared with the Stomp's release layout (hot code, staging, X/IN and
WBUF in Block 2)? This is the layout part of the redesign's cost. The DMA streaming of
weights and near rings is not modelled here; ssim does not make DMA compete for a block.

## Method

`research/helix_floor_stall/drive.py`: the current 4-knob kernel (`--no-tone --no-eq-table`,
3 slots, its arithmetic unchanged), run 160 blocks, counted over the last 50:
- **base**: the release layout.
- **floor**: hot code at pm48 0xe0000, `B2_END = 0` (nothing in Block 2), the globals and
  everything else in Block 3 after the code, cold code at the top as now. (Bigger than
  3,430 words: only the block of each access matters to the model.)

The fetch-conflict rule uses real 128k-word blocks (`>> 17`, as ssim's `mem_block` and the
2026-11-01 chip calibration) instead of `nam_stalls.py`'s `>> 15`; for the release layout
both rules give the same blocks.

usage: `NAM_SRC=$PWD/tools/sharc PYTHONPATH=$PWD/tools/sharc:$PWD/../hx-stomp-kit/modules/nam-a2-lite/src python3 research/helix_floor_stall/drive.py base|floor`
(nam_stalls17.py, next to it, is nam_stalls.py with the `>> 17` fetch rule; for `floor`,
make floorsrc/ as research/helix_floor_stall/README says.)

## Result (cycles a call, one block)

| | instructions | DM/PM conflicts | fetch conflicts | load-use | cache misses | loops | extras |
|---|---|---|---|---|---|---|---|
| base (release) | 26,118 | 584 | 513 | 79 | 203 | 328 | 1,708 |
| floor (all Block 3) | 26,118 | 5,872 | 3,505 | 79 | 203 | 328 | 9,988 |
| **difference** | | +5,288 | +2,992 | | | | **+8,280** |

At ~1,510 cycles per 1% of a block (34.9k = 23.1%, NAM_LITE_DSP_LOAD.md), **+8.3k ≈ +5.5% a
block**: the 4-knob kernel's 22.5% becomes **~28%** from the layout alone. Earlier layout
predictions of this model matched the chip to ~0.0-0.3% (NAM_LITE_DSP_LOAD.md).

Where (floor): conflicts N_WFAR 2,552 (far layers' taps from the staging buffers beside the
weights), N_TAP 1,840 (near taps beside the weights), N_PUTW 288, N_CONV 280, N_WC 280,
N_HC 276, FC_L 216; fetch N_TAP 1,288, PUMP 370, P_NEXT 334, N_PAIR 253, N_IN 251.
The big ones are the pair loop reading a tap (DM) and a weight (PM) from the same block:
with one block there is no layout that separates them.

## With the streaming (estimate, not modelled)

Weights (1,943 words a call) and near rings (~2,200 words in and out) by DMA: about +4-7%
from the per-word costs measured for Lite and Full, so **~32-35% a block**, 2 NAM blocks per
DSP at ~86% beside a Stomp-like ~20% base. Risk on the high side: DMA into the block the core
is reading cost far more than per-word figures for NAM A2 Full (rings staged into Block 3:
+124k a call, NAM_A2_FULL_STOCK_UNIT.md); here every transfer lands in Block 3.

## Levers seen (unmeasured)

- Fewer DM/PM pairs in the tap loops (weights into registers for several samples; long-word
  reads), since separating the blocks is impossible.
- Fetch conflicts: instructions with a Block 3 DM access but no PM access (N_TAP, PUMP, P_NEXT).
- Next step: the Stomp prototype in a 3,430-word Block 3 window, metered on the unit.
