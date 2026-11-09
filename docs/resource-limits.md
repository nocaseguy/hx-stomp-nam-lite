# Resource limits: how much more fits on the HX Stomp

**Read this before planning a feature.** It says which of the HX Stomp's resources are nearly full, what typical changes cost, and where the remaining room is. Measured on 2026-11-03 against stock 3.80.0, the default `build.py` image (NAM A2 Lite, 3 slots) and the GR-meter image (`HX_GR=1 HX_FRAMEPROBE=1`, branch `gr-meter-experiment`). Setting IDs, glyph slots and M4 code were re-measured on 2026-11-04 on main, with an all-features build (`HX_BPM=1 HX_DSP_METER=1`, plus `--splash-text` with an emoji). Status tags are as in [FIRMWARE_NOTES.md](../FIRMWARE_NOTES.md). The HX Stomp XL has the same Entries 2, 3 and 4, so it has the same DSP and model limits.

## The short version

The HX Stomp has two processors. The **M4** (LPC4350, the CPU) runs the screen, the settings and the footswitches. The **SHARC** (ADSP-21469, the DSP) runs the audio. Their limits are very different:

- **M4 features** (screens, widgets, Global Settings, the splash, the LEDs) have **plenty of room**. BPM, the DSP meter and the boot text with an emoji add 4.3 KB of M4 code over the default build, against about 1.7 MB free. Here the limits are how much of the firmware has been mapped, and CPU time, which has not been measured.
- **DSP features** (new audio code, meters measured on the DSP) are **nearly full**. NAM A2 Lite uses almost all the internal DSP RAM that stock left free.
- **New block models** (new entries in the block browser) are **capped at 8 more** by the firmware's preset-ID arrays, and each one costs more space than it needs to.

## Budget table

| Resource | Left now | Spent by | Status |
| --- | --- | --- | --- |
| SHARC internal RAM | **568 words** (NAM, 3 slots); 2,720 (2 slots) | DSP code, DSP state | verified offline |
| Preset model IDs (1..832) | **8** | each new model | verified offline |
| Entry 2 partition (DSP boot stream, 512 KiB) | **9.5 KB** (NAM build) | DSP code and tables | verified offline |
| Entry 3 partition (model database) | **53 KB** | models (~1.8 KB), knobs (~1 KB per model) | verified offline |
| Blob 0 buffer (DSP composite library) | 88,551 words (~27 more cloned composites) | models | verified offline |
| DSP time per preset | M4 admits up to 90%; 15% always taken | blocks in a preset | verified offline |
| M4 code space (segment 6) | **1.73 MB** before the RAM-run hook at `0x29000000`; ~3.1 MB installed (4 MiB image cap) | caves, relocated tables | verified offline |
| Global Settings IDs | **5** int IDs (63, 74, 78, 120, 132) | settings | verified on unit |
| DSP → M4 frame words | words 200..252 used by the GR meter | values measured on the DSP | verified on unit |

## Checklist for a new feature

1. **M4-only feature?** It almost certainly fits. Put code in a segment 6 cave. Use a free Global Settings ID (claim it on its line in `tools/setting_ids.py`) or a per-block knob for configuration.
2. **Needs DSP code or DSP state?** Count its 48-bit instructions (1.5 words each) plus its data words against the 568 words free. If it doesn't fit, choose a way out below *before* writing it. Also check Entry 2's 9.5 KB.
3. **Adds a block model?** It uses one of the 8 preset IDs, ~46 KB of Entry 0, ~1.8 KB of Entry 3, ~15 KB of Entry 4 and ~3,250 Blob 0 words.
4. **Adds knobs to existing models?** About 1 KB of Entry 3 and 8 KB of Entry 4 per model (`patch_comp.py`: 3 knobs × 6 models = 6 KB + 50 KB).
5. **Wraps a stock DSP primitive?** The wrapper's cycles are charged to the stock block's declared cost, so the M4's 90% check never sees them. Keep the wrapper cheap, and remember that some models contain a core several times (the 3-Band Comp has six `0x271a` cores).
6. **New images or glyphs?** About 3.2 MB fit in the Entry 8 read window. Fonts are ASCII only. Slots 0x01..0x1f are free in every font except `hx21_regularFont`, where emoji takes slots from 0x01 upward; other features take them from 0x1f downward.

## Where things stand, by area

### SHARC memory [verified offline: LDR map of Entry 2, `nam_multi.Layout(slots).report()`]

