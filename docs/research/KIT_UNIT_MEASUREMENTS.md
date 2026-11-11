# Measurements on the unit, 2026-10-28 (HX Stomp, 3.80.0, images run from RAM)

Unattended, driven over USB: `tools/hx_ramrun.sh` loads an image, `tools/hx_ctl.py` puts a
model into the edit buffer, `hx-stomp-kit/modules/kit-probe` plays memory words as audio and
`probe_decode.py --record` records the USB output (record_mac.swift) and decodes it.
Nothing was written to eMMC (RAM overlay).

| Question | Result | How |
|---|---|---|
| Is a kit kernel called once per 16-sample block? | **Yes**: 2,368 calls per 2,368-block frame | probe call counter |
| v1's short frames (1,104 of 1,472 bits) | **The recorder**, not the DSP: AVCaptureAudioFileOutput dropped every 4th buffer (2.25 s of 3 s). Fixed: record_mac.swift takes the sample buffers itself and reports timestamp gaps. | sample count, edge phase |
| Instance words after creation | DM(3) = 1, knob DM(5) = 0.5, all other DM(0..23, I0) = 0, as KIT_PRIMITIVE_LIFECYCLE.md said | probe payload |
| I0 / I8 / I3 | 0x99f8d (DM arena) / 0xe33c4 (PM arena) / 0xb5be0 (call list, block 1 heap) | probe payload |
| Arenas' current pointers | **current == end for all nine, even with one block in the preset**: whole slot budgets are carved at graph build, so these pointers cannot show what a preset uses. Heaps 0..4 (0x965ee..) unused. | probe payload |
| DSP load word DM 0xc2fd5 | **Idle %** of the block: 1,509 cycles a point, 100% = ~150,900 cycles (fit over a Burn knob of 7..40,400 EMUCLK-measured cycles: 80.5, 73.8, 66.1, 59.3, 54.2) | Burn knob |
| Stock base load (preset with only the probe) | **19.8%, ~30k cycles a block** | load word |
| Second module's primitive 0x128 | **Runs** (kit-drive on 0x9c75 + kit-probe on 0x128) | image A |
| [instance] dm_words 1017 / pm_words 356 | **Binds and runs** (same I0/I8 addresses; the block's real length not proven) | image B1 |
| [instance] sdram_words 0x10000 | **Silent block**: the Clarity host has no SDRAM budget. The kit now refuses sdram_words. | image B2 |
| A kit amp next to a stock amp in one preset | **Kit block silent** (output exactly 0): one amp at a time, or over budget | preset 35 + probe |
| Replacing a block with a model of another kind (amp slot -> reverb) | The unit **drops the preset** and the edit port stops answering; the update port (hx_dfu_reboot.py) still works, so a RAM reload recovers | hx_ctl set-model |
| USB MIDI Program Change | No effect (agent's test); use hx_ctl select | |

Consequences:
- NAM A2 Full in stock: base 19.8% + kernel 70-73% = 90-93%: no headroom. Not pursued.
- Free per-preset memory cannot be read from the arena pointers; a measurement of real use would need a probe that scans a slot's carved memory for untouched words.
- The probe is a kit module (preset ID 572); its decoder prints load as % and cycles from this calibration.

Open (needs the user): HX Edit with a kit preset (.hlx round trip), a kit preset on stock firmware,
kit-drive's sound (needs an input signal), whether hx_ctl can set the input block to USB for an
unattended audio test.
