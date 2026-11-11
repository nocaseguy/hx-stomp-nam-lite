# The boot screen [verified offline]

The stock boot picture, drawn by the bootloader and then by the app, and the boot view's text. Status tags as in [conventions.md](../conventions.md).

The boot picture is drawn twice, by two programs, from two copies of the same pixels.

- **Stage 1, bootloader** (Entry 1, SPIFI XIP at `0x14000000`): a full 320x240 copy at `0x140068bc` (file offset `0x68bc`, `0x25800` bytes), the splash with 59 black rows below. `0x14002104..0x14002114`: `memcpy(0x29f00ca8, 0x140068bc, 0x4b000)` into its framebuffer, then shows it. Shown from power-on until the app takes over. No checksum beyond the L6IA ones (the vector table does not sum to 0).
- **Stage 2, app** (Entry 0): view constructor `0x28d92708`, paint `0x28d92950`, registered by the app's init at `0x28d92cfc`. It looks up images by name (`0x28db7718(name, &index)`): `HXStomp_Splash` (Entry 7 record 527 = Entry 8 item 527, 320x181 at `0x3e0fdc`) at (160, 240), top-aligned, falling back to `Logo_HXStomp` at (160, 90); `Icon_Firmware` with the text `   Firmware  ` `3.80.0` (`0xb1b1b1`) at y = 53. The loading bar is two rects at y = 121: a 320x1 track `0x660000` and a 2 px `0xff0000` bar whose width the paint sets from a float progress (clamped to 320).
- `Screen_Boot` (record 29, 320x240, the plain black LINE 6 / HX STOMP screen) has no name reference in Entry 0 or Entry 1. **[hypothesis]** unused.
- The P36Updater trailer contains a SPIFI driver (`Common SPIFI Command Set`), so the updater can write Entry 1. Entry 1's sub-header word +4 is `0x02990963` where every other entry has `0x03800000`. **[hypothesis]** a bootloader version that decides whether the updater rewrites SPIFI at all.
- Replacing Stage 2 is an in-place, same-size write of Entry 8 item 527 (115,840 bytes), and a RAM run serves it through the overlay. Replacing Stage 1 means reflashing the bootloader: a RAM run starts the app directly and cannot show it, and a broken bootloader may also lose the DFU path, which the bootloader itself starts.

What HXtra changes on it: [features/boot-splash.md](../features/boot-splash.md).
