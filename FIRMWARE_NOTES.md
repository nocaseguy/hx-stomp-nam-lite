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
- **[hypothesis]** Calling these from the DSP-link thread during boot, before the Home view exists, is a candidate cause of a freeze after the loading bar. See [Open problem](#open-problem-the-gain-reduction-meter).

### Boot splash [verified offline]

The boot picture is drawn twice, by two programs, from two copies of the same pixels.

- **Image store**: Entry 7 is the index, Entry 8 the pixels; neither has an internal checksum. Entry 7: header `{0x5b21255e, 1, size, 0x24, n = 577, 0x3b10, 577, 0xa740, ...}`, then n name records `{off, len}` at `0x24`, then n 48-byte records at `0x3b10`: word 2 = Entry 8 index, 5 = height, 6 = width, 7 = 16 bpp, 8 = `0xf807e01f` (RGB565). Entry 8: header `{0x2a5f3b5e, 1, 959, 0x18, data_off, size}`, then `{len, off}` per item (577 images, then fonts). Pixels are raw little-endian 16-bit with **blue in the top 5 bits and red in the bottom 5** [verified on unit, and offline: stock `Play_Red`/`Icon_SwitchRed` are `0x001f`, `Play_Yellow` `0x07ff`, `Play_Blue` has its large field on top; the rect fill `0x100017e8` and the glyph tint pack `0xRRGGBB` the same way], column-major from the bottom: pixel (x, y from top) is halfword `x * H + (H - 1 - y)` (a byte-exact re-encode of the splash checks this).
- **Stage 1, bootloader** (Entry 1, SPIFI XIP at `0x14000000`): a full 320x240 copy at `0x140068bc` (file offset `0x68bc`, `0x25800` bytes), the splash with 59 black rows below. `0x14002104..0x14002114`: `memcpy(0x29f00ca8, 0x140068bc, 0x4b000)` into its framebuffer, then shows it. Shown from power-on until the app takes over. No checksum beyond the L6IA ones (the vector table does not sum to 0).
- **Stage 2, app** (Entry 0): view constructor `0x28d92708`, paint `0x28d92950`, registered by the app's init at `0x28d92cfc`. It looks up images by name (`0x28db7718(name, &index)`): `HXStomp_Splash` (Entry 7 record 527 = Entry 8 item 527, 320x181 at `0x3e0fdc`) at (160, 240), top-aligned, falling back to `Logo_HXStomp` at (160, 90); `Icon_Firmware` with the text `   Firmware  ` `3.80.0` (`0xb1b1b1`) at y = 53. The loading bar is two rects at y = 121: a 320x1 track `0x660000` and a 2 px `0xff0000` bar whose width the paint sets from a float progress (clamped to 320).
- `Screen_Boot` (record 29, 320x240, the plain black LINE 6 / HX STOMP screen) has no name reference in Entry 0 or Entry 1. **[hypothesis]** unused.
- The P36Updater trailer contains a SPIFI driver (`Common SPIFI Command Set`), so the updater can write Entry 1. Entry 1's sub-header word +4 is `0x02990963` where every other entry has `0x03800000`. **[hypothesis]** a bootloader version that decides whether the updater rewrites SPIFI at all.
- Replacing Stage 2 is an in-place, same-size write of Entry 8 item 527 (115,840 bytes), and a RAM run serves it through the overlay. Replacing Stage 1 means reflashing the bootloader: a RAM run starts the app directly and cannot show it, and a broken bootloader may also lose the DFU path, which the bootloader itself starts.
- **Splash test card** image (`build.py --splash`, MD5 `3a70f780935dbfe32ccda0eac24cd41e`): a test card with corner squares, colour bars and "CUSTOM OS" text in place of `HXStomp_Splash`. Result **[verified on unit]** (RAM run): orientation and the column-major layout are right. (Its red and blue were in fact swapped, unnoticed, because `patch_splash.py` packed red on top until the emoji test showed a red guitar as blue.)
- **Text**: the boot view copies `   Firmware  ` (`0x28e24d14`, literal `0x28d92930`) into a 48-byte buffer at `0x2811ee38` (`0x28daad94` = strcpy), appends `3.80.0` (`0x28e24d24`, literal `0x28d92938`; `0x28daade8` = strcat), and centres the result with `Icon_Firmware` at y = 29. Each string has that one reference; the two are adjacent, 24 bytes in all. `patch_splash.py text` writes up to 23 characters there and points the appended literal at the text's NUL.
- **Full screen**: the boot view's image name (`0x28e24cf4`, 16 bytes, one reference) becomes `Screen_Boot`, and a 320x240 PNG goes into that image (Entry 8 item 29). Full-screen card image (MD5 `8d7a254bfc03232cd18fb308fe6e224e`, **not yet tested on the unit**); full-screen card + text `CustomOS 3.80.0` (MD5 `e3bf46ab7f38351806a2e0b5eee76457`, **verified on unit**: full screen, text over the picture; each glyph of the text is drawn on its own black box).
- **Glyph backgrounds** [verified offline]: a text widget (`[0]` text, `[4]` max length, `[8]`/`[0xc]` position, `[0x18]` font, `[0x1c]` colour, `[0x20]` anchor, `[0x2a]` visible, `[0x2c]` node) is drawn by `0x1000206c`, which calls the app's renderer `0x28db7aa4(fb, text, len, x, y, font, colour, anchor, mode)` with mode 0 (its only caller is the veneer `0x10003530`). Per glyph, mode 0 calls `0x100014cc`, which reads the glyph's columns straight into the framebuffer, black included, then ANDs them with the colour: a black box per glyph. Mode 1 calls `0x10001664`, which reads into a scratch buffer and writes only non-zero pixels. `patch_splash.py apply` hooks the renderer's entry (6 bytes, `sub sp,#8; push.w`) with a cave that sets mode = 1 (`[sp, #0x10]`) when r1 is the boot view's text buffer `0x2811ee38`, so only that line changes. Topographic image (`tools/splash_topo.py`, seed 23, 34 levels; text `CustomOS 3.80.0`; MD5 `8711c5c9d5781f3505c85a3b7b0f8d99`, **not yet tested on the unit**).

### Fonts and emoji [verified offline]

- **Loading**: `0x28db74d0` opens Entry 7 (eMMC sector `0x19408`) and Entry 8 (`0x19c09`) as streams, looks up six font names (literals `0x28db75bc..d4`: `hx21_boldFont`, `hx21_regularFont`, `hx28_boldFont`, `hx28_lightFont`, `hx35_boldFont`, `hx41_lightFont`; that order is the font number), and for each copies its Entry 7 record's glyph table into RAM at `0x28d1aa7c + font * 0x604` (BSS, not in the file): word 0 = record word 5 (extra spacing in px, 3 or 5), then 128 x 12 bytes (`0x28db7778`, at most record word 10 = 0x80 entries, from Entry 7 offset record word 11; the six tables fill Entry 7's tail `0xa740..0xcb40`). A font record has word 4 = 1 (images 0).
- **Glyph entry**: `{height, width, Entry 8 item}`, item `0xffffffff` = none. `0x28db7468(out, char, font)` gives (width, height), `0x28db744c(char, font)` the item, `0x28db748c(font)` the spacing. No bounds check: a byte >= 0x80 reads the next font's table. Glyph items are 571..958 (images 0..570); `hx21_regularFont` has 90 glyphs (space..z), all 21 px tall; every font's 0x00..0x1f slots are empty.
- **Pixels**: as images (blue on top, red at the bottom), column-major, each column bottom-up. A colour glyph drawn on a white line is copied unchanged, so its channels must be in that order: the first emoji build packed red on top and showed the guitar's red as blue **[verified on unit]**. `0x28db7844(item, ...)` reads the item's `{len, off}` from Entry 8's table (index checked against the header's count) and seeks a stream there; the blitters read one column at a time.
- **Colour**: both glyph blitters (`0x100014cc` opaque, `0x10001664` transparent) AND each pixel with the text colour, except when the colour is exactly `0xffffff` (`cmp ..., #0x00ffffff; beq`): then the glyph's pixels are copied unchanged. So a colour glyph draws in colour on a white line.
- **Boot line**: font 1 (`movs r1,#1` at `0x28d92836` before setFont), colour `0xb1b1b1` from the literal `0x28d92940` (both boot text widgets; no other reader).
- **Emoji, as built** (`patch_splash.py text`): each emoji (code point plus joiners, modifiers, selectors) takes a free control-code slot of `hx21_regularFont` (0x01..0x1f, not `\n`/`\r`); its picture (a `--glyph` PNG, else `tools/emoji_png.swift` renders Apple Color Emoji on macOS) is cropped, scaled to 18 px tall (at most 21 wide) in rows 0..17 of the 21 px cell, blended onto black, pure black kept as `0x0001` because 0 is transparent; it is appended to Entry 8 as a new item and the slot set in Entry 7; the boot line's colour literal becomes `0xffffff`. The first prototype grew the item table at `0x18`, which moved every item by 8 bytes per emoji: a RAM run then uploaded ~3.5 MB of Entry 8 (MD5 `53589eb6b825487bcf9fa28dda53efb5`, superseded). Now the new pixels and a copy of the whole item table go after Entry 8's end and the header's count, table offset and size point there; the stock bytes after the 24-byte header are unchanged. Works because the item lookup `0x28db7844` seeks to the header's table offset (`[state+0xc]`, from `0x28db77d4`) + 8 * index and item offsets are absolute; the data offset `[state+0x10]` is not used there. `hxf_ram.py plan`: Entry 8 320 sectors (160 KiB, the Screen_Boot picture plus ~10 KiB), against 7116 before. Image `HXS OS v0.1 🎸` on the topographic picture (MD5 `fae46e6cf5200fc9990f32dd09911258`, **verified on unit**: the emoji, white line and centring work, but red showed as blue). Fixed channels (MD5 `a8c3c7c8331bfb21a2b87315837f5136`, **verified on unit**: red guitar, same background, white centred line without glyph boxes, loading bar; Home, block thumbnails, footswitch/snapshot colours, Global Settings with CustomOS, tuner and preset names unchanged; preset load and save work; power-cycle returns to the installed firmware): `tools/splash_topo.py`'s palette has red and blue swapped so the background's bytes stay exactly as shown; a preview composited from that image's own Entries 7 and 8 shows the line in white with the colour guitar.
- **Emoji alignment** [verified on unit]: `hx21_regularFont`'s capitals and digits are rows 1..16 of the cell (baseline 16; x-height from row 5; descenders to 20). Centred in the whole 21 px cell, emoji sat about 2 px below the capitals (T2 colour card `96d40456c30eb122cfeb49f8fa01826b`: colours, four emoji with skin tone and a ZWJ family, a repeated emoji sharing its slot, centring all right). Now 18 px in rows 0..17, 1 px beyond the capitals each way: T2 `0ad33628891c1d9c02523df42fbf5024` (**verified on unit**: the emoji sit level with the capitals), T1 `9628f8bab23105731daec6441ee26b75` (same glyph code, not run). T3, the 320x181 mode with ASCII text (`4a19f162aed465e018c8ee602306c580`, **verified on unit**): picture over the black band, the line in the stock grey, loading bar; Entry 7 untouched.
- Rejected: more than 128 glyphs (the RAM tables are back to back, the loader copies 0x80); a UTF-8 decoder in the renderer (the renderer, the measurer `0x28db78d8` and strlen are byte based). The line's centring counts the emoji like any glyph [verified offline]: the measurer `0x28db78d8` adds width + spacing (3 px in `hx21_regularFont`) for each byte whose glyph is present (`0x28db741c`: item not `0xffffffff`, width and height not 0). The loader copies Entry 7's table to `base + 4` (spacing word at `base`), so slot c is Entry 7 table + 12c.

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
| `tools/patch_splash.py` | Boot splash picture from a 320x181 or full-screen 320x240 PNG (`export` the current one as a template), and the text under it; `build.py --splash`, `--splash-text`. |
| `tools/splash_topo.py` | A 320x240 boot picture: neon contour lines of a seeded random terrain. |
| `tools/emoji_png.swift` | Renders one emoji (Apple Color Emoji, macOS) to a PNG for `patch_splash.py text`. |
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
- A guard was added so the hook does nothing until frame word 200 equals the DSP marker (`0xf00d600d` raw). Rebuilt MD5 `d6f05ad7f2a7ec895eef765eaac6abb5`. **Not yet tested on the unit.**
- If it still freezes: (a) boot with a preset that has no compressor to separate DSP-side from M4-side causes; (b) build a variant whose M4 hook is a no-op; (c) suspect stack depth in the DSP-link thread (9 registers pushed + 12 bytes + `GET_VALUE` + setter) and setters called from a non-UI thread.
- If it boots but the divider does not track: try the 9 GR Input/Output combinations; if the core is the wrong tap, wrap another member (`0x89`, the multiplier).

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
