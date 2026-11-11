#!/usr/bin/env python3
"""m4asm.py - assemble a position-independent Thumb-2 .s file (Apple's Command Line Tools clang) and print its .text as hex.

With HX_M4_CACHE set to a release's m4cache.json (tools/m4cache.py), modules come from it instead of clang: the web page has none.
"""
import hashlib
import json
import os
import struct
import subprocess
import sys
import tempfile

CLANG = '/Library/Developer/CommandLineTools/usr/bin/clang'
SHT_SYMTAB, SHT_RELA, SHT_REL = 2, 4, 9
CACHE = 'HX_M4_CACHE'
SOURCE_TYPES = ('.s', '.inc')


def key(src, include=()):
    """What a module's code depends on: its source and every source in its include directories, by name, not by path."""
    h = hashlib.sha256()

    def add(name, path):
        data = open(path, 'rb').read()
        h.update(f'{name}\0{len(data)}\0'.encode() + data)

    add(os.path.basename(src), src)
    for i, d in enumerate(include):
        for name in sorted(n for n in os.listdir(d) if n.endswith(SOURCE_TYPES)):
            add(f'{i}/{name}', os.path.join(d, name))
    return h.hexdigest()


def cached(path, src, include):
    with open(path) as f:
        hit = json.load(f)['modules'].get(key(src, include))
    if hit is None:
        raise SystemExit(f'm4asm: {path} has no code for {os.path.basename(src)} with these features: it is another '
                         "release's, or these sources changed since it was made")
    return bytes.fromhex(hit['code']), hit['symbols']


def assemble_module(src, include=()):
    """(.text, {symbol: offset}) of src; refuses relocations and data outside .text, which nothing would place."""
    if os.environ.get(CACHE):
        return cached(os.environ[CACHE], src, include)
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
