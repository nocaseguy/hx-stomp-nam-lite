/* ramboot.h - the memory map and request numbers shared by the RAM loader
 * (ramboot.c), its hook (ramboot_hook.c) and the host tool
 * (tools/hxf_ram.py and web/ramrun.js keep a copy of these numbers: change all three).
 * Why these addresses: RAM_RUN.md. */
#ifndef RAMBOOT_H
#define RAMBOOT_H

#define RB_VERSION      1u

/* SDRAM the stock application never names (RAM_RUN.md): the
 * hook and the overlay from RB_HOOK_BASE (0x28E3FADC..0x29000000 is left to
 * the application's code segment, which add-model makes longer), the SRAM
 * segments staged from RB_STAGE_BASE until the jump, the boot descriptor at
 * RB_DESC. */
#define RB_HOOK_BASE    0x29000000u
#define RB_STAGE_BASE   0x29E00000u
#define RB_DESC         0x29EFF000u
#define RB_FREE_END     0x29F00000u

/* Where the copy-and-jump routine runs: above all the application uses in
 * SRAM1 (its data, bss and stack end at 0x100832d0). */
#define RB_STUB_ADDR    0x10090000u

/* Vendor requests on the control pipe (usb_mon.h's own 1 and 2 stay). */
#define RB_REQ_INFO     0x20u   /* IN 64: "RAMB", version, flags, ... */
#define RB_REQ_ADDR     0x21u   /* OUT 0: pointer = wValue | wIndex << 16 */
#define RB_REQ_DATA     0x22u   /* OUT n <= RB_CHUNK: n bytes at the pointer, which moves on */
#define RB_REQ_LEN      0x23u   /* OUT 0: length = wValue | wIndex << 16 */
#define RB_REQ_CRC      0x24u   /* IN 4: CRC-32 of SDRAM [pointer, pointer + length) */
#define RB_REQ_EMMC_CRC 0x25u   /* IN 8: CRC-32 of eMMC sectors [wValue | wIndex << 16, + length), status */
#define RB_REQ_GO       0x26u   /* OUT 0, wValue RB_GO_KEY: boot from the descriptor at RB_DESC */
#define RB_GO_KEY       0x60B0u
#define RB_CHUNK        4096u

/* The boot descriptor: what the stock bootloader would have done. */
#define RB_DESC_MAGIC   0x47425852u     /* "RXBG" */
#define RB_MAX_COPIES   16u
/* struct { u32 magic, entry, ncopies, param; struct { u32 dst, src, len; } copy[ncopies]; } */

#endif
