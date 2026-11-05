# NAM A2 Lite on the Helix Floor (v3.80.0): first look

Input: `Helix_Floor_v3.80.0_0x7d01f5efb.hxf` (MD5 of payload 9871e15f...).
Compared against `HX_Stomp_v3.80.0_0x103966115.hxf`. Static only: there is no
Floor to test on.

## Container

Same .hxf/L6IA container. `hxf.py unpack` and `l6ia.py` work unchanged. The Floor
has 16 entries, the Stomp 15. Entries map like this:

| Role                         | Stomp | Floor | Floor size |
|------------------------------|-------|-------|------------|
| M4 main app                  | 0     | 0     | 1.48 MB    |
| (copy of E0, type 3)         | -     | 1     | same bytes as E0 |
| SPIFI boot image (type 1)    | 1     | -     |            |
| SHARC boot stream (LDR)      | 2     | 2     | 0x7bdc0    |
| ? ("4321" header)            | -     | 3     | 29 KB      |
| Model descriptors (0x4023245e) | 3   | 4     | 817 KB     |
| Model blobs (0x28267e5e)     | 4     | 5     | 12.4 MB    |
| 5e242340 / 5e7e2628 / ...    | 5..8  | 6..9  |            |
| tail data                    | 9..14 | 10..15|            |

`patch_amp.py` indexes entries 2/3/4 directly, and `sharc_ldr.py` does the same
(Floor E2 happens to be the LDR too). The descriptor/blob indices have to become
per-device.

## M4 app (Entry 0)

The code base is the same (`lib/helix-common/mcu/main_m4/...` paths in the strings),
but it is a different link: **4 segments** (0x10000000, 0x10088a30, **one 1.4 MB
segment at 0x28000000**, 0x20000000) instead of the Stomp's 7. `_parse_e0_segments`
asserts `nsegs == 7`. Every `E0_DEVICES` address (model table, Table 1/2,
browser lists, subcategory folders) and the add-model code patches need to be
found again from scratch. This is the largest piece of work.

## SHARC program (Entry 2)

The SHARC program is the same family, relinked: the memory runs have the same shape,
with addresses shifted by a few hundred words, ~240 more PM instructions, ~2k more
16-bit words, and DDR2 init up to 0x30dabf (Stomp 0x30d06e).

- Model descriptors parse with `parse_entry3_full`: 863 models (Stomp 864),
  111 amps; HD2_AmpLine6Clarity = id 804 (Stomp 803), IR2048Mono = id 74.
- Primitive registry: 290 records (Stomp 282). **0x9c75 does not exist on the
  Floor.** 23 of the Stomp's other 24 unused primitive IDs are registered, at
  different addresses. Before one is used as the hook, it needs a check that no
  Floor model references it.
- **Entry 2 size is the hard limit.** The Stomp NAM build adds 11 LDR blocks
  (~8.4k words, 33.4 KB) and fills E2 to 0x7ffb8 of the 512 KiB partition. The Floor's stock E2
  is already 0x7bdc0, which leaves 16.9 KB (if its partition is also 512 KiB, still
  unverified). To fit, the injection needs to shrink to about half: zero-initialised
  areas (HIST 512 words, rings) as ZERO blocks, tables computed at first call, and
  possibly no built-in model (slot models only).
- Still unknown on the Floor: free Block 2/3 internal memory, heap end, the DDR2
  gap above 0x30dabf, User IR slot addresses (Stomp DM 0x2abded / flags
  0x2ab56e), and the primitive calling convention (expected unchanged).

## Platform differences

- The Floor has **two SHARCs** (one per path). Whether both boot the same E2 is
  unknown. The one-instance guard and the kernel memory are per DSP. The 3600
  dsp_cost has to be checked against the Floor's own meter.
- RAM run: **not ruled out.** The M4 is almost certainly the same LPC43xx
  family: app header 0x230B0C5E ver 2, segments at 0x10000000 / 0x10088a30 /
  0x28000000 / 0x20000000 match the LPC43xx map. So the chip's ROM USB DFU
  (1fc9:000c) exists if its boot pins can be reached. What differs from the Stomp:
  the Floor's main bootloader is not in the .hxf (no type-1 entry; E3 "4321" is a
  small separate Cortex-M image, probably the UI MCU's, cf. `uiIspUpdate.c`). The
  app has no `BootIntoDfu!` string and no 0x1001FF00 literal, so the Stomp's
  software route into ROM DFU is absent. Instead the app has its own updater
  (`PODPlay/mcu/src/system/updater.c`, "Entered Update Mode!"). Open: whether a
  button held at power-up selects ROM USB boot (needs a Floor owner to try
  `dfu-util -l`), or whether the Floor's update protocol can be used. If either
  works, ramboot needs the Floor's clock/SDRAM setup checked and the eMMC
  read/write hook addresses found again (`sdmmc.c` is there).
- `Helix_LT_v3.80.0_0x7d01f5efb.hxf` has the same build hash, so a Floor port
  probably covers the LT with little more work (not checked).

## How Line 6 Updater updates a Floor (checked 2026-10-28)

`/Applications/Line6/Line 6 Updater.app` (x86_64, has symbols and log strings):

- HX Stomp/XL/Effects: `L6HxStompDevice` / `L6NxpDfuDevice`. The running app is told
  to reboot into ROM DFU (1fc9:000c). The Updater then sends the .hxf's kind-5 trailer
  (P36Updater, a RAM app) over DFU, and that app writes the eMMC. Log strings: "HX Stomp did
  not reset after loading update app (via DFU)".
- Helix Floor/LT/Rack: `L6HelixDevice`, with no DFU at all. `prepareForUpdating()` asks
  the running firmware over the normal MsgPort/bulk channel to "put device into update
  mode". `fwUpdateHelper()` gets an "update port", and `startUpdate(imageSize)`
  streams the image to the device. The receiver is in the Floor app itself
  (`lib/PODPlay/mcu/src/system/updater.c`: "Update message server Started",
  "Updating Helix Firmware... %d%%", "Entered Update Mode!", "Boot Failure, Entered
  Update Mode!"). This matches the Floor .hxf: it has no kind-5 RAM updater
  (only one dinf, kind 0). The Floor also ships the app twice (E0 type 2, E1 type 3,
  same bytes), apparently a fallback copy.

So the Updater never puts a Floor into the chip's ROM DFU and never runs code from RAM
on it: what it does is a flash. Routes to a Floor RAM run:
1. The LPC43xx ROM DFU through the boot pins, if any button/strap reaches them. Unknown;
   a Floor owner can try power-up button combinations and `dfu-util -l`.
2. Reverse the Floor app's update protocol (updater.c) in case it has a write-RAM/execute
   command. Not looked at yet.
3. Flash once a Floor image with a small RAM-run hook added (as `hxf_ram.py`'s eMMC
   overlay), then iterate from RAM. Still one real flash, protected by the Updater's
   update mode and the fallback app copy (fallback behaviour unverified).

## Verdict

It is possible in principle: same container, same SHARC code base, same model
format. But it is a real port, not a rebuild like the XL (whose entries 2..9
were byte-identical to the Stomp's). Work list, roughly in order:
1. Find E2's free memory, IR slot addresses, the unused primitive and DDR2 gap on the Floor.
2. Shrink the LDR injection to fit ~16.9 KB.
3. Find again every E0_DEVICES address in the 1-segment M4 app and adapt `_parse_e0_segments`.
4. Make the entry indices per device in patch_amp / l6ia_verify / sharc_ldr.
5. Answer the two-DSP question.
6. A tester with a Floor. First check: does a power-up button give `1fc9:000c`?
