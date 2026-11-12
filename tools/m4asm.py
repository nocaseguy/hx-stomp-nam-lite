#!/usr/bin/env python3
"""m4asm.py - assemble a position-independent Thumb-2 .s file (clang) and print its .text as hex.

clang is HX_CLANG (a path, or a name on PATH), else Apple's Command Line Tools clang, else clang on PATH (Linux, WSL).
With HX_M4_CACHE set to a release's m4cache.json (tools/m4cache.py), modules come from it instead of clang: the web page has none.
"""
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile

APPLE_CLANG = '/Library/Developer/CommandLineTools/usr/bin/clang'
SHT_SYMTAB, SHT_RELA, SHT_REL = 2, 4, 9
CACHE = 'HX_M4_CACHE'
SOURCE_TYPES = ('.s', '.inc')
MARK = 'm4asm_adr_'                 # the labels mark_adr() puts before each adr
ADR = re.compile(r'^(\s*(?:[\w.$]+:\s*)?)(adr(?:\.[wn])?(?:eq|ne|cs|hs|cc|lo|mi|pl|vs|vc|hi|ls|ge|lt|gt|le|al)?)'
                 r'\s+(\w+)\s*,\s*([^@;]*?)\s*(?:[@;].*)?$', re.I)
TARGET = re.compile(r'^([A-Za-z_.$][\w.$]*)\s*(?:([+-])\s*(0x[0-9a-f]+|\d+))?$', re.I)
ZERO_ALIGN = re.compile(r'^\s*(?:[\w.$]+:\s*)?\.(?:b?align|p2align)\s+[^,@;]+,\s*(?:0x)?0+\s*(?:,.*)?(?:[@;].*)?$', re.I)


def find_clang():
    """The clang to assemble with, or a path that doesn't exist when there is none, which assemble_module() names."""
    if os.environ.get('HX_CLANG'):
        return shutil.which(os.environ['HX_CLANG']) or os.environ['HX_CLANG']
    # ahead of PATH on a Mac: /usr/bin/clang may be Xcode's, another version than the one the pinned MD5s were made with
    if os.path.exists(APPLE_CLANG):
        return APPLE_CLANG
    return shutil.which('clang') or APPLE_CLANG


CLANG = find_clang()


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


def mark_adr(text, src):
    """text with a label MARK<n> before each adr, and [(n, target label, addend, line)]: clang takes an adr's offset mod 4096
    without a word when its label is further (Apple clang 21), so assemble_module() checks each one's encoding."""
    out, adrs, macro = [], [], False
    for no, line in enumerate(text.split('\n'), 1):
        word = line.split('@')[0].strip().lower()
        macro = (macro or word.startswith('.macro')) and not word.startswith('.endm')
        m = ADR.match(line)
        if m:
            if macro:
                raise SystemExit(f'm4asm: {src}:{no}: an adr inside a .macro, which m4asm cannot check: move it out')
            t = TARGET.match(m.group(4))
            if not t:
                raise SystemExit(f'm4asm: {src}:{no}: m4asm checks an adr to a label, or a label + a number: {m.group(4)!r}')
            addend = int(t.group(3), 0) * (-1 if t.group(2) == '-' else 1) if t.group(2) else 0
            out.append(f'{m.group(1)}{MARK}{len(adrs)}: {line[len(m.group(1)):]}')
            adrs.append((len(adrs), t.group(1), addend, no))
        else:
            out.append(line)
    return '\n'.join(out), adrs


def check_zero_align(text, src):
    """Refuses a byte alignment filled with 0: clang 18 (Ubuntu) pads it with nops in .text, Apple clang 21 with zeros, so the
    same build would get two MD5s."""
    for no, line in enumerate(text.split('\n'), 1):
        if ZERO_ALIGN.match(line):
            raise SystemExit(f'm4asm: {src}:{no}: an alignment filled with 0, which clangs pad differently: use .balignl N, 0 '
                             'where the padding is whole words, else .org label + N, 0')


def adr_target(code, at):
    """Where the adr at offset at of code points, or None when it is no adr."""
    hw, = struct.unpack_from('<H', code, at)
    base = (at + 4) & ~3
    if hw & 0xf800 == 0xa000:
        return base + ((hw & 0xff) << 2)
    if at + 4 <= len(code) and hw & 0xfbff in (0xf20f, 0xf2af):
        hw2, = struct.unpack_from('<H', code, at + 2)
        imm = (hw >> 10 & 1) << 11 | (hw2 >> 12 & 7) << 8 | hw2 & 0xff
        return base + (imm if hw & 0xfbff == 0xf20f else -imm)
    return None


def check_adr(code, symbols, adrs, src):
    for n, label, addend, no in adrs:
        at, want = symbols[f'{MARK}{n}'], symbols.get(label)
        if want is None:
            continue                                # an .equ or another section: clang refuses or relocates those itself
        got = adr_target(code, at)
        if got is None:
            raise SystemExit(f'm4asm: {src}:{no}: no adr assembled at its line')
        if got != want + addend:
            raise SystemExit(f'm4asm: {src}:{no}: the adr to {label} is {want + addend - (at + 4 & ~3):#x} bytes from it, out of an '
                             f"adr's reach (4095), and clang assembled it to {got:#x} instead of {want + addend:#x}: adr to a near "
                             'label and add the rest')


def assemble_module(src, include=()):
    """(.text, {symbol: offset}) of src; refuses relocations, data outside .text, which nothing would place, and an adr whose
    label is out of its reach."""
    if os.environ.get(CACHE):
        return cached(os.environ[CACHE], src, include)
    if not os.path.exists(CLANG):
        raise SystemExit(f'm4asm: no clang at {CLANG}: install it (macOS: xcode-select --install; Ubuntu: apt install clang), '
                         'or set HX_CLANG to one')
    with tempfile.TemporaryDirectory() as d:
        text = open(src).read()
        check_zero_align(text, src)
        marked, adrs = mark_adr(text, src)
        with open(f'{d}/{os.path.basename(src)}', 'w') as f:
            f.write(marked)
        obj = f'{d}/o.o'
        subprocess.run([CLANG, '-target', 'thumbv7em-none-eabi', '-mcpu=cortex-m4', '-mfpu=fpv4-sp-d16', '-mfloat-abi=hard',
                        *(f'-I{i}' for i in (*include, os.path.dirname(os.path.abspath(src)))), '-c', f.name, '-o', obj],
                       check=True)
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
    code = e[s[4]:s[4] + s[5]]
    check_adr(code, symbols, adrs, src)
    return code, {k: v for k, v in symbols.items() if not k.startswith(MARK)}


def assemble(src, include=()):
    return assemble_module(src, include)[0]


if __name__ == '__main__':
    code = assemble(sys.argv[1])
    print(len(code), 'bytes')
    print(code.hex())
