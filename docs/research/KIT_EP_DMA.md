# External-port DMA on the ADSP-21469, and the kit-dmatest probe

2026-10-28. From Analog Devices documentation and the simulator. **Nothing here
has run on the unit yet.** The probe is `modules/kit-dmatest` in hx-stomp-kit.

Confidence labels:
- **verified (doc)**: stated in ADI's ADSP-214xx Hardware Reference or `def21469.h`. Quoted page given.
- **verified (sim)**: shown by the kit's ssim tests with a model of the channel. This shows what the kernel writes, not what the chip does.
- **likely**: follows from the documents plus one reasonable assumption.
- **guess**: no direct evidence.
- **open**: the unit run must answer it.

## Sources

1. *ADSP-214xx SHARC Processor Hardware Reference*, rev 1.1, part 82-000469-01 (Analog Devices). The text was extracted locally from the copy at <https://www.bdtic.com/download/adi/82-000469-01.pdf>. analog.com timed out (<https://www.analog.com/media/en/dsp-documentation/processor-manuals/ADSP-214xx_hwr_rev1.1.pdf>). The ADSP-21469 is a 2146x part, covered by this manual.
   - Ch. 3 "External Port": "External Port DMA" pp. 3-100..3-105; interrupts pp. 3-114..3-116; throughput pp. 3-117..3-119; effect latency p. 3-120; programming models pp. 3-121..3-125; Listing 3-3 "EPDMA With Read Optimization" p. 3-43; DDR2 address mapping p. 3-60..3-62.
   - Ch. 2 "I/O Processor": index registers and the 0x80000 internal offset, p. 2-4..2-5; general DMA procedure p. 2-51; default programmable-interrupt map p. 2-48.
   - App. A: DMACx bits pp. A-60..A-63; register listing pp. A-273..A-274.
   - Ch. 23: external-port boot uses DMAC0 = 0x1000001 and EIEP0 = 0x4000000, pp. 23-10..23-11.
2. `def21469.h` (ADI, "(c) Copyright 2009-2011 Analog Devices"), as vendored in djyos/djyos: <https://github.com/djyos/djyos/blob/master/djysdk/djysrc/third/firmware/Sharc21469/include/def21469.h>. Lines 109..148 hold the EP and DMA addresses, 1752..1790 EPCTL, 1862..1879 the DMAC bits and 2494 PMCTL1 EPOFF. Every address agrees with source 1.
3. The ADSP-21469 data sheet: I could not fetch it (analog.com timed out; mirrors returned 403). Nothing below depends on it.
4. Stock image evidence: `research/KIT_NAM_A2_FULL.md` §1. The image has no immediate reference to 0x1802..0x1811 or 0x181f..0x1850, and it sets up only 0x1801, 0x1812..0x181e, 0x1851 and 0x1856.

## Register map (channel 0; channel 1 is +0x10, DMAC1 = 0x180c)

| Register | IOP address | What | Confidence |
|---|---|---|---|
| EPCTL | 0x1801 | External port global control (arbitration, freezing). Reset 0xF0. **The kit does not touch it.** | verified (doc, A-273) |
| AMICTL0..3, AMISTAT | 0x1804..0x1807, 0x180a | Async memory interface. Not used. | verified (doc) |
| **DMAC0** | **0x180b** | Channel 0 control/status. Reset 0. | verified (doc, A-273) |
| DMAC1 | 0x180c | Channel 1 control/status | verified (doc) |
| DDR2CTL0..5, DDR2RRC, DDR2STAT0 | 0x1812..0x1817, 0x181d, 0x181e | DDR2 controller. **Never write them.** | verified (doc) |
| **EIEP0** | **0x1820** | External index: start address, 28 bits | verified (doc) |
| **EMEP0** | **0x1821** | External modifier | verified (doc) |
| ECEP0 | 0x1822 | External count. **Read only**: an alias of ICEP0, updated when ICEP0 is written (p. 3-103) | verified (doc) |
| **IIEP0** | **0x1823** | Internal index: 19 bits on top of an internal offset of 0x80000 (p. 2-4) | verified (doc) |
| **IMEP0** | **0x1824** | Internal modifier | verified (doc) |
| **ICEP0** | **0x1825** | Count. 0 means 2^16 transfers and is forbidden in a chain (pp. 2-27..2-28, 3-124) | verified (doc) |
| **CPEP0** | **0x1826** | Chain pointer. 0 = no chain | verified (doc) |
| EBEP0, TPEP0, ELEP0 | 0x1827, 0x1828, 0x1829 | Circular base, tap-list pointer, length (circular, delay-line and scatter modes) | verified (doc) |
| EPTC0 (TCEP0) | 0x182b | Tap count | verified (doc) |
| DFEP0 | 0x182c | Data FIFO | verified (doc) |
| DDR2STAT1, DDR2PADCTL0/1 | 0x1840..0x1842 | DDR2 | verified (doc, header only) |
| DLL0CTL0/1, DLL1CTL0/1 | 0x1850/0x1851, 0x1855/0x1856 | DDR2 DLLs | verified (doc, header only) |

