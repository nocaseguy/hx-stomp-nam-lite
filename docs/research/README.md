# Research notes

Working notes from building NAM A2 Lite into the stock firmware: what was measured on an HX Stomp, what was tried, and what didn't work. They are copied from the working repository as they were written, so they're terse, dated, and some numbers were later improved on. The current state is in the main README.

Addresses are those of HX Stomp 3.80.0 (SHARC Entry 2 or the ARM application, Entry 0) unless a note says otherwise. Labels such as **verified**, **likely** and **guess** say how a claim was checked.

The notes name some tools and notes that are not in this repository, such as `hx_ctl.py` (USB control like HX Edit), `hx_smoke.py`, `nam_meter.py`, the `hx-stomp-kit` module builds, the NAM A2 Full kernel, and `KIT_*` notes on stock internals. Those belong to the working repository. A cycle count or load figure in these notes can't be reproduced from this repository alone.

## NAM A2 Lite on the HX Stomp

| note | what it covers |
|---|---|
| [NAM_LITE_DSP_LOAD.md](NAM_LITE_DSP_LOAD.md) | cycles and DSP load on the chip, where they go, the dsp_cost budget calibrated, how three blocks came to fit |
| [AMP_LIMIT.md](AMP_LIMIT.md) | the 2-amp limit per preset (block kind 17), measured |
| [HX_EDIT_DROPS_NAM.md](HX_EDIT_DROPS_NAM.md) | why HX Edit drops NAM blocks and how a donor model ID fixed it (the 4-knob and EQ layouts) |
| [NAM_INPUT_CALIBRATION.md](NAM_INPUT_CALIBRATION.md) | the input trim from a capture's `input_level_dbu`, and the Stomp's 11.5 dBu |
| [STOMP_TEST_A_PRESET_SWEEP.md](STOMP_TEST_A_PRESET_SWEEP.md) | 126 factory presets forward and reverse, then NAM: no stock preset touches NAM's memory |
| [KIT_HEAP_USE.md](KIT_HEAP_USE.md) | which stock internal heaps are used at run time, and the NAM block's own DM |
| [KIT_UNIT_MEASUREMENTS.md](KIT_UNIT_MEASUREMENTS.md) | first probe measurements: call rate, the load word, the empty-preset base load |
| [KIT_EP_DMA.md](KIT_EP_DMA.md) | external-port DMA on the ADSP-21469, from ADI's manual |

## Stopped or not built

| note | what it covers |
|---|---|
| [KIT_NAM_A2_FULL.md](KIT_NAM_A2_FULL.md) | NAM A2 Full (8 channels) in the stock firmware: the feasibility study |
| [NAM_A2_FULL_STOCK_UNIT.md](NAM_A2_FULL_STOCK_UNIT.md) | Full measured on the unit (~90% of a DSP, room for up to four stock blocks). Stopped: memory borrowed from stock heaps got written after some presets, which crackled |
| [STOCK_BITEXACT_OPT.md](STOCK_BITEXACT_OPT.md) | making stock effects cheaper with bit-identical output, and stock models' dsp_cost against measured cycles |
| [HELIX_FLOOR_FEASIBILITY.md](HELIX_FLOOR_FEASIBILITY.md) | a first look at the Helix Floor / LT 3.80.0 |
| [HELIX_FLOOR_KERNEL_COST.md](HELIX_FLOOR_KERNEL_COST.md) | the modelled cost of the Floor's layout, with code and data all in Block 3 |
