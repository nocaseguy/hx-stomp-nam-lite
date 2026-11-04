"""m4emu - run M4 module code in unicorn (Cortex-M4 Thumb) against stubbed firmware functions, for tests."""
import os
import struct
import tempfile

import pytest

unicorn = pytest.importorskip('unicorn', reason='no unicorn (pip install unicorn)')
from unicorn import arm_const as A  # noqa: E402

import m4asm  # noqa: E402
import patch_menu as pm  # noqa: E402

RAM = (0x28000000, 0x01000000)      # the HX Stomp's SDRAM: the app's data and code, and here the module, stack and fakes
ROM = (0x10000000, 0x00010000)      # the boot ROM's functions
STACK_TOP = 0x28f00000
RETURN = 0x28ff0000                 # where the called function returns to; emulation stops there
CLANG = pytest.mark.skipif(not os.path.exists(m4asm.CLANG), reason='no Command Line Tools clang')


def assemble(path, mods, ids):
    """(code, symbols) of a module, with the customos.inc patch_menu.py would generate."""
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, 'customos.inc'), 'w') as f:
            f.write(pm.customos_inc(mods, ids))
        return m4asm.assemble_module(os.path.join(pm.ROOT, path), include=(d, os.path.dirname(os.path.join(pm.ROOT, path))))


class M4:
    """Memory, stubs (a firmware function's address -> a Python function of the emulator) and calls."""

    def __init__(self, code, at):
        self.uc = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_THUMB | unicorn.UC_MODE_MCLASS)
        for base, size in (RAM, ROM):
            self.uc.mem_map(base, size)
        self.at = at
        self.uc.mem_write(at, code)
        self.log = []               # (stub address, (r0, r1, r2, r3)) of every stub call, in order

    def stub(self, fn, handler=None):
        """At fn (bit 0 ignored): log the call, handler(m4), then return to the caller."""
        fn &= ~1
        self.uc.mem_write(fn, struct.pack('<H', 0x4770))     # bx lr

        def hit(uc, addr, size, data):
            self.log.append((fn, tuple(self.reg(f'r{i}') for i in range(4))))
            if handler:
                handler(self)
        self.uc.hook_add(unicorn.UC_HOOK_CODE, hit, begin=fn, end=fn)

    def calls(self, fn):
        """The (r0, r1, r2, r3) of each call of the stub at fn, in order."""
        return [args for at, args in self.log if at == fn & ~1]

    def reg(self, n, value=None):
        r = getattr(A, f'UC_ARM_REG_{n.upper()}')
        if value is None:
            return self.uc.reg_read(r)
        self.uc.reg_write(r, value & 0xffffffff)

    def u32(self, va, value=None):
        if value is None:
            return struct.unpack('<I', self.uc.mem_read(va, 4))[0]
        self.uc.mem_write(va, struct.pack('<I', value & 0xffffffff))

    def u8(self, va, value):
        self.uc.mem_write(va, bytes([value]))

    def read(self, va, n):
        return bytes(self.uc.mem_read(va, n))

    def write(self, va, data):
        self.uc.mem_write(va, bytes(data))

    def stack_args(self, n):
        """The first n stack arguments of a stubbed call."""
        sp = self.reg('sp')
        return [self.u32(sp + 4 * i) for i in range(n)]

    def call(self, fn, *args):
        """fn(args) (at most 4, in r0-r3) -> r0; checks SP and r4-r11 come back as they went in."""
        for i, a in enumerate(args):
            self.reg(f'r{i}', a)
        kept = {f'r{i}': 0x1000 + i for i in range(4, 12)}
        for r, v in kept.items():
            self.reg(r, v)
        self.reg('sp', STACK_TOP)
        self.reg('lr', RETURN | 1)
        self.uc.emu_start(fn | 1, RETURN, count=2_000_000)
        assert self.reg('sp') == STACK_TOP, 'the stack is not balanced'
        assert {r: self.reg(r) for r in kept} == kept, 'a callee-saved register changed'
        return self.reg('r0')