So the stock image's untouched ranges contain all of EP DMA: DMAC0/1 sit in 0x1802..0x1811, and both parameter blocks sit in 0x181f..0x1850. The registers it does set up are EPCTL, the DDR2 controller and the DLLs. That fits a program that never uses EP DMA: **likely**. Static analysis would not see the registers reached through a computed pointer.

### DMACx bits (p. A-61..A-63; def21469.h 1862..1879)

| Bit | Name | Meaning |
|---|---|---|
| 0 | DEN | DMA enable (the manual also calls it DMAEN) |
| 1 | TRAN | 0 = write to internal memory (external reads); 1 = read internal memory (external writes) |
| 2 | CHEN | chaining |
| 3 | DLEN | delay-line DMA (needs CHEN) |
| 4 | CBEN | circular buffering |
| 5 | DFLSH | flush the FIFO, write-one-to-clear; clears DFS |
| 7 | WRBEN | write back EIEP (chained only) |
| 8 | OFCEN | control bits from CPEP per TCB |
| 9 | TLEN | scatter/gather (tap list) |
| 12 | INTIRT | 0 = interrupt on access completion (default); 1 = on internal completion |
| 17..16 | DFS (RO) | FIFO: 00 empty, 01 partly full, 11 full |
| 20 | DMAS (RO) | 1 = DMA in progress |
| 21 | CHS (RO) | chain loading |
| 22 | TLS (RO) | tap list loading |
| 23 | WBS (RO) | write-back active |
| 24 | EXTS (RO) | 1 = the external interface has an access pending |
| 25 | DIRS (RO) | direction status; follows TRAN in standard DMA |

### Programming a standard (non-chained) DMA

These steps come from the manual: the standard-DMA steps on p. 3-121, Listing 3-3 on p. 3-43, and disabling on p. 3-124. kit-dmatest uses exactly this order.

```
DMAC0 = DFLSH                 // flush the FIFO, channel off
CPEP0 = 0                     // no chain (general procedure p. 2-51: clear the chain pointer)
IIEP0 = internal address      // e.g. 0xe5000; the top bit above 19 is implied (offset 0x80000)
IMEP0 = 1
ICEP0 = N                     // ECEP0 follows
EMEP0 = 1
EIEP0 = external address      // the same normal-word address the core uses, e.g. 0x324800
DMAC0 = DEN [| TRAN]          // go
... poll DMAC0 until DMAS == 0 and EXTS == 0 ...
DMAC0 = 0                     // off again
```

