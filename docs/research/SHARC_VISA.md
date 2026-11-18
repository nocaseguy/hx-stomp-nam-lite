# VISA: the SHARC's 16/32/48-bit code in Entry 2

How Entry 2's VISA code is laid out and encoded, and what `tools/sharc/visa_dis.py` decodes. The forms were first worked out from the stock code and the 48-bit ISA tables in `tools/sharc/sasm.py`, then checked against ADI's *SHARC Processor Programming Reference* (ADSP-2136x/2137x/214xx, rev 2.4: chapter 10 "Instruction Set Opcodes", and "Short Compute Opcodes" in chapter 12), which agrees with every one.

## Running the disassembler

- `python3 tools/sharc/visa_dis.py START [END | +N]` lists VISA code at short-word addresses; `--pm` lists 48-bit ISA code in PM. The firmware is `--hxf` or `$HX_STOMP_HXF`.
- Branch and loop targets print as absolute addresses, as sasm takes them (`JUMP (PC, 0x609250)` is a jump to `0x609250`).
- A parcel with no known form prints as `?? xxxx`, one parcel, never a guess. In the stock file 72 of 76,408 VISA instructions do, all `00c1` (see [Open](#open)).

## Where the code is (verified offline)

Entry 2 is an LDR boot stream read raw (`l6ia.parse(l6)[2]`, not swapped), blocks `{tag, count, addr}` from word 384.

- Tag 5: 48-bit ISA instructions in PM at `0x8c100..0x8ee95`. Four tag-2 blocks (48-bit zero fills: 4, 21, 3 and 7 words at `0x8c112`, `0x8c2ac`, `0x8d67d`, `0x8ea85`) sit between its tag-5 blocks; they are NOPs in the code, and `visa_dis.py` lists them, so the PM listing has no holes. Two calls from VISA go just below it (`0x8c0c3`, `0x8c0ec`), to code Entry 2 does not load.
- Tag 3: VISA in internal memory, short-word addresses `0x13ac4a..0x183138`. The count is in parcels; each 32-bit word holds two parcels, **the high half first**, counted from the block's start (an odd count ends on a padding half). `patch_amp.expand_sharc_blob0_buffer`'s words `w[37192..37193]` read this way as `R0 = 0x77aac; RFRAME`.
- Tag 10: VISA in DDR2. Word `0x300000 + k` holds the parcels at short-word `0x600000 + 2k` (low half) and `0x600000 + 2k + 1` (high half), up to `0x61a0de`.
- Tag 1 blocks between those blocks are zeros in the code, even in the middle of an instruction: `9980 bf80` at `0x13b35d` takes its third parcel `0000` from a zero fill (`DM(I4,M6) = 0xbf800000`), and two 48-bit NOPs follow.

## Instruction length (verified offline)

The first parcel, and for some types the low 7 bits of the second, give the length:

| first parcel | length |
|---|---|
| `0x00xx`, `0x19xx` (NOP, IDLE, RFRAME) | 16 bits if bit 0 is set (`0001`, `1901`), else 48 |
| `0x01xx` (compute), `0x0fxx` (ureg = immediate) | 32 bits if bit 7 is set, else 48 |
| `0x0axx`, `0x0bxx` (RTS, RTI) | 16 bits if bit 7 is set (type 11c), else 48 |
| `0x04`, `0x08`, `0x09`, `0x20`..`0x7f` (types 1, 3, 4, 5, 7, 9) | 32 bits if the second parcel's low 7 bits are `0x3f`, else 48 |
| `0x9xxx` | by bits 4..0: `00000` 48, `00100` 32, `01000` 32, `1xxxx` 16 |
| `0xcxxx` | 16 bits |
| `0x02`, `0x06`, `0x07`, `0x0a`..`0x0e`, `0x10`..`0x14`, `0x16`..`0x18`, `0x80`..`0x8f`, `0xa0`..`0xbf` | 48 bits |

How it was checked: 2,308 call sites are `CJUMP` (3 parcels), `DM(I7,M7) = R2` (1), `DM(I7,M7) = <return - 1>` (3), and the stored return address always lies 6 parcels after the CJUMP; that fixed the first rules. A linear sweep of every VISA run with the full rules keeps all 2,308 call sites whole, starts an instruction at each of the 468 CJUMP targets in VISA, and lands on 5,310 of 5,310 PC-relative branch and DO targets inside VISA (`tests/test_visa_dis.py`). The `0x3f` marker never occurs in the ISA code: no tag-5 instruction has `0x3f` in compute bits 22..16. The Programming Reference: "For ISA/VISA instructions bits 47–40 are used to decode the instruction set types and for VISA instructions bits 36–34 are optionally decoded"; its 32-bit types 1b, 3b, 4b, 5b, 7b and 9b end in `0111111` at bits 22..16.

## The forms (verified offline)

- **48-bit**: the ISA encoding unchanged (`MODIFY(I7,-2)` = `1607 ffff fffe`, `R2 = DM(0xe149a)` = `1002 000e 149a`). The ISA decoder re-encodes all 11,633 tag-5 instructions to the same words with sasm; the other two are data after an RTI. The 35 tag-2 words decode as `NOP`.
- **32-bit, the ISA form without a compute** (types 1, 3, 4, 5, 7, 9): the ISA instruction's top 32 bits, with `0x3f` in place of compute bits 22..16 (`JUMP (M14,I12) (DB)` = `083f 343f`, `I12 = DM(M7,I6)` = `4dfe 0e3f`).
- **32-bit compute** (`0x01`, bit 7 set): no condition; the 23-bit compute field is `(p1 & 0x7f) << 16 | p2` (`0193 04c4` = `F4 = F12 * F4`, `0180 b0da` = `COMPU(R13, R10)`).
- **32-bit ureg = data16** (`0x0f`, bit 7 set): ureg in bits 6..0, the immediate sign-extended (`0f80 ff80` = `R0 = -0x80`). The SRU masks at `0x6092ce..` confirm the sign extension.
- **`0x9xxx`**, the ISA's `DM|PM(Ia,Mb) = data32` space, whose bits 4..0 the ISA leaves zero:
  - `00000`: that 48-bit form.
  - `00100`, 32-bit: `DM|PM(Ia,Mb) = data16`, I in bits 11..9, M in 8..6, PM in bit 5 (`9fc4 0005` = `DM(I7,M7) = 5`).
  - `01000`, 32-bit (type 15b): `ureg <-> DM|PM(data7, Ia)`; I in bits 11..9, store in bit 8, PM in bit 5; the second parcel holds ureg in bits 13..7 and a signed 7-bit offset in 6..0 (`9d08 01e7` = `DM(-25,I6) = R3`, `9428 0110` = `R2 = PM(16,I10)`). Its (LW) bit is bit 7 or 6 of the first parcel (the manual's text does not place it); the stock code never sets either, and `visa_dis.py` prints such a parcel raw.
  - `1xxxx`, 16-bit: `Rn <-> DM(Ia,Mb)`; I in bits 11..9, M in 8..6, store in bit 5, Rn in 3..0 (`9ff2` = `DM(I7,M7) = R2`, `9b52` = `R2 = DM(I5,M5)`).
- **RTS, RTI** (type 11c), 16-bit: `0000 101x 1 J COND LR` (`0abe` = `RTS`, `0abf` = `RTS (LR)`). The compiled C returns with `JUMP (M14,I12)`; RTS occurs 5 times.
- **16-bit short compute** (type 2c) `1100 op Rn Rx`, one source register the destination. The ops were first named from how the code uses them (the evidence column), then found in the manual's table; op 4, `Rn = NOT Rx`, does not occur in the stock code:

  | op | operation | evidence |
  |---|---|---|
  | 0 | `Rn = Rn + Rx` | |
  | 1 | `Rn = Rn - Rx` | usually Rn = Rx (clearing); `R11 = I4; R15 = B4; c1bf` |
  | 2 | `Rn = PASS Rx` | most common; tests before a conditional jump |
  | 3 | `COMP(Rn, Rx)` | followed by a conditional jump 412 times of 535; Rn never Rx |
  | 4 | `Rn = NOT Rx` | not used |
  | 5 | `Rn = Rx + 1` | load, `c522`, store back |
  | 6 | `Rn = Rx - 1` | clamps an index: `COMP(R0,R2)`, `IF GT` skip, `c620`; `c6ee; IF EQ` before `LCNTR = R14` |
  | 7 | `Rn = Rn * Rx (SSI)` | products of integers, then FLOAT |
  | 8, 9, f | `Fn = Fn + Fx`, `Fn = Fn - Fx`, `Fn = Fn * Fx` | float code |
  | a | `Fn = FLOAT Rx` | `R7 = TRUNC F0 ... ca77; F3 = F0 - F7` |
  | b | `COMP(Fn, Fx)` | followed by `IF LT` / `IF GE` in float code |
  | c, d | `Rn = Rn AND Rx`, `Rn = Rn OR Rx` | the SRU field writes at `0x6092d0..` |
  | e | `Rn = Rn XOR Rx` | the xorshift at `0x13bfd7` (shifts 13, -17, 5) |
- PC-relative offsets in VISA count parcels (short words).

## The compiled C calling convention (verified offline)

- A call: `CJUMP f (DB)`, `DM(I7,M7) = R2` (the caller's I6), `DM(I7,M7) = <next - 1>`; the return is `JUMP (M14,I12) (DB)` with M14 = 1. Arguments are R4, R8, R12, then the stack (`DM(1,I6)`, `DM(2,I6)`, ... in the callee).
- A function opens with `MODIFY(I7,-n)` and saves what it uses at `DM(-k,I6)`: R3, R5, R6, R7, R9, R10, R11, R13, R14, R15 and I-registers through R2. It ends with `I12 = DM(M7,I6)`, restores, `JUMP (M14,I12) (DB)`, `RFRAME` and one delay-slot instruction (often a 16-bit NOP).

## Open

- `00c1` (16-bit, 72 places) sits before each entry of the jump tables after some functions' ends. It has the shape of type 22c (16-bit IDLE/EMUIDLE, `000 00000 IDL EMU ... 1`) with both IDL and EMU set, which the manual does not define; it is printed raw. **Guess**: an assembler's filler.
