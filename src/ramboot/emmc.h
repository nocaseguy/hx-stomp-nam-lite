/* emmc.h - the HX Stomp's eMMC through the LPC4350's SD/MMC controller
 * (Synopsys DesignWare, 0x40004000), for ramboot.c (read only).
 *
 * What the stock bootloader does, read from it: pins PC_0 SD_CLK, PC_10 SD_CMD,
 * PC_4..7 and PC_11..14 SD_DAT0..7, PC_2 SD_RST, PC_9 SD_POW, all function 7; power and reset
 * through the controller's PWREN and RST_N; the command words below. This
 * driver keeps it simpler than stock: a 1-bit bus at 12 MHz from the IRC (so
 * it does not depend on how the DFU loader left the PLLs), one 512-byte
 * block per command, data through the FIFO (no DMA), no interrupts, and a
 * timeout on every wait.
 *
 *   emmc_start()            0, or the step that failed (0x1xx) with the
 *                           controller's raw status in the low bits
 *   emmc_read(s, buf)       one sector; 0 or an error
 *   emmc_write(s, buf)      one sector, only with EMMC_WRITES defined, and
 *                           refused at or above EMMC_WRITE_LIMIT; waits until
 *                           the card has finished programming
 * emmc_cid[4], emmc_ocr, emmc_sectors (EXT_CSD SEC_COUNT) after emmc_start(). */
#ifndef EMMC_H
#define EMMC_H
#include <stdint.h>
#include "lpc4350.h"

#ifndef EMMC_WRITE_LIMIT
#define EMMC_WRITE_LIMIT 0x8000u                /* the application partition ends here */
#endif

#define SDMMC(o)        REG32(0x40004000u + (o))
#define SD_CTRL         SDMMC(0x000)
#define SD_PWREN        SDMMC(0x004)
#define SD_CLKDIV       SDMMC(0x008)
#define SD_CLKSRC       SDMMC(0x00C)
#define SD_CLKENA       SDMMC(0x010)
#define SD_TMOUT        SDMMC(0x014)
#define SD_CTYPE        SDMMC(0x018)
#define SD_BLKSIZ       SDMMC(0x01C)
#define SD_BYTCNT       SDMMC(0x020)
#define SD_INTMASK      SDMMC(0x024)
#define SD_CMDARG       SDMMC(0x028)
#define SD_CMD          SDMMC(0x02C)
#define SD_RESP(n)      SDMMC(0x030 + 4u * (n))
#define SD_RINTSTS      SDMMC(0x044)
#define SD_STATUS       SDMMC(0x048)
#define SD_FIFOTH       SDMMC(0x04C)
#define SD_RST_N        SDMMC(0x078)
#define SD_BMOD         SDMMC(0x080)
#define SD_DATA         SDMMC(0x100)
#define CGU_BASE_SDIO_CLK REG32(CGU_BASE + 0x090)

/* RINTSTS */
#define SD_RE   (1u << 1)
#define SD_CD   (1u << 2)
#define SD_DTO  (1u << 3)
#define SD_TXDR (1u << 4)
#define SD_RXDR (1u << 5)
#define SD_DCRC (1u << 7)
#define SD_RTO  (1u << 8)
#define SD_DRTO (1u << 9)
#define SD_HTO  (1u << 10)
#define SD_FRUN (1u << 11)
#define SD_HLE  (1u << 12)
#define SD_SBE  (1u << 13)
#define SD_EBE  (1u << 15)
#define SD_CMD_ERR  (SD_RE | SD_RTO | SD_HLE)
#define SD_DATA_ERR (SD_DCRC | SD_DRTO | SD_HTO | SD_FRUN | SD_SBE | SD_EBE)

/* Command words as the stock driver uses them (start bit added when sent). */
#define W_CMD0   0x8000u        /* send_init, no response */
#define W_CMD1   0x8041u        /* send_init, response */
#define W_CMD2   0x00C2u        /* long response */
#define W_CMD3   0x0043u
#define W_CMD7   0x2007u        /* wait_prvdata */
#define W_CMD8   0x2208u        /* SEND_EXT_CSD: data in */
#define W_CMD9   0x00C9u
#define W_CMD13  0x004Du
#define W_CMD17  0x2251u        /* read one block */
#define W_CMD24  0x2658u        /* write one block */
#define W_CLOCK  0x202000u      /* update the clock registers only */

#define EMMC_RCA 1u

