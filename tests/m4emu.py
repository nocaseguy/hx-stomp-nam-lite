"""m4emu - run M4 module code in unicorn (Cortex-M4 Thumb) against stubbed firmware functions, for tests.

Importing it skips the importing test file when unicorn is missing; take the m4emu fixture (tests/conftest.py) instead, so a file's
other tests still run. Only code a test placed runs: the module, load()ed code and stubs. Anything else fails the call, so a call to
a function nobody stubbed fails instead of sliding through zeroed memory into the next stub."""
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
STEPS = 2_000_000
BX_LR = struct.pack('<H', 0x4770)
CLANG = pytest.mark.skipif(not os.path.exists(m4asm.CLANG), reason='no Command Line Tools clang')


def assemble(path, mods, ids):
    """(code, symbols) of a module, with the customos.inc patch_menu.py would generate; skips the test without clang."""
    if not os.path.exists(m4asm.CLANG):
        pytest.skip('no Command Line Tools clang')
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, 'customos.inc'), 'w') as f:
            f.write(pm.customos_inc(mods, ids))
        return m4asm.assemble_module(os.path.join(pm.ROOT, path), include=(d, os.path.dirname(os.path.join(pm.ROOT, path))))


class M4:
    """Memory, code, stubs (a firmware function's address -> a Python function of the emulator) and calls."""

    def __init__(self, code, at, log_regs=('r0', 'r1', 'r2', 'r3')):
        self.uc = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_THUMB | unicorn.UC_MODE_MCLASS)
        for base, size in (RAM, ROM):
            self.uc.mem_map(base, size)
        self.at, self.log_regs = at, log_regs
        self.code = [(RETURN, RETURN + 2)]
        self.log = []               # (stub address, the log_regs' values) of every stub call, in order; clear it with log.clear()
        self.stray = None
        self.uc.hook_add(unicorn.UC_HOOK_CODE, self._fetch)
        self.load(at, code)

    def _fetch(self, uc, addr, size, data):
        if self.stray is None and not any(a <= addr < b for a, b in self.code):
            self.stray = addr
            uc.emu_stop()

    def map(self, base, size):
        """More memory, e.g. the M4's internal SRAM at 0x20000000 (base and size in 4 KB pages)."""
        self.uc.mem_map(base, size)

    def load(self, va, code):
        """Code that may run, at va."""
        self.uc.mem_write(va, bytes(code))
        self.code.append((va, va + len(code)))

    def stub(self, fn, handler=None, code=BX_LR):
        """At fn (bit 0 ignored): log the call, handler(m4), then run code (by default bx lr: return to the caller)."""
        fn &= ~1
        self.load(fn, code)

        def hit(uc, addr, size, data):
            self.log.append((fn, tuple(self.reg(r) for r in self.log_regs)))
            if handler:
                handler(self)
        self.uc.hook_add(unicorn.UC_HOOK_CODE, hit, begin=fn, end=fn)

    def calls(self, fn):
        """The log_regs' values at each call of the stub at fn, in order."""
        return [regs for at, regs in self.log if at == fn & ~1]

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
        """fn(args) (at most 4, in r0-r3) -> r0; checks it returned, and that SP and r4-r11 come back as they went in."""
        assert len(args) <= 4, 'call() passes at most 4 arguments, in r0-r3'
        for i, a in enumerate(args):
            self.reg(f'r{i}', a)
        kept = {f'r{i}': 0x1000 + i for i in range(4, 12)}
        for r, v in kept.items():
            self.reg(r, v)
        self.reg('sp', STACK_TOP)
        self.reg('lr', RETURN | 1)
        self.stray = None
        self.uc.emu_start(fn | 1, RETURN, count=STEPS)
        assert self.stray is None, f'ran {self.stray:#x}, outside the code and the stubs: a call of a function with no stub?'
        assert self.reg('pc') == RETURN, f'still running at {self.reg("pc"):#x} after {STEPS} instructions: a loop?'
        assert self.reg('sp') == STACK_TOP, 'the stack is not balanced'
        assert {r: self.reg(r) for r in kept} == kept, 'a callee-saved register changed'
        return self.reg('r0')