- **Step 1 of the manual** says to configure AMICTL/SDCTL (DDR2) first. The stock boot already sets up the DDR2 controller, since the core reads DDR2. **The kit writes no DDR2 or EPCTL register.** EPCTL resets to 0xF0, rotating priority with no freezing (A-273). Whether the stock changes it does not matter for a plain DMA: **likely**.
- **Addresses.** "The non multiplexed address that is seen from the core/DMA is referred to as IA31–0" (p. 3-60), so DMA uses the core's addresses. Boot loads EIEP0 = 0x4000000, the bank 1 start, in the same normal-word space (p. 23-11). For x16 DDR2, "the processor supports only 32-bit data accesses. The DDR2 controller performs two 16-bit accesses" (p. 3-62). So EIEP = 0x324800 with EMEP = 1 moves consecutive 32-bit words, exactly as the core reads them: **likely** (doc + one assumption: the same holds for the 21469's DDR2 bank 0 at 0x200000..).
- **Internal addresses** are 19 bits plus 0x80000 (p. 2-4; worked example p. 8-11: 0xC0100 becomes 0x40100). Writing the full normal-word address 0xe5000 is fine: **verified (doc)**.
- **Write latency.** A configured external-port register takes effect after 4 PCLK (p. 3-120). A poll straight after the enable could still read DMAS = 0. kit-dmatest waits 32 core cycles after the enable before any poll.
- **Completion.** In the default mode (INTIRT = 0), for writes to external memory, "the DMA complete interrupt is generated only after external writes ... are done". For reads, it comes "when the internal DMA writes complete" (p. 3-115). Polling DMAS = 0 and EXTS = 0 covers both directions: **likely**. The manual does not say whether DMAS falls before or after the EXTS drain on a write, so the kit waits for both.
- **Disabling mid-transfer** (p. 3-124): clear DEN, wait for EXTS = 0, write 0 to ICEP and DMAC. kit-dmatest does this on a timeout.
- **Interrupts.** EP DMA channel 0 completion is programmable interrupt P9I by default, and channel 1 is P13I (p. 2-48, table at p. 3-114). In `def21469.h`'s LIRPTL layout, EP0I is latch bit 3, EP0IMSK mask bit 13 and EP0IMSKP bit 23. Channel 1 uses bits 7 and 17. The latch is set at completion even while the interrupt is masked: **likely**. If the stock had EP0IMSK set, our DMA would vector into whatever the stock IVT slot holds. kit-dmatest reads LIRPTL first and refuses to run when bit 13 is set. It assumes PICR keeps the default mapping: **likely**, since the stock never touches EP DMA.

### Throughput the manual gives (p. 3-118, 16-bit DDR2, 400 MHz core)

DMA reads: 473 MB/s at 133 MHz DDR2 (ratio 1:3), 700 MB/s at 200 MHz (1:2). Writes: 481 and 732 MB/s. Core reads: 495 and 742 MB/s. Those core figures come from a long sequential loop. kit-memtest measured core DDR2 reads on the unit at about 30 cycles a word (`research/KIT_NAM_A2_FULL.md`). On the unit's 450 MHz core, then, 1,024 words (4 KB) by DMA should take roughly **2,500..3,900 core cycles** at those rates: a **guess**, since the unit's DDR2 clock is not known. If the transfer runs in the background, the core pays only for programming the channel, about 10 IOP writes. A block that needs 768 words, like a staged NAM layer, would then cost a few hundred cycles of core time instead of about 15k.

## The probe: modules/kit-dmatest (hx-stomp-kit)

- Preset ID 605 (sdk/preset_ids.toml), model "Kit DMA Test", Clarity host. Knobs: **Work** (pid 5, 0..1 → 0..20,000 core cycles between the start and the first poll; default 0.1) and **Direction** (pid 6: below 0.5, DDR2 → Block 3; 0.5 and up, Block 3 → DDR2).
- Memory claims: report area 0xe4860..0xe4880; buffer 0xe5000..0xe5400; DDR2 window 0x324800..0x326800 in the port's `ddr2` region. It does not use `ddr2_try` 0x2f0000.., which heavy stock presets write (kit commit 2f34215). It also claims the IOP registers DMAC0 (0x180b) and EIEP0..DFEP0 (0x1820..0x182c). The port has two new regions, `iop_epdmac = [0x180b, 0x180d]` and `iop_epdma = [0x1820, 0x183d]`. They are deliberately narrow: EPCTL, AMI and the DDR2 controller stay outside every region, so `kit.py check` refuses any store there.
- Each block, after filling the window once: it checks that the channel is idle (DMAC0 has none of DEN, DMAS, CHS, EXTS) and that EP0IMSK is clear, otherwise it skips. It poisons the destination, programs the channel as above and times the start with EMUCLK. It waits 32 cycles, does the Work, then polls up to 4,000 times. It sets DMAC0 back to 0 and checks all 1,024 words. The report, for kit-probe → probe_decode.py:

