# Long press and the virtual footswitches (`HX_LONG_PRESS`, `tools/features/long_press.py`, `src/m4/long_press.s`)

A hold action per footswitch, FS1..FS5 Hold, and the virtual footswitches FS6..FS10 on MIDI CC 20..24. Status tags as in [conventions.md](../conventions.md).

## As built [verified offline]

- **Long press, as built** (`HX_LONG_PRESS`, `tools/features/long_press.py`, `src/m4/long_press.s`):
  - Settings (before #34 moved them to virtual IDs, which read their defaults until stored, and dropped `lp_boot`): FS1/FS2/FS3 Hold (IDs 63, 78, 132) = Off / Tuner / FS4 / FS5. At boot (after the Home constructor) `lp_boot` rewrites any of their records that is not type 2 as `{2, value}` (0 if above 3), through the setter `0x28e1f8f4(0x28e007ec(), id, record, 6)`.
  - The feature owns `0x28dd1978`; a veneer enters `lp_event` with the stock handler in r2.
  - For footswitch 1..3, it acts only when the switch has a Hold action, Footswitch Mode (21) is not 2 or 3, the function byte is 2 and the switch is not momentary. Then its press is held back.
  - A click replays press and release to the stock handler, so the block toggles on release.
  - A hold runs the tuner request (guarded as the TAP hold is), or replays press and release of code 15 or 16.
  - Everything else passes to the stock handler unchanged.
- **Virtual footswitches FS6..FS10** (Hold values 4..8; first CC 102..106, image MD5 `c4e06138ff8c8c0da6cf53927b528521`):
  - A hold finds the first bypass node on the CC, reads that block's state and sends the opposite: 1.0 when it is bypassed, else 0.0.
  - With no block to read, it flips the value it sent last.
  - **[verified on unit]**:
    - A block on CC 102 (Bypass Assign > MIDI In, on a later knob page) toggles on each hold of FS1 (Hold = FS6), and FS1's own block stays as it was.
    - The first hold after a preset or snapshot change and back still toggles it.
    - Two blocks on CC 103 (FS2 Hold = FS7) both follow the first one's opposite.
  - **Now CC 20..24** (undefined in the MIDI spec; 102..119 is used by some makers for their own parameters).
    - The Bypass Assign MIDI In knob [verified offline]: turning up from Off sets CC 4 (`movs r2,#4` at `0x28dbc2b4`); turning down from Off does nothing; each step is one CC, skipping 0..3, 32 and 49..81. So CC 102 took about 65 clicks.
    - That instruction now sets CC 20, so FS6 is one click from Off and FS10 five. CC 4..19 stay below it.
    - Image MD5 `bec419ffac5c6ee340d26d369b976cbc` **[verified on unit]**: one click up from Off reads CC 20. FS6 and FS10 toggle their blocks.
- **FS4/FS5 Hold and mapped defaults** (image MD5 `e62bb229d2a1df8c5cf53606ca64314c`, **[verified on unit]**: FS1..FS5 Hold read FS6..FS10 after boot; FS1's default hold toggles a block on CC 20; FS4 Hold = Tuner opens the tuner from an external switch, and a tap toggles on release):
  - FS4 Hold (ID 74) and FS5 Hold (ID 120) are for external switches on codes 15, 16.
  - FS1..FS5 Hold default to FS6..FS10.
  - Stock units hold in-range values on these IDs: 78 and 132 hold 0, 74 and 120 hold 1, 63 holds 100. Only 63's value would read as the default.
  - So `lp_boot` treats any Hold record that is not type 2, or not set, as the first boot, and writes all five defaults as ints. Later boots keep the values.
  - **[hypothesis]** If a saved record's type ever reverted to 1, every boot would reset the five to their defaults. To be checked on an installed build.
- **CC text: FS6..FS10** [verified offline]:
  - A CC shows on the device as a 9-byte buffer: cleared, then "CC" (`0x28daad94`, string `0x28e3a0ec`), then the digits from itoa `0x28daaf6c(cc, buf + 2)`. The buffer goes to the knob text setter `0x28dc654c(knob, buf)`, so stock reads "CC20".
  - The only three such sites:
    - `0x28dbb6b2`: Bypass Assign redraw `0x28dbb0fc`.
    - `0x28dbbcd6`: Bypass Assign knob refresh `0x28dbbbf4`, after a turn or a learn.
    - `0x28d8ff4c`: Controller Assign `0x28d8fc48`, its CC# knob.
  - Each is chained with `lp_cc_text`, which rewrites CC 20..24 as FS6..FS10. The Command Center's "CC #" is a CC it sends, so it is left as it is. HX Edit still shows MIDI CC 20..24.
  - Image MD5 `2240fc7cafb4acd1929fd5014309d26b` **[verified on unit]**: MIDI In reads FS6 one click up from Off, FS10 four clicks later, then CC25; it reads CC19 below FS6. Controller Assign's CC# 20 reads FS6, and an FS6 hold still toggles its block.
- **MIDI In label: FootswIn** [verified offline, then on unit]:
  - Bypass Assign labels the MIDI In knob (knob 0) right after its text, with the knob label setter `0x28dc63d0(0, "MIDI In")` (string `0x28e3a0f4`). The only two calls:
    - `0x28dbb6c2`, in the redraw: the MIDI In node from `0x28ddebcc` is in r5 (0 when MIDI In is Off).
    - `0x28dbbce6`, in the knob refresh: the node is in r4 (0 when Off).
  - Off sets its text and then joins the same label call (`0x28dbb808` → `0x28dbb6be`, `0x28dbbea4` → `0x28dbbce2`), so every detent relabels the knob.
  - `long_press.py` owns both calls (`p.own_call`): `lp_label_redraw` and `lp_label_refresh` pass the node to `lp_label`, which hands the setter "FootswIn" when the node's CC (+0x14) is 20..24, and "MIDI In" otherwise.
  - Image payload MD5 `007daabaf3de232fa88749ca8489a8ea` (HX_LONG_PRESS, RAM run, 2026-11-11) **[verified on unit]**: MIDI In reads FootswIn on FS6..FS10, when paged to and on each detent, and MIDI In on Off and other CCs; FootswIn fits under the knob, and an FS6 hold still toggles its block.

- **FS6..FS10 Function** [verified offline: unicorn tests in `tests/test_long_press.py`; not yet on the unit]:
  - Settings FS6 Function … FS10 Function (virtual IDs `0xda..0xde`, container 110, as 108 is full), FS3..FS5 Function's values with Stomp N, and Tuner in TAP/Tunr's place (the user's choice after the first unit run: a hold only ever gives one action, and it has no use for a tap), default Stomp. From Stomp on, value v is stock function v + 1, as for FS3..FS5 Function. In Footswitches after the Holds: pages 4 and 5.
  - A hold that presses virtual footswitch n reads its function. Stomp toggles CC 20 + n as before. Tuner runs the tuner request as the Tuner Hold does. Any other function runs in the stock dispatch's own code (see [footswitches.md](../m4/footswitches.md)): `stock_case` builds the dispatch's frame (`push {r4,r5,r6,lr}; sub sp,#16`, r6 the object, r4 the held footswitch k, r0 its slot) and enters the tbh at `0x28dd14e0` with r3 = function - 1, once with k pressed and once released, so the preset and snapshot steps act. The hooks other features put in that code still run: the tuner's own call of the tap at `0x28dd1656`, more snapshots' select at `0x28dd1640`.
  - TogglEXP enters its case past the press check (`0x28dd17fc`) with k unpressed and r5 = obj + k, so its stomp tail leaves k's own blocks alone; then CC 20 + n toggles, as a stock TogglEXP switch toggles its own blocks.
  - The build asserts the dispatch's switch and table (`0x28dd14d2..0x28dd14fb`) and TogglEXP's first bytes.
  - Image payload MD5 `9735a563611c9b7bb008b0074ae22bcc` (RAM run, `HX_LONG_PRESS` only) **[verified on unit]**: Footswitches pages 4 and 5 show FS6..FS10 Function on Stomp 6..10, all 12 values step and a knob press resets; FS1 held with FS6 on Stomp toggles the CC 20 block and not FS1's; SnpshtUp steps the snapshot and PresetDn the preset on a hold; TogglEXP shows the EXP popup and toggles the CC 20 block, not FS1's; Bank Up shows the preset list, flashing, then the footswitches labelled preset down / the selected preset / preset up (Preset mode); FS Mode> steps the mode, and holds stop outside Stomp mode as expected. TAP/Tunr (since replaced by Tuner) tapped and did not open the tuner, which the user marked a fail.
  - Image payload MD5 `286709f4a9fdb764042effb94ce09919` (Tap and Tuner as two values, RAM run) **[verified on unit]**: FS6 Function starts on Stomp 6 and turns left to Tuner then Tap; Tap follows a run of FS1 holds as the tempo without opening the tuner; Tuner opens the tuner on an FS1 hold. The user then dropped Tap: the values are now Tuner in TAP/Tunr's place (image `81e8befe4fa816976bedeed085088985`, boot-5).
  - Image payload MD5 `7cd4a838dda874e0dcea99ac57f7da33` ("fs-functions boot-6", the same code as boot-5, RAM run) **[verified on unit]**: FS6 Function starts on Stomp 6 and one step left is Tuner, the first value; FS1 Hold = FS6 with FS6 Function = Tuner opens the tuner on an FS1 hold; FS2 Hold = Tuner opens it on an FS2 hold.

## Unit results

- **Long press, unit results**:
  - Image `1ce59296…` (IDs 63, 78, 132) **[verified on unit]**: FS1 Hold = Tuner opens the tuner on a hold without toggling, and a tap toggles on release. Snapshot mode stays stock. But FS2 Hold offered only Off and Tuner.
  - Image `2fe68426…` (FS2 on 74) **[verified on unit]**: FS1 and FS2 Hold offer all four values, and FS3 (132) only two. FS2 Hold = FS4 toggles the block assigned to FS4.
  - **Setting records** [verified offline]: IDs up to `0x88` keep a 40-byte record at `0x2845ee9c + 40 * id`, with the type byte at +8 and the value at +0xc. `GET_VALUE` returns `{type, value}`. The store write (`0x28e1f206`) copies the given record's type and value in and marks the store dirty.
  - 78, 120 and 132 have stock type-1 (bool) limits (`0x28e1ec4c`, `0x28e1ec82`); 63, 74 and 101 have type 2. **[hypothesis]** The menu steps a setting by its record's type, so an ID that was ever a bool shows two values whatever its limits say.
  - Image `4892843b5e04cc8b16e161433b891052` (FS2 back on 78, records rewritten at boot) **[verified on unit]**: FS1, FS2 and FS3 Hold all offer four values, and FS3 Hold = FS5 toggles the block assigned to FS5. Persistence was not tested: a plain RAM run does not save settings.

## Probes

- **Footswitch probe** image (`HX_FS_PROBE=1`, a test feature kept off main, on branch `long-press-midi`; MD5 `88c30d209c18e0d6fada6c13fa04b542`): five hex rows at the top left of the Home screen, one per footswitch k = 0..4. Each row shows k, the report-mode flag, the last raw value, the count of raw reports above `0x3f` and of those at or below it (4 digits each), and the count of events posted of types 1, 2, 3, 5 and any other type. Result **[verified on unit]**: a latching footswitch 1 posts press, release and click, but no raw report reaches the ring loop hook, so **footswitches do not come through `0x28d9aec4`**. The rows repainted only when a block toggled, so hold events were not seen. The TAP hold opened the tuner, and back on Home the preset name covered the rows.
- **Probe, second image** (MD5 `5bad1e82de210e9040994cb5af94eb57`): the same rows at the bottom left, y 4..66, repainted on every footswitch event. Result **[verified on unit]** (latching footswitch 2, Stomp mode): a 3 s hold gives press, release and hold, with no click; a tap then adds press, release and click. So **a held latching stomp switch makes a hold event at 1 s, and its release is not a click**.

Footswitch events, holds and MIDI CC bypass: [m4/footswitches.md](../m4/footswitches.md).
