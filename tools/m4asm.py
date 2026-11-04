#!/usr/bin/env python3
"""m4asm.py - assemble a position-independent Thumb-2 .s file (Apple's Command Line Tools clang) and print its .text as hex, to paste into patch_menu.py."""
import struct
import subprocess
import sys
import tempfile

CLANG = '/Library/Developer/CommandLineTools/usr/bin/clang'


def assemble(src):
    with tempfile.TemporaryDirectory() as d:
        obj = f'{d}/o.o'
        subprocess.run([CLANG, '-target', 'thumbv7em-none-eabi', '-mcpu=cortex-m4', '-mfpu=fpv4-sp-d16', '-mfloat-abi=hard',
                        '-c', src, '-o', obj], check=True)
        e = open(obj, 'rb').read()
    shoff, = struct.unpack_from('<I', e, 0x20)
    shentsize, shnum, shstrndx = struct.unpack_from('<3H', e, 0x2e)
    secs = [struct.unpack_from('<10I', e, shoff + i * shentsize) for i in range(shnum)]
    names = e[secs[shstrndx][4]:]
    for s in secs:
        if names[s[0]:names.index(b'\0', s[0])] == b'.text':
            return e[s[4]:s[4] + s[5]]
    raise SystemExit('no .text')


if __name__ == '__main__':
    code = assemble(sys.argv[1])
    print(len(code), 'bytes')
    print(code.hex())
