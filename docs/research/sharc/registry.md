# SHARC tools, the primitive registry and control functions

The SHARC toolchain, the primitive registry, wrapping a primitive with a kernel of our own, and how control functions are called. Status tags as in [conventions.md](../conventions.md).

## Tools and kernels

- `tools/sharc/sasm.py`: assembler. `tools/sharc/ssim.py`: simulator (the `MANT` ALU op `0xAD` is not modelled). There is no disassembler in the repo. Labels are case-insensitive (`fp_cur` clashes with `FP_CUR`). `IF EQ DM(I5,1) = I4` is illegal: copy to a data register first.
- `tools/sharc/nam_multi.py` generates the NAM A2 Lite kernel (checked in the simulator against `src/sharc/nam_a2.asm`).
- **Primitive registry**: in Entry 2's data at DM `0x200000`, 2256 words, 8-word entries `[id, init_fn, 0, 0, ctrl_fn, process_addr, dm_words, pm_words]`. A primitive's process code address is word 5.
- **Registry-wrap technique [verified on unit for the transport]**: `tools/patch_amp.py patch --wrap-prim ID:ADDR` repoints a registry entry's process address at a custom kernel, which `CALL`s the stock address first (`ORIG`) and then does its own work. The patch asserts that the stock address equals `ADDR`, and adds a new tag-4 LDR block. No graph surgery is needed.
- Custom kernels: save and restore what they use (MODE1, R0..R7, I4..I6, L4..L6); clear `PEYEN|BDCST9` while running.
- A kernel is installed as the entry of an otherwise unused primitive; `patch_amp.py patch --asm file.asm` places code at the addresses the `.section` lines give.

## Control functions [verified offline]

- **[verified on unit]** A primitive's control function is called as (pid R4, pointer to the value R8, the core's state R12). R8 is one slot shared by all pids, followed by the writers {pid, 1, core}; R12's first words are the core's DM block (start, end, start), then its PM block. The value is not on the stack (`DM(1, I6)`) or in the core's state.
- A registry entry's `init_fn`/`ctrl_fn` addresses such as `0x6100bd` are VISA (16/32/48-bit) code in DDR2: short-word address `0x600000 + 2 * (word - 0x300000)`, from Entry 2's tag-10 boot blocks at `0x300000`. In each 32-bit word the low half is the first parcel: in that order, the 48-bit `MODIFY(I7,-2)` (`1607fffffffe`) occurs 229 times. `ssim.py` does not run VISA, and its 16/32-bit encodings are not in the repo.
- The parcels `70be`/`70fe` (the first parcels of `R0 = R8` / `R0 = R12`) open the generic store `0x611ddd`, and `4dfe 0e..` (`I12 = DM(M7, I6)`) appears early in `0x6100bd`: consistent with the C calling convention (arguments in R4, R8, R12).
- In the Deluxe Comp, no member primitive uses the generic store: `0x239d` has none, and `0x102`, `0x271a`, `0x89`, `0x80` each have their own.

How the ABI was found, image by image: [features/gr-meter-log.md](../features/gr-meter-log.md) (Knobs-to-meter to Value-at-R8).