static uint32_t emmc_cid[4], emmc_ocr, emmc_sectors;
static int emmc_sector_addressing;

static void emmc_spin(uint32_t n) { while (n--) __asm volatile ("nop"); }
static void emmc_ms(uint32_t ms) { while (ms--) emmc_spin(60000); }   /* at least 1 ms up to 204 MHz */

static int emmc_issue(uint32_t word, uint32_t arg) {
    for (uint32_t t = 0; SD_CMD & (1u << 31); ++t)
        if (t > 1000000u) return -1;
    SD_CMDARG = arg;
    SD_CMD = word | 1u << 31 | 1u << 29;        /* start, use the hold register */
    for (uint32_t t = 0; SD_CMD & (1u << 31); ++t)
        if (t > 1000000u) return -2;
    return 0;
}

static int emmc_clock(uint32_t div) {           /* card clock = 12 MHz / (2 div), div 0 = 12 MHz */
    SD_CLKENA = 0;
    if (emmc_issue(W_CLOCK, 0)) return -1;
    SD_CLKSRC = 0;
    SD_CLKDIV = div;
    if (emmc_issue(W_CLOCK, 0)) return -1;
    SD_CLKENA = 1;
    return emmc_issue(W_CLOCK, 0);
}

/* A command and its response: 0, or the RINTSTS error bits (or 1 for a time-out here). */
static uint32_t emmc_cmd(uint32_t word, uint32_t arg) {
    SD_RINTSTS = 0xFFFFFFFFu;
    if (emmc_issue(word, arg)) return 1;
    for (uint32_t t = 0; !(SD_RINTSTS & (SD_CD | SD_CMD_ERR)); ++t)
        if (t > 2000000u) return 1;
    return SD_RINTSTS & SD_CMD_ERR;
}

/* CMD13 until the card is in TRAN with READY_FOR_DATA (or up to about 1 s). */
static uint32_t emmc_ready(void) {
    for (unsigned i = 0; i < 1000; ++i) {
        uint32_t e = emmc_cmd(W_CMD13, EMMC_RCA << 16);
        if (e) return e;
        uint32_t st = SD_RESP(0);
        if ((st >> 9 & 15u) == 4u && (st & 1u << 8)) return 0;
        emmc_ms(1);
    }
    return 2;
}

static uint32_t emmc_data_wait(void) {
    for (uint32_t t = 0; !(SD_RINTSTS & (SD_DTO | SD_DATA_ERR)); ++t)
        if (t > 4000000u) return 3;
    return SD_RINTSTS & SD_DATA_ERR;
}

/* One 512-byte block in: the command, then the FIFO emptied word by word. */
static uint32_t emmc_block_in(uint32_t word, uint32_t arg, uint32_t *buf) {
    SD_CTRL |= 2u;                              /* FIFO reset */
    for (uint32_t t = 0; SD_CTRL & 2u; ++t) if (t > 100000u) return 4;
    SD_BLKSIZ = 512;
    SD_BYTCNT = 512;
    uint32_t e = emmc_cmd(word, arg);
    if (e) return e;
    unsigned n = 0;
    for (uint32_t t = 0; n < 128; ++t) {
        uint32_t r = SD_RINTSTS;
        if (r & SD_DATA_ERR) return r & SD_DATA_ERR;
        unsigned have = SD_STATUS >> 17 & 0x1FFFu;
        while (have-- && n < 128) buf[n++] = SD_DATA;
        if (t > 4000000u) return 5;
    }
    return emmc_data_wait();
}

