#!/usr/bin/env python3
"""m4asm.py - assemble a position-independent Thumb-2 .s file (Apple's Command Line Tools clang) and print its .text as hex."""
import struct
import subprocess
import sys
import tempfile

CLANG = '/Library/Developer/CommandLineTools/usr/bin/clang'
SHT_SYMTAB, SHT_RELA, SHT_REL = 2, 4, 9


def assemble_module(src, include=()):
    """(.text, {symbol: offset}) of src; refuses relocations and data outside .text, which nothing would place."""
    with tempfile.TemporaryDirectory() as d:
        obj = f'{d}/o.o'
        subprocess.run([CLANG, '-target', 'thumbv7em-none-eabi', '-mcpu=cortex-m4', '-mfpu=fpv4-sp-d16', '-mfloat-abi=hard',
                        *(f'-I{i}' for i in include), '-c', src, '-o', obj], check=True)
        e = open(obj, 'rb').read()
    shoff, = struct.unpack_from('<I', e, 0x20)
    shentsize, shnum, shstrndx = struct.unpack_from('<3H', e, 0x2e)
    secs = [struct.unpack_from('<10I', e, shoff + i * shentsize) for i in range(shnum)]

    def cstr(table, at):
        return e[table + at:e.index(b'\0', table + at)].decode()

    names = [cstr(secs[shstrndx][4], s[0]) for s in secs]
    if '.text' not in names:
        raise SystemExit(f'm4asm: {src} has no .text')
    text = names.index('.text')
    for n, s in zip(names, secs):
        if s[1] in (SHT_REL, SHT_RELA) and s[7] == text and s[5]:
            raise SystemExit(f'm4asm: {src} needs relocations ({n}): a bl or a literal to a .global symbol, or to another section')
        if n in ('.data', '.bss', '.rodata') and s[5]:
            raise SystemExit(f'm4asm: {src} has {n}: keep everything in .text')
    symbols = {}
    for s in secs:
        if s[1] != SHT_SYMTAB:
            continue
        strtab = secs[s[6]][4]
        for at in range(s[4], s[4] + s[5], 16):
            st_name, value, _, _, _, shndx = struct.unpack_from('<3I2BH', e, at)
            sym = cstr(strtab, st_name)
            if shndx == text and sym and not sym.startswith('$'):
                symbols[sym] = value & ~1
    s = secs[text]
    return e[s[4]:s[4] + s[5]], symbols


def assemble(src, include=()):
    return assemble_module(src, include)[0]


if __name__ == '__main__':
    code = assemble(sys.argv[1])
    print(len(code), 'bytes')
    print(code.hex())
