/* ramboot_hook.c - the eMMC overlay the stock application runs with when it
 * is started from RAM (ramboot.c, tools/hxf_ram.py, RAM_RUN.md).
 *
 * The application reads and writes the eMMC through two functions only,
 * read_blocks(buf, sector, count) at 0x28da5354 and write_blocks at
 * 0x28da5708 (both return count * 512, or a negative error); every caller is
 * its sector-stream layer. hxf_ram.py puts `ldr.w pc, [pc]` and the address
 * of read_hook / write_hook over the first 8 bytes of each, and links this
 * blob at RB_HOOK_BASE, followed by the overlay: the 512-byte sectors of the
 * changed .hxf that differ from the stock one, as runs sorted by sector.
 *
 * Reads: sectors in the overlay (or written earlier, below) come from SDRAM;
 * the rest from the card through the original function. Writes: a sector of
 * the overlay is changed in SDRAM; any other sector goes to a pool in SDRAM
 * (RB_WRITES_RAM, the default: the eMMC is never written), or to the card
 * (RB_WRITES_PASS). Everything in SDRAM is gone at power-off.
 *
 * The original function's first three instructions, overwritten by the jump,
 * run in orig_read / orig_write, which then go on into the rest of it. */
#include <stdint.h>

#define RB_WRITES_RAM  0u
#define RB_WRITES_PASS 1u

struct run { uint32_t sector, count, data; };
struct table { uint32_t nruns; struct run run[]; };

/* Filled by hxf_ram.py; the offsets are part of the format (version 1). */
struct hdr {
    uint32_t magic, version;            /* 0x00 "RXBH", 1 */
    uint32_t read_hook, write_hook;     /* 0x08 for the jumps put into the application */
    uint32_t card;                      /* 0x10 the literal the original's second instruction loads */
    uint32_t read_cont, write_cont;     /* 0x14 where the originals go on (Thumb addresses) */
    uint32_t table;                     /* 0x1c the overlay */
    uint32_t write_mode;                /* 0x20 RB_WRITES_RAM or RB_WRITES_PASS */
    uint32_t pool_slots, pool_data, pool_sectors;   /* 0x24 written sectors: keys (sector + 1), data */
    uint32_t pool_used;                 /* 0x30 counters, for a later look with a debugger */
    uint32_t reads, read_hits, writes, write_hits, pool_full, pass_writes;
};

int read_hook(uint8_t *buf, uint32_t sector, int count);
int write_hook(const uint8_t *buf, uint32_t sector, int count);

__attribute__((section(".hdr"), used)) struct hdr rb_hdr = {
    .magic = 0x48425852u, .version = 1,
    .read_hook = (uint32_t)read_hook, .write_hook = (uint32_t)write_hook,
};

int orig_read(uint8_t *buf, uint32_t sector, int count);
int orig_write(const uint8_t *buf, uint32_t sector, int count);
/* The originals begin: push.w {r4-r11, lr}; ldr r5, =card; ldr.w r3, [r5, #0x248]. */
__asm__(
    ".text\n .align 2\n .thumb\n"
    ".global orig_read\n .thumb_func\n orig_read:\n"
    "  push.w {r4, r5, r6, r7, r8, r9, r10, r11, lr}\n"
    "  ldr r5, =rb_hdr\n ldr r12, [r5, #0x14]\n ldr r5, [r5, #0x10]\n"
    "  ldr.w r3, [r5, #0x248]\n"
    "  bx r12\n"
    ".global orig_write\n .thumb_func\n orig_write:\n"
    "  push.w {r4, r5, r6, r7, r8, r9, r10, r11, lr}\n"
    "  ldr r5, =rb_hdr\n ldr r12, [r5, #0x18]\n ldr r5, [r5, #0x10]\n"
    "  ldr.w r3, [r5, #0x248]\n"
    "  bx r12\n"
    ".ltorg\n");