| Word | | Word | |
|---|---|---|---|
| 0 | magic 0x646d6131 | 8 | cycles start → done seen |
| 1 | owner I0 | 9 | busy polls (0 = done during the work) |
| 2 | runs | 10 | work cycles |
| 3 | timeouts | 11 | DMAC0 at the last poll |
| 4 | wrong words | 12 | calls |
| 5, 6 | last wrong address, value (0x0bad0bad = never written) | 13 | skips |
| 7 | cycles to program + start | 14, 15 | LIRPTL after, ICEP0 after |

- ssim: `python3 kit.py check kit-dmatest` passes (it fills the window and skips the DMA because the suite starts DMAC0 random). `modules/kit-dmatest/tests` (10 tests) model the channel as the manual describes it. They check the write order and values (DFLSH; CPEP 0, IIEP 0xe5000, IMEP 1, ICEP 1024, EMEP 1, EIEP chunk; DEN or DEN|TRAN; then 0), the data in both directions, the detection of a DMA that moves nothing, the timeout path (channel left off, ICEP 0), both skip conditions, the owner takeover and the whole contract suite with the model: **verified (sim)**. Cost in ssim: 11.4k instructions a block reading DDR2 with Work 0.1, 14.5k writing, 56.5k at worst. On the chip, writing to DDR2 adds about 36k for the core's own DDR2 poison and check passes.
- Build: `python3 kit.py build HX_Stomp_v3.80.0_0x103966115.hxf kit-dmatest kit-probe --l6ia build/dmatest.l6ia`. It builds, and every checksum passes. It cannot go in one image with kit-memtest (the report area) or nam-a2-lite (Block 3 and `ddr2`).

## What the unit run should show, and how to read it

| Result | Meaning |
|---|---|
| runs rising, 0 timeouts, 0 wrong words | EP DMA works from a kernel: **the plan in KIT_NAM_A2_FULL.md for staging NAM windows is open** |
| polls 0 at Work 0.1 (2,000 cycles) | the DMA runs in the background and is done within 2k cycles; lower Work to 0 to measure its length (`cycles to done`) |
| timeouts, DMAC0 shows DMAS = 1, ICEP0 = 1024 | the channel never moved: a wrong address, the EP clock off (PMCTL1 EPOFF, bit 5; the kit does not touch it), or a DMA needing a setting the stock does not make |
| wrong words reading 0x0bad0bad, no timeouts | completion seen early, or the transfer went elsewhere (address mapping) |
| wrong words with other values | wrong EIEP mapping (for example, byte or 16-bit addressing) |
| skips rising | DMAC0 not idle (the stock uses the channel after all) or EP0IMSK set. Read words 11 and 17 |
| LIRPTL bit 3 set after | the EP0 completion latch: harmless while masked |

## Risks if a register is wrong

- **Writes stay inside 0x180b and 0x1820..0x182c** (`kit.py check` enforces it in ssim). If those addresses were wrong on this chip, the writes would land on other IOP registers. Per both sources, the neighbours are AMISTAT (0x180a, read only), DMAC1 (0x180c) and the DDR2 controller (0x1812..). The values written are small (0, 1, 0x20, 1,024, 0xe5000, 0x3248xx). An unintended write to a DDR2 controller register could hang external memory and crash the DSP, so the unit would need a power cycle. The addresses match in both ADI sources, so this is a **guess**-level risk.
- **A DMA to the wrong place.** If EIEP were not the core's address (say it were byte-addressed), reads would fetch other DDR2 words, which is harmless. Writes (Direction ≥ 0.5) would land somewhere else in DDR2 and could corrupt stock heaps. **So run the read direction first**, and try writing only after reads show 0 wrong words. IIEP is protected by the 19-bit field: any value lands in internal memory, and 0xe5000 is the claimed buffer.
- **A never-ending DMA.** The poll gives up after 4,000 polls and disables the channel. The block can then overrun the DSP budget, and audio drops out while it lasts. It does not hang.
- **The interrupt.** If PICR remaps P9I, LIRPTL bit 13 may not be EP0's mask, and a completion could vector into a stock handler. **Guess**: unlikely, since the stock never uses EP DMA. The latch is recorded (word 14), so a run shows whether it is set.
- **Core and DMA ordering on writes.** The core's poison writes to the DDR2 chunk come just before the DMA writes the same words. If the external port reordered them, poison would show as wrong words in the write direction only. That is a finding about ordering, not a broken DMA. **Open.**
