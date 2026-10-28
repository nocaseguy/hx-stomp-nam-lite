# Running a build from RAM

You can try a built `.hxf` on the Stomp without installing it. The firmware runs from the Stomp's SDRAM for one session, and nothing is written to the eMMC. Turn the Stomp off and on and it starts whatever is installed, as before.

**Status:** both ways have run NAM A2 Lite on a real HX Stomp: the command line (`tools/hxf_ram.py`, the loader and the hook) and the browser version on the setup page (`web/ramrun.js`, the same steps over WebUSB). Neither has been tried on an XL.

## From the setup page

Step 3 of the [setup page](https://nocaseguy.github.io/hx-stomp-nam-lite/web/) has a **Run from RAM** button once step 2 has built the firmware. It needs:

- Chrome or Edge on a computer (WebUSB);
- HX Edit and Line 6 Updater closed, because they hold the USB connection;
- stock 3.80.0 (or this same build) installed on the Stomp; see [The eMMC](#the-emmc).

The browser asks for a device three times: the HX Stomp itself, the Stomp in update mode (`1fc9:000c`, often shown as "LPC" or as an unknown device) and the RAM loader (`1209:0001`). The last two are new USB devices each time the Stomp restarts, so the browser doesn't remember them. If it ever already has permission for one, the page goes on without the click.

On Windows the browser may not see the Stomp, because Line 6's driver holds it. On Linux the user needs access to the three USB devices (a udev rule).

## From the command line

```sh
pip install pyusb                    # and libusb
# Hold Page Right while you turn the Stomp on (update mode, dark screen), then:
dfu-util -d 1fc9:000c -a 0 -D tools/ramboot/firmware-ramboot.dfu
python3 tools/hxf_ram.py run build/HX_Stomp_v3.80.0_NAM_A2_Lite.hxf --stock HX_Stomp_v3.80.0_0x103966115.hxf
```

dfu-util may report an I/O error at the end: the loader has started and left update mode. `hxf_ram.py plan` makes the same checks and layout without a unit (`--out DIR` writes what would be sent), and `hxf_ram.py info` shows what the loader reports.

## What to expect

- What you change during the run (presets, settings, imported IRs) goes to SDRAM and is gone at power-off. Import captures with the normal firmware first. (`--writes pass` sends writes outside the overlay to the card instead.)
- Knobs can react slowly during a RAM run, on every amp. An installed firmware doesn't do that.
- If a User IR slot model stays silent, run it again before looking further. This has happened on some RAM runs and not on others of the same image.
- If anything hangs, turn the Stomp off and on.

## How it works

1. **Update mode.** The page asks the running Stomp to restart in update mode, the same way Line 6 Updater does. It opens a message stream to port 0xEF on vendor interface 0 and sends update command 2. The Stomp then leaves `BootIntoDfu!` in RAM and resets, and its bootloader starts the boot ROM's DFU loader. Holding Page Right at power-up skips this step.
2. **The RAM loader** (`src/ramboot/ramboot.c`, a 4 KB image) is sent to the boot ROM over DFU. It sets the clocks the way the stock bootloader does (PLL1 at 204 MHz), then starts the SDRAM (EMC at 102 MHz) and the eMMC, read only. The image contains no eMMC write. Vendor requests on the control pipe (`src/ramboot/ramboot.h`) write SDRAM 4 KB at a time and return CRC-32s of SDRAM and of eMMC sectors. `GO` starts the application.
3. **The application** (entry 0 of the build) is checked as the bootloader checks it: magic, size, CRC-32, flags and segment ranges. Segments for SDRAM go straight to their addresses. Segments for internal SRAM are staged in SDRAM and copied by a small routine at 0x10090000 just before the jump, because the loader itself runs in SRAM. The routine fills the parameter block as the bootloader does and jumps with interrupts off.
4. **The overlay.** Each of the other entries is compared with the stock `.hxf`, 512 bytes at a time, at its sectors on the eMMC. Every sector that differs, and every sector past the end of the stock entry, goes into a table in SDRAM. The application reaches the eMMC only through two functions, `read_blocks` and `write_blocks`. `hxf_ram.py` overwrites the first 8 bytes of each with a jump to `src/ramboot/ramboot_hook.c`. The hook serves overlay sectors from SDRAM and passes every other sector to the original function. For NAM A2 Lite the overlay is about 4,250 sectors of entries 2, 3 and 4, and the whole upload is about 3 MB.

SDRAM use: the application keeps below 0x28E50000. The hook, the overlay and the write pool sit at 0x29000000..0x29E00000, and staging and the boot descriptor at 0x29E00000..0x29F00000, under the bootloader's framebuffers. The hook addresses are those of the 3.80.0 application. `hxf_ram.py` refuses any other version.

## The eMMC

The overlay holds only the sectors that differ from stock, so every other sector is read from the card. The Stomp must therefore have stock 3.80.0 installed, or this same build, which matches stock wherever the overlay doesn't cover. If the loader can start the eMMC, the run first compares the CRC of every sector it will read with stock and stops if one differs. If the loader cannot start the eMMC, which has happened on the unit, the check is skipped and the log says so. A run against another installed version would most likely hang, and turning the Stomp off and on recovers.

## Rebuilding the loader

`tools/ramboot/firmware-ramboot.dfu` and `tools/ramboot/ramboot-hook.bin` are kept built, so the page and `hxf_ram.py` need no toolchain. To rebuild them, install `arm-none-eabi-gcc` and run `make -C src/ramboot`. `tests/test_ramrun.py` checks that they match the source whenever the toolchain is installed.