static uint32_t emmc_start(void) {
    static const uint8_t pins[] = { 4, 5, 6, 7, 10, 11, 12, 13, 14 };     /* DAT0..3, CMD, DAT4..7 */
    SCU_SFS(0xC, 0) = 0x77;                     /* SD_CLK */
    for (unsigned i = 0; i < sizeof pins; ++i) SCU_SFS(0xC, pins[i]) = 0xF7;
    SCU_SFS(0xC, 2) = 0x17;                     /* SD_RST */
    SCU_SFS(0xC, 9) = 0x17;                     /* SD_POW */
    CGU_BASE_SDIO_CLK = 0x01000800u;            /* IRC 12 MHz, autoblock */

    SD_BMOD = 1;                                /* DMA reset; no DMA used */
    SD_CTRL = 7;                                /* controller, FIFO and DMA reset */
    for (uint32_t t = 0; SD_CTRL & 7u; ++t) if (t > 100000u) return 0x101;
    SD_CTRL = 0;                                /* no interrupts, no DMA */
    SD_BMOD = 0;
    SD_INTMASK = 0;
    SD_RINTSTS = 0xFFFFFFFFu;
    SD_TMOUT = 0xFFFFFFFFu;
    SD_FIFOTH = 0x100F0010u;
    SD_CTYPE = 0;                               /* 1-bit bus */

    SD_PWREN = 0; emmc_ms(250);                 /* power off and on, reset low and high, as stock */
    SD_PWREN = 1; emmc_ms(250);
    SD_RST_N = 0; emmc_ms(25);
    SD_RST_N = 1; emmc_ms(25);
    if (emmc_clock(15)) return 0x102;           /* 400 kHz */

    emmc_cmd(W_CMD0, 0);
    emmc_ms(25);
    if (emmc_cmd(W_CMD1, 0)) return 0x103;
    uint32_t arg = (SD_RESP(0) & 0x40FF8000u) | 0x40000000u;
    unsigned tries = 0;
    do {
        if (emmc_cmd(W_CMD1, arg)) return 0x104;
        emmc_ms(10);
    } while (!(SD_RESP(0) & 1u << 31) && ++tries < 100);
    if (!(SD_RESP(0) & 1u << 31)) return 0x105;
    emmc_ocr = SD_RESP(0);
    emmc_sector_addressing = (emmc_ocr >> 29 & 3u) == 2u;      /* access mode: sector */

    if (emmc_cmd(W_CMD2, 0)) return 0x106;
    for (unsigned i = 0; i < 4; ++i) emmc_cid[i] = SD_RESP(i);
    if (emmc_cmd(W_CMD3, EMMC_RCA << 16)) return 0x107;
    if (emmc_cmd(W_CMD9, EMMC_RCA << 16)) return 0x108;
    if (emmc_cmd(W_CMD7, EMMC_RCA << 16)) return 0x109;
    if (emmc_clock(0)) return 0x10A;            /* 12 MHz */
    if (emmc_ready()) return 0x10B;

    static uint32_t ext_csd[128];
    uint32_t e = emmc_block_in(W_CMD8, 0, ext_csd);
    if (e) return 0x100C0000u | e;
    emmc_sectors = ext_csd[212 / 4];            /* SEC_COUNT, bytes 212..215 */
    if (!emmc_sector_addressing && emmc_sectors > 4194304u) emmc_sector_addressing = 1;
    return 0;
}

static uint32_t emmc_addr(uint32_t sector) { return emmc_sector_addressing ? sector : sector * 512u; }

static uint32_t emmc_read(uint32_t sector, void *buf) {
    if (emmc_sectors && sector >= emmc_sectors) return 0x201;
    uint32_t e = emmc_ready();
    if (e) return 0x20000000u | e;
    e = emmc_block_in(W_CMD17, emmc_addr(sector), (uint32_t *)buf);
    return e ? 0x21000000u | e : 0;
}

#ifdef EMMC_WRITES
static uint32_t emmc_write(uint32_t sector, const void *buf) {
    if (sector >= EMMC_WRITE_LIMIT) return 0x301;           /* never outside the application partition */
    const uint32_t *w = (const uint32_t *)buf;
    uint32_t e = emmc_ready();
    if (e) return 0x30000000u | e;
    SD_CTRL |= 2u;
    for (uint32_t t = 0; SD_CTRL & 2u; ++t) if (t > 100000u) return 0x302;
    SD_BLKSIZ = 512;
    SD_BYTCNT = 512;
    e = emmc_cmd(W_CMD24, emmc_addr(sector));
    if (e) return 0x31000000u | e;
    unsigned n = 0;
    for (uint32_t t = 0; n < 128; ++t) {
        uint32_t r = SD_RINTSTS;
        if (r & SD_DATA_ERR) return 0x32000000u | (r & SD_DATA_ERR);
        unsigned room = 32u - (SD_STATUS >> 17 & 0x1FFFu);  /* the FIFO holds 32 words */
        while (room-- && n < 128) SD_DATA = w[n++];
        if (t > 4000000u) return 0x303;
    }
    e = emmc_data_wait();
    if (e) return 0x33000000u | e;
    e = emmc_ready();                           /* until the card has finished programming */
    return e ? 0x34000000u | e : 0;
}
#endif

#endif
