/* ramboot.c - run a (changed) HX Stomp .hxf from RAM, writing nothing to the
 * eMMC (tools/hxf_ram.py; how and why: RAM_RUN.md).
 *
 * A RAM image like every other: Page Right at power-up, then dfu-util. It does
 * what the stock bootloader does before it starts the application, and takes
 * the rest from the computer:
 *   1. clocks as the bootloader sets them (PLL1 at 204 MHz), then the SDRAM
 *      (sdram.h, the EMC at half the core clock: 102 MHz as stock), then the
 *      eMMC, read only (emmc.h), so the computer can check that the unit holds
 *      the stock firmware the overlay was made against;
 *   2. the computer writes the application's segments, the hook and the
 *      overlay into SDRAM (RB_REQ_ADDR / RB_REQ_DATA) and checks them
 *      (RB_REQ_CRC); segments meant for SRAM are staged in SDRAM;
 *   3. RB_REQ_GO: USB off, the SD clock back as the bootloader leaves it, a
 *      copy-and-jump routine at RB_STUB_ADDR copies the staged segments and
 *      jumps to the entry point the way the bootloader does (interrupts off,
 *      r0 = 3).
 * There is no eMMC write in this image. 'D' (usb_mon.h) goes back to DFU. */
#include <stdint.h>
#include "lpc4350.h"
#include "dfu.h"
#include "emmc.h"
#include "ramboot.h"

static void spin(uint32_t n) { while (n--) __asm volatile ("nop"); }
#include "sdram.h"

static int vendor(const uint8_t *s);
#define USB_VENDOR(s) vendor(s)
#include "usb_mon.h"

#define CGU_IDIVA_CTRL     REG32(CGU_BASE + 0x048)
#define CGU_BASE_SPIFI_CLK REG32(CGU_BASE + 0x070)
#define CGU_BASE_OUT_CLK   REG32(CGU_BASE + 0x0AC)
#define CGU_PLL1_SEL_XTAL  0x06000000u
#define CGU_SEL_PLL1       0x09000800u  /* PLL1, autoblock */
#define NVIC_ICER(n)       REG32(0xE000E180u + 4u * (n))
#define NVIC_ICPR(n)       REG32(0xE000E280u + 4u * (n))

static uint8_t chunk[RB_CHUNK] __attribute__((aligned(4096)));
static uint32_t crc_table[256];
static uint32_t ptr, len32, flags, emmc_status = 0xFFFFFFFFu, sdram_ok;
static uint32_t pending_len;
static volatile int go;

/* The bootloader's clock set-up (0x14002978, called for 204 MHz): crystal on,
 * PLL1 = 12 MHz x 17 first through its divider (102 MHz), the core on it,
 * then direct (204 MHz); the peripheral bases on PLL1, IDIVA = PLL1 / 4,
 * SPIFI on the IRC. */
static void clocks_as_bootloader(void) {
    CGU_BASE_M4_CLK = (CGU_BASE_M4_CLK & ~0x1F000000u) | 0x01000000u;   /* core on the IRC meanwhile */
    CGU_XTAL_OSC_CTRL &= ~4u;                   /* low-frequency mode */
    CGU_XTAL_OSC_CTRL &= ~1u;                   /* oscillator on */
    spin(10000);
    CGU_PLL1_CTRL = CGU_PLL1_SEL_XTAL | 0x10u << 16;                    /* MSEL 16: x17, through the divider */
    for (uint32_t t = 0; !(CGU_PLL1_STAT & 1u); ++t) if (t > 10000000u) return;
    CGU_BASE_M4_CLK = (CGU_BASE_M4_CLK & ~0x1F000000u) | 0x09000000u;   /* core on PLL1 */
    spin(10000);
    CGU_PLL1_CTRL |= 0x80u;                     /* direct: 204 MHz */
    CGU_BASE_OUT_CLK = (CGU_BASE_OUT_CLK & ~0x1F000000u) | 0x09000000u;
    CGU_IDIVA_CTRL = 0x0900080Cu;               /* PLL1 / 4, autoblock */
    CGU_BASE_APB1_CLK = CGU_SEL_PLL1;
    CGU_BASE_APB3_CLK = CGU_SEL_PLL1;
    CGU_BASE_SDIO_CLK = CGU_SEL_PLL1;
    CGU_BASE_SSP0_CLK = CGU_SEL_PLL1;
    CGU_BASE_SSP1_CLK = CGU_SEL_PLL1;
    for (unsigned i = 0; i < 4; ++i) REG32(CGU_BASE + 0x09C + 4u * i) = CGU_SEL_PLL1;   /* UART0..3 */
    CGU_BASE_SPIFI_CLK = 0x01000800u;
    CGU_BASE_SPIFI_CLK &= ~1u;
}

