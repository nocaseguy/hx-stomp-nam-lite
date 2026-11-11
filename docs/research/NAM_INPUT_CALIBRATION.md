# NAM input calibration on the HX Stomp

A NAM capture's `metadata.input_level_dbu` is the dBu at which its interface reached 0 dBFS during
the capture (NAM defines it by a 1 kHz sine's peak). The amp trims its input by
`STOMP_DBU − input_level_dbu` dB, so that at Drive 5.0 (GAIN 0 dB in the own firmware) the
Stomp's input drives the model as the capture's interface did. Without the trim, the two match
only when the levels happen to be the same.

The trim is applied at runtime, so `STOMP_DBU` is a firmware constant: a better figure needs only
a rebuild, not new IR files or model headers.

## The Stomp's level: 11.5 dBu (accepted)

There is no Line 6 spec. These are user measurements from TheGearForum,
"Calibrating Input Level for Plugins", p.13 (May 2023):

| unit | signal | reads | 0 dBFS at |
|---|---|---|---|
| Helix Floor, pad off, 1 MΩ (James Freeman, over S/PDIF) | 0.500 / 0.707 / 0.775 V RMS | −15.2 / −12.2 / −11.4 dBFS | +11.4 dBu |
| HX Stomp (MirrorProfiles) | "always matches your values" | | ≈ +11.4 dBu |
| HX Stomp (DieSchmalle, over USB, Axe-FX sine checked with 2 multimeters) | 0.775 V | −15.1 dBFS | +15.1 dBu |

A poster in "Settings guide for Tonex/NAM capturing with an HX Stomp" believes all of the Stomp's
inputs top out at 11.5 dBu. `STOMP_DBU = 11.5` (tools/sharc/nam_lite.py, src/pedal.c).

Accepted on 2026-10-28: the user has confirmed 11.5 dBu from many sources, so no measurement on
the unit is planned. The one outlier (15.1 dBu) stays an outlier. The own firmware sets up the
codec itself, so its level would differ only if that setup differs from stock.

## How the trim is applied

**Stock firmware, NAM Lite** (`tools/sharc/nam_lite_kernel.asm`, the same in hx-stomp-nam-lite):
- `nam2ir.py` (and the web converter) writes the weights unchanged. It puts
  `10^(−input_level_dbu/20)` in IR word 5 (`nam_lite.level_word`), or 0 when there is none.
  Older `.wav` files also have 0 there.
- On a load the kernel sets `N_TRIM` = word 5 × `STOMP_GAIN`. `STOMP_GAIN` is a DDR2 word
  (0x327465) that `nam_lite.py` writes as `10^(STOMP_DBU/20)`.
- Each block, it multiplies Drive's gain by `N_TRIM` when that is not 0.
- Block 2 is full to the word (705 instructions; one more pushes a layer's rings past DDR2), so
  the change saves what it adds:
  - Drive's and the tone knobs' clamp use CLIP around step 50.
  - `DRIVE_TAB` is indexed directly.
  - The level is computed as (2k)² and multiplied into the head scale once a block.
  - The load is moved inline.
- The (scale × level) product rounds differently from (x · scale) · level, by an ulp, at levels
  other than 1.
- `nam_lite.py --check` has a slot model made at 15 dBu. It must equal nam_a2.asm bit for bit
  on the input × `input_trim(15)`, and the built-in model must play untrimmed after it. Without
  the trim the check fails (mutation tested).

**Own firmware** (`src/pedal.c`):
- `nam2c.py` writes `NAME_INPUT_DBU` into the model header, and `nam_live.py -c` passes it on as
  `SHARC_NAM_LIVE_INPUT_DBU`.
- `pedal.c` adds `STOMP_DBU − that` to the GAIN it sends (`P_GAIN`).
- `STOMP_DBU` there is a copy of nam_lite.py's. This firmware sets up the codec itself, so its
  input level may differ from stock.

Alternative not taken: folding the gain into the rechannel and mix-in weights at conversion is
exact (the input reaches an A2 WaveNet only through those). It was the first version (commit
4244984), but it froze `STOMP_DBU` into every converted file.

## AATR SX3 Clean BAL3 CAB (input_level_dbu 15)

- Trim −3.5 dB.
- NeuralAmpModelerCore `render`: the model with the weight-folded −3.5 dB equals the original
  on the input × 0.668, to 134 dB (A2 Lite) and 139 dB (A2 Full).
- The output falls 2.2 dB: the clean amp compresses a little.

`output_level_dbu` is not used: it changes only loudness, and the level it would preserve is the
capturer's load box output.