static uint32_t irq_off(void) {
    uint32_t m;
    __asm volatile ("mrs %0, primask\n cpsid i" : "=r" (m) :: "memory");
    return m;
}
static void irq_restore(uint32_t m) { __asm volatile ("msr primask, %0" :: "r" (m) : "memory"); }

static void copy512(void *dst, const void *src) {
    if ((((uint32_t)dst | (uint32_t)src) & 3u) == 0) {
        uint32_t *d = dst; const uint32_t *s = src;
        for (int i = 0; i < 128; ++i) d[i] = s[i];
    } else {
        uint8_t *d = dst; const uint8_t *s = src;
        for (int i = 0; i < 512; ++i) d[i] = s[i];
    }
}

static uint8_t *overlay_find(uint32_t sector) {
    const struct table *t = (const struct table *)rb_hdr.table;
    uint32_t lo = 0, hi = t->nruns;
    while (lo < hi) {
        uint32_t mid = (lo + hi) / 2;
        const struct run *r = &t->run[mid];
        if (sector < r->sector) hi = mid;
        else if (sector - r->sector >= r->count) lo = mid + 1;
        else return (uint8_t *)(r->data + 512u * (sector - r->sector));
    }
    return 0;
}

/* The pool: open addressing on the sector number; a key is sector + 1, 0 empty. */
static uint8_t *pool_find(uint32_t sector, int add) {
    uint32_t n = rb_hdr.pool_sectors;
    if (!n) return 0;
    uint32_t *key = (uint32_t *)rb_hdr.pool_slots;
    uint32_t i = (sector * 2654435761u) % n;
    for (uint32_t k = 0; k < n; ++k, i = i + 1 == n ? 0 : i + 1) {
        if (key[i] == sector + 1) return (uint8_t *)(rb_hdr.pool_data + 512u * i);
        if (!key[i]) {
            if (!add || rb_hdr.pool_used * 4 >= n * 3) return 0;     /* keep a quarter free */
            key[i] = sector + 1;
            rb_hdr.pool_used++;
            return (uint8_t *)(rb_hdr.pool_data + 512u * i);
        }
    }
    return 0;
}

static uint8_t *find(uint32_t sector) {
    uint8_t *p = overlay_find(sector);
    return p ? p : pool_find(sector, 0);
}

int read_hook(uint8_t *buf, uint32_t sector, int count) {
    rb_hdr.reads++;
    if (count <= 0) return orig_read(buf, sector, count);
    int any = 0, all = 1;
    for (int i = 0; i < count; ++i) {
        uint32_t m = irq_off();
        int hit = find(sector + i) != 0;
        irq_restore(m);
        if (hit) any = 1; else all = 0;
    }
    if (!any) return orig_read(buf, sector, count);
    int r = all ? count * 512 : orig_read(buf, sector, count);
    if (r < 0) return r;
    for (int i = 0; i < count; ++i) {
        uint32_t m = irq_off();
        uint8_t *p = find(sector + i);
        if (p) { copy512(buf + 512 * i, p); rb_hdr.read_hits++; }
        irq_restore(m);
    }
    return r;
}

int write_hook(const uint8_t *buf, uint32_t sector, int count) {
    rb_hdr.writes++;
    if (count <= 0) return orig_write(buf, sector, count);
    int i = 0;
    while (i < count) {
        uint32_t m = irq_off();
        uint8_t *p = overlay_find(sector + i);
        if (p || rb_hdr.write_mode != RB_WRITES_PASS) {
            if (!p) p = pool_find(sector + i, 1);
            if (p) { copy512(p, buf + 512 * i); rb_hdr.write_hits++; }
            else rb_hdr.pool_full++;            /* dropped: the pool is full */
            irq_restore(m);
            ++i;
            continue;
        }
        irq_restore(m);
        int j = i + 1;                          /* a run of sectors outside the overlay: to the card */
        while (j < count && !overlay_find(sector + j)) ++j;
        int r = orig_write(buf + 512 * i, sector + i, j - i);
        if (r < 0) return r;
        rb_hdr.pass_writes += j - i;
        i = j;
    }
    return count * 512;
}