static void crc_init(void) {
    for (uint32_t i = 0; i < 256; ++i) {
        uint32_t c = i;
        for (int k = 0; k < 8; ++k) c = c & 1u ? 0xEDB88320u ^ c >> 1 : c >> 1;
        crc_table[i] = c;
    }
}
static uint32_t crc_more(uint32_t c, const uint8_t *p, uint32_t n) {
    while (n--) c = crc_table[(c ^ *p++) & 0xFFu] ^ c >> 8;
    return c;
}

static void put32(uint8_t *p, uint32_t v) { p[0] = v; p[1] = v >> 8; p[2] = v >> 16; p[3] = v >> 24; }

static int in_sdram(uint32_t a, uint32_t n) {
    return a >= SDRAM_BASE && a <= 0x2A000000u && n <= 0x2A000000u - a;
}

static void send_info(unsigned len) {
    static uint8_t b[64] __attribute__((aligned(4)));
    for (unsigned i = 0; i < sizeof b; ++i) b[i] = 0;
    b[0] = 'R'; b[1] = 'A'; b[2] = 'M'; b[3] = 'B';
    put32(b + 4, RB_VERSION);
    put32(b + 8, flags);                        /* 1 SDRAM up and tested, 2 eMMC up */
    put32(b + 12, sdram_core_mhz);
    put32(b + 16, sdram_emc_mhz);
    put32(b + 20, emmc_status);
    put32(b + 24, emmc_sectors);
    put32(b + 28, sdram_bad_at);
    put32(b + 32, RB_HOOK_BASE);
    put32(b + 36, RB_STAGE_BASE);
    put32(b + 40, RB_DESC);
    put32(b + 44, RB_FREE_END);
    put32(b + 48, RB_CHUNK);
    usb_send(b, sizeof b, len);
    (void)usb_puts; (void)usb_puthex;
}

static void data_done(void) {                   /* a chunk is in: into SDRAM at the pointer */
    uint32_t *d = (uint32_t *)ptr;
    const uint32_t *s = (const uint32_t *)chunk;
    for (uint32_t i = 0; i < pending_len / 4; ++i) d[i] = s[i];
    for (uint32_t i = pending_len & ~3u; i < pending_len; ++i) ((uint8_t *)ptr)[i] = chunk[i];
    ptr += pending_len;
    usb_ack();
}

static int vendor(const uint8_t *s) {
    unsigned type = s[0], req = s[1];
    uint32_t value = s[2] | s[3] << 8u, index = s[4] | s[5] << 8u, len = s[6] | s[7] << 8u;
    uint32_t arg = value | index << 16;
    static uint8_t r[8] __attribute__((aligned(4)));
    if (type == 0xC0 && req == RB_REQ_INFO) { send_info(len); return 1; }
    if (type == 0x40 && req == RB_REQ_ADDR) {
        if (!sdram_ok || !in_sdram(arg, 0)) { usb_stall(); return 1; }
        ptr = arg; usb_ack(); return 1;
    }
    if (type == 0x40 && req == RB_REQ_LEN) { len32 = arg; usb_ack(); return 1; }
    if (type == 0x40 && req == RB_REQ_DATA) {
        if (!sdram_ok || len > RB_CHUNK || !in_sdram(ptr, len)) { usb_stall(); return 1; }
        pending_len = len;
        usb_recv(chunk, len, data_done);
        return 1;
    }
    if (type == 0xC0 && req == RB_REQ_CRC) {
        if (!sdram_ok || !in_sdram(ptr, len32)) { usb_stall(); return 1; }
        put32(r, ~crc_more(0xFFFFFFFFu, (const uint8_t *)ptr, len32));
        usb_send(r, 4, len);
        return 1;
    }
    if (type == 0xC0 && req == RB_REQ_EMMC_CRC) {
        static uint32_t sec[128];
        if (emmc_status) { usb_stall(); return 1; }
        uint32_t c = 0xFFFFFFFFu, st = 0;
        for (uint32_t i = 0; i < len32 && !st; ++i) {
            st = emmc_read(arg + i, sec);
            c = crc_more(c, (const uint8_t *)sec, 512);     /* the host waits (its time-out is long) */
        }
        put32(r, ~c); put32(r + 4, st);
        usb_send(r, 8, len);
        return 1;
    }
    if (type == 0x40 && req == RB_REQ_GO) {
        const uint32_t *d = (const uint32_t *)RB_DESC;
        if (value != RB_GO_KEY || !sdram_ok || d[0] != RB_DESC_MAGIC || d[2] > RB_MAX_COPIES) { usb_stall(); return 1; }
        usb_ack();
        go = 1;
        return 1;
    }
    return 0;
}

