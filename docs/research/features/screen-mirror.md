# Screen mirror (`HX_SCREEN_MIRROR=1`, `tools/features/screen_mirror.py`, `src/m4/screen_mirror.s`, `tools/hx_mirror.py`)

The HX Stomp's screen on a computer, live and recorded, for demos and onboarding videos. Status tags as in [conventions.md](../conventions.md).

## How it works

- **The command** [verified on unit]: the build chains `sm_register` after the boot's call of the editor's command registrations (`0x28d96adc`), and it registers command `0x52` (its line in `tools/usb_commands.py`) with the no-parameter check. The editor service and its reply functions: [m4/usb-editor.md](../m4/usb-editor.md). Nothing else on the unit changes, and the web page never offers it (`WEB = False`).
- **The reply** is an ordinary editor reply, `{0x66: seq, 0x67: 0, 0x68: bin32}`. The frame is the one at the LCD's `UPBASE` ([m4/home-screen.md](../m4/home-screen.md)), or the first framebuffer when that holds no framebuffer address. It is coded in halfwords over the pixels in the framebuffer's order (column-major, bottom-up, 5-6-5 blue high) as its changes since the frame sent before, which the unit keeps in `sm_prev`: `c < 0x4000` then `c` pixels; `0x4000 + c`, `c` pixels as before; `0x8000 + c` then one pixel `c` times. Then `0` and two u32 times in µs (coding, sending), as halfwords low first.
- **Whole frames**: a request whose seq is not the last one's plus one (a new session, or another editor command in between) gets every pixel, with no skips. The host forces one when a reply does not decode, by skipping a seq.
- **Tests** (`tests/test_screen_mirror.py`): the coding both ways; the handler in `tests/m4emu.py` against a model of the reply functions (its bytes equal the host's coding, against the frame before or whole, the seq rules, `UPBASE`, the worst cases); the registration; and that the build hooks the call.

## Using it

- Build with `HX_SCREEN_MIRROR=1` (with `HX_BREATHING_LINE=1` too when testing: the moving line shows the mirror's fidelity at a glance) and run it from RAM. Close HX Edit: the mirror uses the editor stream.
- `python3 tools/hx_mirror.py shot screen.png --scale 2`, `view` (a window, three times the size), `view --record demo.mov` (H.264, each frame at the time it arrived), `bench`. `view --fps N` caps the frames asked for (15 by default). The window and the recorder are `tools/mac/mirror_mac.swift`, built into `build/mirror_mac` on first use (Command Line Tools' `swiftc`; no ffmpeg).
- A script records while it drives the unit: `with hx_mirror.Session(record='demo.mov') as s:` then `s.ctl.select(3)`, `s.wait(2)`, and so on; `s.ctl` is the `hx_ctl.HxCtl` session, its calls taking turns with the frames on the one USB stream. No frame arrives during a call, so a preset select (which waits about a second for the unit's notifications) shows as a held frame in the recording.

## What limits it [verified on unit, 2026-11-11]

- **USB**: the unit sends its stream at about 0.5 MB/s, in messages of about 253 bytes, whatever MTU the host offers and however many reads it keeps in flight; so bytes per frame set the frame rate.
- **The M4's time**: code in SDRAM runs uncached, about 26 cycles an instruction, and a frame's comparison with `sm_prev` takes about 25 ms. Asking for frames as fast as they come keeps the M4 busy about three quarters of the time and the unit's own screen and controls lag; at 15 frames a second they do not, seen on the unit.

## Results

| Image (boot text) | Coding | Frames a second | Reply | On the unit |
| --- | --- | --- | --- | --- |
| `2c0d8a3d…` | pixels, coded twice (count, then send) | 4.8 | 22 KB | |
| `e15f4ca6…` | the same, timed | 5.9 | 17.6 KB | 62 ms coding, 102 ms coding again and sending |
| `d396ae92…` | pixels, coded once into a buffer | 10.3, 11.3 with the host's quiet reads and window | 23 KB | 39 ms coding |
| `5b1a1be8…` (boot-5) | two-pixel words | 7.3 | 44 KB | 28 ms coding, 102 ms sending |
| `eab6eac0…` (boot-6, breathing line) | changes since the frame before | 27.8 | 0.9 KB | 31 ms coding, 1.9 ms sending |
| `60e8474a…` (boot-7, breathing line) | the same, eight words a comparing step | 30.5; 15 by default since | 0.6 KB | 25 ms coding, 1.4 ms sending |