- Stock fills internal Blocks 0 (`0x92000..0x9e000`) and 1 (`0xb2000..0xbe000`). It leaves only Block 2's tail (`0xc7674..0xc8000`, 2,444 words) and Block 3 above `0xe4842` (14,270 words).
- NAM takes those gaps: 13 words are left in Block 2. Block 3 has 555 words left at 3 slots and 2,707 at 2.
- **The GR meter's DSP side** (`frame_probe.asm`: 600 instructions + 336 words) is loaded at the NAM kernel's own addresses (`0xc4ef8` / `0xe4850`). `build.py` builds one or the other, so **a GR build has no NAM kernel**. With NAM at 2 slots, the GR code fits in Block 3.
- DDR2 (external RAM) is plentiful. Heap 4 is `0x328000..0xed7000` (12.2M words; decoded by hand from VISA immediates near Entry 2 word 41908). The other regions are listed in `patch_amp.py` (`HEAP6_MOVED`, `SHARC_BLOB0_*`, `SLOT_SDRAM`).

### Models [verified offline]

- **Preset model IDs stop at 832**: the app keeps 833-entry arrays indexed by preset ID (init loop `0x28e01182`) and rejects `id > 0x340` (`0x28e01518`, `0x28e01d30`, `0x28e0768e`, about 12 sites). Stock uses 823 of them, and NAM uses 147 and 148.
- Each `add-model` appends new copies of the Static Model Table (~10 KB) and the UI Model Info Table (~36 KB) to segment 6, and leaves the old copies behind. The first model also copies Entry 3's string and descriptor tables (+156 KB once) and moves Blob 0 to Entry 4's tail (+1.98 MB once). Each Blob 0 clone appends a whole copy of the composite table.

### M4 memory [verified offline: reset handler `0x28d92598`]

- SDRAM is 32 MB at `0x28000000`, laid out in this order:
  - data, then BSS to `0x28519ffc`;
  - the 8 MB Entry 8 window at `0x2851aa7c`;
  - fonts, framebuffers (`0x28d1ce98`) and the 8 KB process stack;
  - code from `0x28d8fa80`. Stock code ends at `0x28e3fadc`. The default build reaches `0x28e58ae4`, and an all-features build `0x28e59bc0`.
- Nothing in the stock app points above its own image. A RAM run puts its hook and overlay at `0x29000000..0x29F00000`.
- SRAM left unused by the stock image: `0x100832d0..0x10092000` (60 KB; the RAM loader uses `0x10090000`) and `0x2000c608..0x20010000` (14.8 KB). **[hypothesis]** Nothing allocates these at run time.

### DSP time [verified offline; unit figures from README]

- Costs are in hundredths of a per cent. A preset starts at 1500. The M4 refuses a block that would take the total past 9000 (`0x28e01e88`). Stock blocks cost 35..4000 (median 750). NAM costs 2345 (about 24% measured on the unit).
- One 16-sample block at 48 kHz is about 150,000 SHARC cycles.

### Small limits

- **Global Settings IDs** free for int settings (empty label, no stock reader): 63, 74, 78, 120, 132 [verified on unit: values persist across a power-cycle]. Claimed: tuner 29 and 104, BPM 102, 126 and 128, DSP meter 101 (see `tools/setting_ids.py`). 105..116 are float settings (default 1.0f) and can't hold an int setting. The store holds IDs up to `0x95`.
- **DSP → M4 frames**: 256 words, about 1,000 a second. Word 253 is lost in transit [verified on unit]. **[hypothesis]** Words ~70..199 are unused filler too.
- **Image store**: Entry 8 is read at boot through an 8 MB window (`1 << 14` sectors, stream open `0x28da4378`). It holds 4.83 MB with all features (the emoji glyph adds one item). **[hypothesis]** Past 8 MB, reads need a re-seek or fail.

## Ways to get more room

| Problem | Way out | Gain | Status |
| --- | --- | --- | --- |
| Internal DSP RAM | NAM at 2 slots | +2,152 words | verified offline |
| Internal DSP RAM | Put control-rate DSP code (control functions, the frame-tail writer) in DDR2. Stock already runs 88 of 282 primitives from DDR2 as VISA | most of our code | hypothesis |
| Internal DSP RAM | Code of the 24 unused stock primitives (`UNUSED_SHARC_PRIMS`) | ~390 instructions in ~20 pieces | estimate |
| Entry 2 partition | Load NAM's all-zero staging block (`0xc7cd7`, 796 words) with a zero-fill (tag 1) LDR block | ~3.2 KB | verified offline |
| Preset IDs | Relocate the 833-entry arrays and patch every bounds check | unlimited | hypothesis |
| Entry 0 / Entry 3 / Blob 0 growth | Allocate the tables once with spare rows; drop the stale copies | ~46 KB per model, ~156 KB of Entry 3 | hypothesis |

## Not measured yet

1. M4 CPU headroom (a DWT `CYCCNT` sample shown in a settings value).
2. The GR wrapper's cycles per call, with several hooked cores in one preset (EMUCLK, as `tools/nam_meter.py` does).
3. Whether the internal DSP heaps (`0x965ed..`, `0xe1a00..0xe3cf1`) run short in a full preset.
4. Our own SHARC code running from DDR2.
5. The complete list of preset-ID bounds checks.

Update this file when a number changes or an item above is measured.