/* Where a copy may go: the stock bootloader's own ranges (0x140021d0). */
static int allowed_dst(uint32_t a, uint32_t n) {
    static const uint32_t r[4][2] = {
        {0x10000000u, 0x10020000u}, {0x10080000u, 0x10092000u},
        {0x20000000u, 0x20010000u}, {0x28000000u, 0x29F00000u},
    };
    for (unsigned i = 0; i < 4; ++i)
        if (a >= r[i][0] && a <= r[i][1] && n <= r[i][1] - a) return 1;
    return 0;
}

/* Copies the staged segments and jumps; runs from RB_STUB_ADDR, so it is
 * written to need nothing but registers and to work at any address. */
extern const uint8_t ramboot_stub[], ramboot_stub_end[];
__asm__(
    ".text\n .align 2\n .thumb\n .global ramboot_stub\n .global ramboot_stub_end\n"
    ".thumb_func\n ramboot_stub:\n"
    "  cpsid i\n"
    "  ldr r1, [r0, #8]\n"                      /* number of copies */
    "  add r2, r0, #16\n"
    "1: cmp r1, #0\n beq 4f\n"
    "  ldmia r2!, {r3, r4, r5}\n"               /* dst, src, len */
    "2: cmp r5, #0\n beq 3f\n"
    "  ldr r6, [r4], #4\n str r6, [r3], #4\n subs r5, r5, #4\n b 2b\n"
    "3: subs r1, r1, #1\n b 1b\n"
    "4: ldr r1, [r0, #12]\n"                    /* the parameter block, as the bootloader fills it (0x14001dd8) */
    "  cbz r1, 5f\n"
    "  add r4, r1, #16\n str r4, [r1, #4]\n movs r4, #0\n str r4, [r1, #16]\n"
    "5: dsb\n isb\n"
    "  ldr r3, [r0, #4]\n"
    "  movs r0, #3\n"
    "  bx r3\n"
    ".align 2\n ramboot_stub_end:\n");

static void boot(void) {
    const uint32_t *d = (const uint32_t *)RB_DESC;
    for (uint32_t i = 0; i < d[2]; ++i) {
        uint32_t dst = d[4 + 3 * i], src = d[5 + 3 * i], n = d[6 + 3 * i];
        if (!allowed_dst(dst, n) || !in_sdram(src, n) || (n & 3u)) return;
    }
    for (uint32_t t = 0; t < 2000; ++t) { usb_poll(); spin(10000); }   /* let the status stage of GO finish */

    __asm volatile ("cpsid i");
    USB_CMD &= ~1u;                             /* stop, then reset the controller: the host sees it leave */
    USB_CMD |= 2u;
    for (uint32_t t = 0; USB_CMD & 2u; ++t) if (t > 1000000u) break;
    SYST_CSR = 0;
    for (unsigned i = 0; i < 8; ++i) { NVIC_ICER(i) = 0xFFFFFFFFu; NVIC_ICPR(i) = 0xFFFFFFFFu; }
    CGU_BASE_SDIO_CLK = CGU_SEL_PLL1;           /* as the bootloader leaves it; the application starts the card itself */

    uint8_t *to = (uint8_t *)RB_STUB_ADDR;
    const uint8_t *from = (const uint8_t *)((uint32_t)ramboot_stub & ~1u);
    for (uint32_t i = 0; i < (uint32_t)(ramboot_stub_end - from); ++i) to[i] = from[i];
    __asm volatile ("dsb\n isb");
    ((void (*)(const uint32_t *))(RB_STUB_ADDR | 1u))(d);
}

int main(void) {
    crc_init();
    clocks_as_bootloader();
    if (sdram_start() && sdram_test(RB_STAGE_BASE, 0x100000u)) { sdram_ok = 1; flags |= 1u; }
    emmc_status = emmc_start();                 /* it can take a second, and USB wants quick answers */
    if (!emmc_status) flags |= 2u;
    usb_start();
    for (;;) {
        uint32_t c;
        usb_poll();
        if (usb_command(&c) && (c & 0xFF) == 'D') dfu_reboot();
        if (go) { go = 0; boot(); }             /* back here only if the descriptor was refused */
    }
}
