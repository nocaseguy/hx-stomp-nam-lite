# HX Stomp firmware notes

A working document for anyone (human or agent) continuing the custom-firmware work. It records what has been learned about the HX Stomp 3.80.0 firmware, the tools used to learn it, and what is still open. **Add to it as you learn things**; see [How to contribute](#how-to-contribute).

Every claim carries a status:

- **[verified on unit]**: seen working on a real HX Stomp.
- **[verified offline]**: checked in the simulator, by disassembly, or by a checksum, not on a unit.
- **[hypothesis]**: reasoned, not yet checked. Treat with suspicion.

No Line 6 code or data is in this repository. Addresses below are facts about the stock 3.80.0 file you supply yourself (`HX_Stomp_v3.80.0_0x103966115.hxf`, MD5 `a2cd8f4ae56f49415380270ebc484bf1`, gitignored). Every patch asserts the stock bytes it replaces before writing.

## Goal and working method

Goal: a completely custom firmware for the HX Stomp, built in small steps, each verifiable on the real unit.

- The repo is a **binary patcher**: `build.py` reads the user's stock `.hxf` and writes `build/HX_Stomp_v3.80.0_CustomOS.hxf`.
- Test on the unit by running the image from RAM (nothing is written to the Stomp; power-cycle restores the installed firmware). See [RAM_RUN.md](RAM_RUN.md).
- **Always build to `build/HX_Stomp_v3.80.0_CustomOS.hxf`.** Earlier "freezes" were the user running a stale, differently named file. Tell the user the MD5 of what you built.
- The user hates repeated manual readings ("I cannot be providing reading after reading after reading"). Prefer making unknowns **runtime parameters** (Global Settings knobs) so one image can test several hypotheses.
- Do not install anything on the user's machine. Do not commit or push unless told. Do not add attribution lines to commits.

## Container formats

- `.hxf` wraps an **L6IA archive** of 15 entries (`tools/l6ia.py`, `tools/hxf.py`). `tools/l6ia_verify.py` checks every checksum; a build must print `ALL OK`.
- **Entry 0**: the Cortex-M4 application (LPC4350). Segment 6 is code at `0x28d8fa80` in SDRAM and is writable at runtime. Patches append "caves" to segment 6 and reach them with `b.w` hooks or `ldr.w pc,[pc,#0]` tail-jumps. The file stores words halfword-swapped; `patch_amp.get_entry_swapped` and `_e0_vaddr_to_foff` handle that.
- **Entry 2**: the SHARC (ADSP-2156x) DSP boot stream, LDR blocks. Tag 5 = 48-bit instructions, tag 4 = 32-bit data.
- **Entry 3**: the model table (29 models; metadata such as `gainReductionMeterCount`).
- **Entry 4**: DSP graph blobs. Blob 0 is the composite library (each effect is a composite of primitives). The graph surgery format is only partly understood.
- Internal CRCs must be fixed after editing Entry 0 (`l6ia.fix_internal_crcs`).

## The M4 (CPU) side

- Thumb-2 disassembly: Apple `llvm-objdump` (`llvm-objdump -d --triple=thumbv7em`) works. A disassembly of segment 6 is the main map; rebuild it with `tools/l6ia.py`/`patch_amp.py` helpers to extract Entry 0, then disassemble.
- **Assembling M4 code: Apple `clang -target thumbv7em-none-eabi` works** as a Thumb-2/VFP assembler. `tools/m4asm.py file.s` prints the `.text` hex. Use `mul`, not `muls`, in the clang syntax where it complains.
- The firmware uses the hardware FPU elsewhere, but new M4 hooks avoid VFP because the FPU context of the thread they run in is unknown.
- Thumb function pointers are called with the address OR 1.

### Settings (Global Settings) [verified on unit]

- Global Settings has 6 stock sections; `tools/patch_menu.py` adds a 7th, **"CustomOS"**. Entries are identified by a setting ID and carry a label (`b'Section\nName'`), a limits object, and a value-string table.
- Shipped: **Tuner Activation** (Hold/Press, ID 29) and **Lock Tuner Settings** (Off/On, ID 104).
- `GET_VALUE` at `0x28e1f844` (call as `0x28e1f845`): `(id, out)`, result at `[out+4]`; the buffer must be at least 8 bytes.
- Limits code for an int 0..3: `0x28e1ed1c`.
- Experiment modes (`HX_PROBE`, `HX_GR`) reuse IDs 29 and 104 for their knobs and so disable the tuner features. Real features need their own IDs.

### Home screen and widgets [verified on unit]

- The Home view is a static object at `0x2812a05c` (returned by `0x28d960f4`).
- The divider is four 80 px segment widgets at `0x2812a594 + 0x1c*k` (k = 0..3). Layout function `0x28dc87cc` resets them to the stock look on mode change.
- Stock: the selected segment is white and 2 px, the others grey `0x666666` (a literal at `0x28dc8b58`) and 1 px. `tools/patch_divider.py` makes the whole divider 2 px green by patching three sites (`0x28dc8808`, `0x28dc8b22`, `0x28dc8b58`). Verified on the unit.
- Widget setters (PLT stubs, Thumb): `setColor 0x28e24b98` (r0 = widget, r1 = `0xRRGGBB`, black = 0); `setSize 0x28e24b28` (r0 = widget, r1 = w, r2 = h). Both take a mutex and invalidate, so they are not free to call at high rate; cache and call only on change.
- From the ROM bodies (segment 1) [verified offline]: a widget is `[0]` colour, `[4]` position, `[0xc]` size, `[0x15]` visible, `[0x18]` canvas. `setColor`/`setSize` store the value and only mark the canvas dirty (`[canvas+0x24] = 1`); `0x28e24b00` is `setVisible(w, v)`. Nothing repaints until **`0x28db8508(full, partial)`** (96 callers; the layout ends with `(0, 1)`), which sets dirty flags `0x281f3728`/`0x281f371c` under mutex `0x281f3720` and signals `0x281f3714`, waking the UI thread.
- The ROM mutex (`0x10000500`) fails instead of blocking when `CONTROL` is 0 (interrupt or pre-RTOS), so the setters and the redraw request degrade rather than hang in such contexts.
- **[hypothesis]** Calling these from the DSP-link thread during boot, before the Home view exists, is a candidate cause of a freeze after the loading bar. See [Open problem](#open-problem-the-gain-reduction-meter).

## The M4 to DSP link [verified on unit]

- Framed 1 KB (256-word) SPI/DMA frames. Word 0 is magic `0xFACEF00D`, word 255 is trailer `0xD00FECAF`, payload from word 2.
- The M4 receive callback is reached through a literal at `0x28da6134` (stock value `0x10001095`; `r1` = RX buffer). Hooking it by replacing the literal and tail-calling the stock address works.
- The M4 sees halfword-swapped words: `ror #16` to read them.
- Most frames are empty. Words ~70..254 are unused filler.
- **The DSP can send data to the M4 by writing into the frame tail.** A SHARC routine scanned DSP memory (internal `0x80000..0x100000`, DDR2 `0x200000..0x330000`, 256 words per call) for `0xFACEF00D` with `0xD00FECAF` at +255, wrote `0x600DF00D` at word 200, a tag at 201 and a call counter at 202, and all three arrived at the M4. Word 203 onward is free. This is the transport for DSP-measured values (for example gain reduction), and it needs no knowledge of Line 6's own message formats.
- Searching Line 6's existing message traffic for a meter value ("needle in a haystack") was tried and abandoned.

## The SHARC (DSP) side

- `tools/sharc/sasm.py`: assembler. `tools/sharc/ssim.py`: simulator (the `MANT` ALU op `0xAD` is not modelled). There is no disassembler in the repo. Labels are case-insensitive (`fp_cur` clashes with `FP_CUR`). `IF EQ DM(I5,1) = I4` is illegal: copy to a data register first.
- `tools/sharc/nam_multi.py` generates the NAM A2 Lite kernel (checked in the simulator against `src/sharc/nam_a2.asm`).
- **Primitive registry**: in Entry 2's data at DM `0x200000`, 2256 words, 8-word entries `[id, init_fn, 0, 0, ctrl_fn, process_addr, dm_words, pm_words]`. A primitive's process code address is word 5.
- **Registry-wrap technique [verified on unit for the transport]**: `tools/patch_amp.py patch --wrap-prim ID:ADDR` repoints a registry entry's process address at a custom kernel, which `CALL`s the stock address first (`ORIG`) and then does its own work. The patch asserts that the stock address equals `ADDR`, and adds a new tag-4 LDR block. No graph surgery is needed.
- Custom kernels: save and restore what they use (MODE1, R0..R7, I4..I6, L4..L6); clear `PEYEN|BDCST9` while running.
- A kernel is installed as the entry of an otherwise unused primitive; `patch_amp.py patch --asm file.asm` places code at the addresses the `.section` lines give.

### Deluxe Comp [verified offline]

- Model `HD2_CompressorDeluxeCompMono`, composite `0x6000c9`, members: 0 in-port, 1 `0x239d`, 2 and 3 `0x102`, 4 `0x271a` (compressor core, 2 inputs / 1 output), 5 `0x89` (2 inputs), 6 `0x80`, 7 out-port.
- Registry entry for the core at `0x200320`: `[0x271a, 0x6100f8, 0, 0, 0x6100bd, 0x8d9c9, 0xb, 5]`; process code at PM `0x8d9c9`, which uses `MANT` (log-domain gain).
- The wrapper was called with `I1=0x967de`, `I2=0x967ee` (adjacent 16-word buffers), `I3=0xb2e30`, `I0=0x96fc9`, `I4=0xe14ee`, `I5=0xc5b52`. Sample magnitudes were tiny (~1e-5) in a probably silent capture, so **which buffer is the compressor's input and which its output is unknown.**
- Blocks are 16 samples.

## Tools index

| Tool | Purpose |
| --- | --- |
| `build.py` | Whole pipeline. `HX_FRAMEPROBE=1` swaps in `src/sharc/frame_probe.asm` and wraps `0x271a`. |
| `tools/l6ia.py`, `tools/l6ia_verify.py`, `tools/hxf.py` | Container parse/rebuild/verify/pack. |
| `tools/patch_amp.py` | Add models, IR titles, SHARC kernel, `--wrap-prim`. |
| `tools/patch_menu.py` | Global Settings section and the M4 caves. `HX_PROBE=1` / `HX_GR=1` are experiment modes. |
| `tools/patch_divider.py` | Home divider 2 px green. |
| `tools/m4asm.py` | Assemble a Thumb-2 `.s` with Apple clang, print hex. |
| `tools/sharc/sasm.py`, `ssim.py` | SHARC assembler and simulator. |
| `tools/hxf_ram.py`, `tools/ramboot/` | Run an image from RAM over USB. |
| `src/sharc/frame_probe.asm` | DSP-side wrapper and frame-tail writer (test image). |
| `src/m4/gr_meter.s` | M4 receive hook that draws the meter on the Home divider. |
| `tools/gr_meter.hex` | Generated by `python3 tools/m4asm.py src/m4/gr_meter.s \| tail -1 > tools/gr_meter.hex`. |

Build commands:

```sh
# normal build
python3 build.py HX_Stomp_v3.80.0_0x103966115.hxf
# gain-reduction meter experiment
HX_GR=1 HX_FRAMEPROBE=1 python3 build.py HX_Stomp_v3.80.0_0x103966115.hxf
# word-probe experiment (shows frame words on screen)
HX_PROBE=1 HX_FRAMEPROBE=1 python3 build.py HX_Stomp_v3.80.0_0x103966115.hxf
```

Environment notes: macOS with zsh. `sed -i` needs a backup suffix on macOS, so edit with Python. Do not `echo ======` in zsh.

## Open problem: the gain-reduction meter

Goal: on the Home divider, a green bar grows left to right with the gain reduction of the first or active compressor (start with the Deluxe Comp), the rest black, maximum reduction = full width. The reduction must be computed on the device.

Design as built:

1. **DSP**: the wrapper around primitive `0x271a` measures the peak of three candidate buffers before and after the stock call, and writes these into every validated frame tail: words 207..209 = pre-call peaks of buffers A (`I1`), B (`I2`), C (`I3`); 210..212 = post-call peaks; 203..206 the register values; 213..215 samples.
2. **M4** (`src/m4/gr_meter.s`): receive hook. Reads the settings **GR Input** and **GR Output** (each picks buffer A, B or C), computes GR = 1 - post/pre in Q16 with integer maths, smooths (up instantly, down slowly), maps to 0..320 px in 8 px steps over the four segments, and calls `setColor`/`setSize` only when a segment changes.

Status:

- Transport works (above). The first GR image **froze after the loading bar finished** (so it fails before the Home screen is usable).
- A guard was added so the hook does nothing until frame word 200 equals the DSP marker (`0xf00d600d` raw). Image MD5 `d6f05ad7f2a7ec895eef765eaac6abb5` **booted fine [verified on unit]**, but with a Deluxe Comp (threshold -47.2 dB, ratio 20:1) the divider stayed full green 2 px while playing. That is ambiguous: no drawing at all, setters without effect, and 100% computed reduction all look the same.
- **[hypothesis]** The core `0x271a` (2 in, 1 out, followed by the multiplier `0x89`) outputs a gain signal, not audio, so "1 - post/pre" of two buffers is the wrong formula.
- Diagnostic hook (MD5 `5520099fc2a57c43f5549c96432f4e3f`, **not yet tested on the unit**): **Meter Source** (ID 29) = Buffer A/B/C/Test, **Meter Mode** (ID 104) = Level Pre/Level Post (peak before/after the stock code, 96 dB log scale), Reduction (24 dB below 1.0 = full), Linear (0..1). Test draws green/black/green/black, with red instead of green on frames without the DSP marker. The hook latches once it first sees the marker and does nothing before that. Result **[verified on unit]**: Source = Test left the divider solid green, which does not separate "marker never seen" (the hook stays idle) from "setters have no visible effect".
- Counter image (MD5 `0423c489f0ddb7acd05e029c3688f962`, **not yet tested on the unit**): the hook blob is an entry table (+0 receive callback, +4 text function). With Source = Test, the Source value text shows `C.... M.... D....` (hook calls, frames with the marker, segment draws, low 16 bits in hex), or `C.... W........` (raw word 200 of the last frame) while no marker has been seen. Result **[verified on unit]**: `M8D1B D2B6D` then `M9E32 D43FC`, so the hook runs, the marker arrives and thousands of setter calls happen, yet the divider stays solid green: the setters alone do not repaint.
- Redraw image (MD5 `ac9007039875d781632ec30628fea3f4`): after a segment change the hook calls `0x28db8508(0, 1)`, at most every 16 frames. **[verified on unit]** The divider now animates: with a steady tone through a 100% depth, 1 s tremolo into the Deluxe Comp, the bar follows the signal as a gain-reduction meter would, at the boot-time Meter Source/Mode values. Not yet confirmed that it tracks the compressor's actual reduction rather than the signal level.
- If it still freezes: (a) boot with a preset that has no compressor to separate DSP-side from M4-side causes; (b) build a variant whose M4 hook is a no-op; (c) suspect stack depth in the DSP-link thread (9 registers pushed + 12 bytes + `GET_VALUE` + setter) and setters called from a non-UI thread.
- If no buffer tracks: wrap another member (`0x89`, the multiplier).

## Not yet done (when the user asks to commit the feature)

- Remove or integrate the experiment switches (`HX_PROBE`, `HX_GR`, `HX_FRAMEPROBE`); give the GR settings their own IDs and restore the tuner settings.
- Update `README.md`, `tests/test_firmware.py` (`BUILT_MD5`), `web/firmware-worker.js` (`BUILT_MD5`, sources; it must also run `patch_divider.py`). The pins still match commit `07b38cc` (`3670f1662290098c3071e64aa25c88eb`), but the divider patch is already in the working-tree build, so the pin is stale there.
- At the time this file was written, the divider patch, `m4asm.py`, the GR/probe sources, and the `patch_amp.py`/`patch_menu.py`/`build.py` changes were **uncommitted in the working tree** of the author's checkout. Check `git status` before assuming they exist.

## Ideas for next steps

- Prove the wrapper end to end with a known signal: a preset with a Deluxe Comp, low threshold, hard playing, then compare the nine buffer combinations.
- Generalise to "first/active compressor in the chain": wrap each compressor core and have each write to its own frame words.
- A custom effect model entirely of our own (the NAM A2 Lite model shows how to add a model, preset ID and DSP cost).
- Map more of the M4 UI code so further custom screens/settings need no probing.

## How to contribute

- Add facts under the matching section, with a status tag and, for addresses, how you found them (disassembly, simulator, unit).
- When a hypothesis is confirmed or refuted, edit it in place and say how.
- Keep entries short. Put long dumps in a scratch file, not here.
- Never paste Line 6 code or data here; describe it and give addresses.
