# M4 code: reading and writing it

Disassembling Entry 0 and assembling new Thumb-2 code for it. Status tags as in [conventions.md](../conventions.md).

- Thumb-2 disassembly: Apple `llvm-objdump` (`llvm-objdump -d --triple=thumbv7em`) works. A disassembly of segment 6 is the main map; rebuild it with `tools/l6ia.py`/`patch_amp.py` helpers to extract Entry 0, then disassemble.
- **Assembling M4 code: Apple `clang -target thumbv7em-none-eabi` works** as a Thumb-2/VFP assembler. `tools/m4asm.py file.s` prints the `.text` hex. Use `mul`, not `muls`, in the clang syntax where it complains.
- **An `adr` out of reach assembles wrong, silently** [verified offline, 2026-11-11, Apple clang 21.0.0 with m4asm's flags]: when its label is 4096 bytes or more away, clang takes the offset mod 4096 (labels 0x1008, 0x2008 and 0x20008 away all give `adr.w r1, #4`), exits 0 and leaves no relocation. `tools/m4asm.py` marks each `adr` in a module with a label, decodes what clang assembled there and fails the build when it does not point at the label the source names (`tests/test_m4asm.py`); it refuses an `adr` inside a `.macro`, which it cannot mark. For a far label, `adr` to a near one and `add.w` the rest.
- The firmware uses the hardware FPU elsewhere, but new M4 hooks avoid VFP because the FPU context of the thread they run in is unknown.
- Thumb function pointers are called with the address OR 1.

How a feature's code is built in and hooked: [features/engine.md](../features/engine.md).
