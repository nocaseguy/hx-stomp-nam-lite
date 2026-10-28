#!/usr/bin/env python3
"""ssim - a small simulator for the 48-bit SHARC code we write ourselves.

It executes the encoded instructions sasm produces, so what is tested is what
ships. It covers the instruction forms and compute operations our own sources
use and stops with SimError on anything else, rather than guessing.

Model: 32-bit IEEE floats (the code must run with RND32 set, round to
nearest), circular buffers on post-modify and MODIFY when L != 0, hardware
loops, the PC stack, AZ/AN and the bit-test flag. SIMD (MODE1 PEYEN): computes
run on both processing elements, a data register moved through an index
register pairs with its S register and the next memory word, a store of any
other register also overwrites the next memory word (with junk), and loads through
I1 / I9 are broadcast when BDCST1 / BDCST9 is set; every other use of a data
register in SIMD stops the simulation. Flags are those of PEx. The core
timer counts down one per instruction while MODE2 TIMEN is set (no reload, no
interrupt), and every change of FLAGS is logged in `flag_log` as (cycles,
value). Not modelled: delayed branches, interrupts, 40-bit floats, saturation,
pipeline effects and the restrictions on short loops. `cycles` counts
instructions executed, which is the cycle count of straight-line single-cycle
code.
"""
import math
import os
import struct

M32 = 0xFFFFFFFF
U_PC, U_PCSTK, U_CURLCNTR, U_LCNTR, U_TCOUNT = 0x63, 0x64, 0x67, 0x68, 0x6F
U_USTAT1, U_USTAT2, U_MODE1, U_MODE2, U_FLAGS, U_ASTATX, U_ASTATY = 0x70, 0x71, 0x72, 0x74, 0x75, 0x76, 0x77
U_USTAT3, U_USTAT4 = 0x7E, 0x7F
PEYEN, BDCST9, BDCST1 = 1 << 21, 1 << 22, 1 << 23
CBUFEN = 1 << 24
SRRFL, SRRFH = 1 << 7, 1 << 10     # MODE1: the secondary R0-R7 / R8-R15 (and S0-S7 / S8-S15)
TRUNC = 1 << 15
ASTAT_MASK = 0x1 | 0x2 | 0x4 | 0x8 | (1 << 11) | (1 << 12) | (1 << 18)
JUNK = 0x7FC0DEAD                # what a SIMD store of an unpaired register leaves in the next word
TIMEN = 1 << 5


class SimError(Exception):
    pass


# RECIPS as the ADSP-21469 on the unit gives it (measured with a probe kernel,
# 2026-10-25; recips_table.json): a seed from a 128-entry table indexed by the top 7 mantissa bits,
# exponent 253 - e, sign kept; zero or subnormal -> signed infinity, infinity ->
# signed zero, NaN -> 0xffffffff, underflow -> signed zero. ssim by default takes the exact 1/x instead;
# SSIM_RECIPS_HW=1 selects the unit's.
RECIPS_HW = os.environ.get("SSIM_RECIPS_HW") == "1"
_RECIPS_T = None


def recips_hw(b):
    global _RECIPS_T
    if _RECIPS_T is None:
        import json
        _RECIPS_T = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "recips_table.json")))
    s, e, m = b & 0x80000000, (b >> 23) & 0xFF, b & 0x7FFFFF
    if e == 255:
        return 0xFFFFFFFF if m else s
    if e == 0:
        return s | 0x7F800000
    re = 253 - e
    return s if re <= 0 else s | (re << 23) | (_RECIPS_T[m >> 16] << 15)


def ftz(b):
    b &= M32
    return (b & 0x80000000) if (b & 0x7F800000) == 0 else b


def f2b(x):
    try:
        return struct.unpack("<I", struct.pack("<f", x))[0]
    except OverflowError:
        return 0x7F800000 if x > 0 else 0xFF800000


def b2f(b):
    return struct.unpack("<f", struct.pack("<I", b & M32))[0]


def d2b(x):
    try:
        lo, hi = struct.unpack("<II", struct.pack("<d", x))
        return lo, hi
    except OverflowError:
        return (0, 0x7FF00000) if x > 0 else (0, 0xFFF00000)


def b2d(lo, hi):
    return struct.unpack("<d", struct.pack("<II", lo & M32, hi & M32))[0]


def exp2f(n):
    return b2f(((n + 127) & 0xFF) << 23) if -126 <= n <= 127 else 2.0 ** n


def clz32(v):
    v &= M32
    return 32 - v.bit_length()


def s32(v):
    v &= M32
    return v - (1 << 32) if v & 0x80000000 else v


def sx(v, bits):
    return v - (1 << bits) if v >> (bits - 1) & 1 else v


class Sim:
    def __init__(self, byte_mode=False, hle=None):
        self.byte_mode = byte_mode
        self.hle = hle or {}
        self.u = [0] * 128                  # universal registers by code
        self.dm = {}                        # 32-bit words by normal-word address
        self.pm = {}                        # 48-bit instructions by address
        self.pc = 0
        self.pcstk, self.loops, self.stsstk = [], [], []     # loops: [top, end, count]
        self.pending_branch = None          # (target, slots_left)
        self.az = self.an = self.ac = self.av = self.sv = self.sz = self.tf = False
        self.mrf = [0, 0, 0]
        self.mrb = [0, 0, 0]
        self.alt = [0] * 32                 # secondary R0-R15, then S0-S15
        self.srrf = 0                       # MODE1 SRRFL | SRRFH as last seen
        self._pey_eff = None                # SIMD as the current instruction sees it, when a BIT SET/CLR
        self._pey_next = None               # MODE1 just changed PEYEN (it takes one instruction)
        self.cycles = 0
        self.flag_log = []
        # The chip wraps circular buffers only with MODE1 CBUFEN set, and puts an
        # index back into the buffer by one length only: a step longer than the
        # buffer can leave it outside (heard on the unit as a tone at each long
        # ring's rate, nam_lite_kernel.asm). With strict_cbufen ssim does both;
        # off by default, since older tests call kernels without their callers'
        # MODE1 and some may step further.
        self.strict_cbufen = False

    # ---------------------------------------------------------- loading
    def load(self, sections):
        for s in sections:
            mem = self.pm if s.kind == "pm" else self.dm
            for i, w in enumerate(s.words):
                mem[s.addr + i] = w

    def rd(self, a):
        a &= M32
        if self.byte_mode:
            if a & 3 == 0:
                return self.dm.get(a >> 2, 0)
            return self.rd8(a) | (self.rd8(a + 1) << 8) | (self.rd8(a + 2) << 16) | (self.rd8(a + 3) << 24)
        return self.dm.get(a, 0)

    def wr(self, a, v):
        a, v = a & M32, v & M32
        if self.byte_mode:
            if a & 3 == 0:
                self.dm[a >> 2] = v
            else:
                self.wr8(a, v & 0xFF)
                self.wr8(a + 1, (v >> 8) & 0xFF)
                self.wr8(a + 2, (v >> 16) & 0xFF)
                self.wr8(a + 3, (v >> 24) & 0xFF)
        else:
            self.dm[a] = v

    def rd8(self, a):
        a &= M32
        w = self.dm.get(a >> 2 if self.byte_mode else a, 0)
        return (w >> ((a & 3) * 8)) & 0xFF

    def wr8(self, a, b):
        a, b = a & M32, b & 0xFF
        wa = a >> 2 if self.byte_mode else a
        sh = (a & 3) * 8
        w = self.dm.get(wa, 0)
        self.dm[wa] = (w & ~(0xFF << sh)) | (b << sh)

    # ---------------------------------------------------------- flags & registers
    def _pack_flags(self):
        return (int(self.az) | (int(self.av) << 1) | (int(self.an) << 2) | (int(self.ac) << 3)
                | (int(self.sv) << 11) | (int(self.sz) << 12) | (int(self.tf) << 18))

    def _unpack_flags(self, v):
        self.az = bool(v & 0x1)
        self.av = bool(v & 0x2)
        self.an = bool(v & 0x4)
        self.ac = bool(v & 0x8)
        self.sv = bool(v & (1 << 11))
        self.sz = bool(v & (1 << 12))
        self.tf = bool(v & (1 << 18))

    def get(self, code):
        if code == U_PC:
            return self.pc
        if code == U_CURLCNTR:
            return self.loops[-1][2] if self.loops else self.u[U_LCNTR]
        if code == U_ASTATX:
            return (self.u[U_ASTATX] & ~ASTAT_MASK) | self._pack_flags()
        return self.u[code]

    def set(self, code, v):
        v &= M32
        self.u[code] = v
        if 0x40 <= code < 0x50:             # loading Bn loads In
            self.u[code - 0x30] = v
        elif code == U_ASTATX:
            self._unpack_flags(v)

    def R(self, n):
        return self.u[n]

    def F(self, n):
        return b2f(ftz(self.u[n]))

    def D(self, n):
        b = n & ~1
        return b2d(self.u[b], self.u[b + 1])

    def setR(self, n, v):
        self.u[n] = v & M32
        self.az, self.an = self.u[n] == 0, bool(self.u[n] >> 31)

    def setF(self, n, x):
        b = ftz(f2b(x))
        self.u[n] = b
        x = b2f(b)
        self.az, self.an = x == 0.0, x < 0.0

    def setD(self, n, x):
        b = n & ~1
        lo, hi = d2b(x)
        self.u[b], self.u[b + 1] = lo, hi

    # ---------------------------------------------------------- address generators
    def _wrap(self, i, v):
        b, ln = self.u[0x40 + i], self.u[0x30 + i]
        if ln and self.strict_cbufen:       # as the chip: only with CBUFEN, and corrected once
            if self.u[U_MODE1] & CBUFEN:
                if v >= b + ln:
                    v -= ln
                elif v < b:
                    v += ln
            return v & M32
        if ln:
            if self.byte_mode and b >= 0x100000:
                ln *= 4
            if v >= b + ln:
                v = b + (v - b) % ln
            elif v < b:
                rem = (b - v) % ln
                v = b if rem == 0 else b + ln - rem
        return v & M32

    def post(self, i, step, scale=None):
        if scale is None:
            scale = 4 if self.byte_mode else 1
        a = self.u[0x10 + i]
        self.u[0x10 + i] = self._wrap(i, a + s32(step) * scale)
        return a

    def pre(self, i, step, scale=None):
        if scale is None:
            scale = 4 if self.byte_mode else 1
        if self.strict_cbufen:              # the chip wraps post-modify accesses only
            return (self.u[0x10 + i] + s32(step) * scale) & M32
        return self._wrap(i, self.u[0x10 + i] + s32(step) * scale)

    # ---------------------------------------------------------- SIMD
    @property
    def simd(self):
        if self._pey_eff is not None:
            return self._pey_eff
        return bool(self.u[U_MODE1] & PEYEN)

    @property
    def wstep(self):
        return 4 if self.byte_mode else 1

    def _scalar(self, *codes):
        pass

    def dget(self, r):
        """Value(s) of data register r for a store through an index register."""
        return (self.u[r], self.u[r ^ 0x50]) if self.simd else (self.u[r],)

    def dload(self, a, i):
        """Value(s) for a data register loaded from address a through index register i."""
        if not self.simd:
            return (self.rd(a),)
        if (i == 1 and self.u[U_MODE1] & BDCST1) or (i == 9 and self.u[U_MODE1] & BDCST9):
            v = self.rd(a)
            return (v, v)
        return (self.rd(a), self.rd(a + self.wstep))

    def dset(self, r, v):
        self.u[r] = v[0]
        if len(v) > 1:
            self.u[r ^ 0x50] = v[1]

    def dstore(self, a, v):
        ws = self.wstep
        for k, x in enumerate(v):
            self.wr(a + k * ws, x)

    def ustore(self, a, v):
        """Store a register that has no partner. In SIMD the processor writes the
        next word as well (seen on the unit: a zero); nothing may depend on it."""
        self.wr(a, v)
        if self.simd:
            self.wr(a + self.wstep, v if (self.byte_mode or v == 0) else JUNK)

    def _swap_pe(self):
        self.u[0:16], self.u[0x50:0x60] = self.u[0x50:0x60], self.u[0:16]
        self.mrf, self.mrb = self.mrb, self.mrf

    def compute(self, c):
        self.compute1(c)
        if c and self.simd:
            x_flags = self._pack_flags()
            self._unpack_flags(self.u[U_ASTATY])
            self._swap_pe()
            self.compute1(c)
            self.u[U_ASTATY] = (self.u[U_ASTATY] & ~ASTAT_MASK) | self._pack_flags()
            self._swap_pe()
            self._unpack_flags(x_flags)

    # ---------------------------------------------------------- conditions
    def _cond_flags(self, c, az, an, ac, av, sv, sz, tf):
        if c == 31:
            return True
        neg, base = c >= 16, c & 15
        if base == 0: v = az
        elif base in (1, 6): v = an
        elif base == 2: v = an or az
        elif base == 3: v = ac
        elif base == 4: v = av
        elif base == 7: v = sv
        elif base == 8: v = sz
        elif base == 13: v = tf
        elif base == 15: v = not (self.loops and self.loops[-1][2] > 1)
        else: raise SimError(f"condition {c} is not modelled")
        return v != neg

    def cond(self, c):
        return self._cond_flags(c, self.az, self.an, self.ac, self.av, self.sv, self.sz, self.tf)

    def cond_pey(self, c):
        y = self.u[U_ASTATY]
        return self._cond_flags(c, bool(y & 1), bool(y & 4), bool(y & 8), bool(y & 2),
                                bool(y & (1 << 11)), bool(y & (1 << 12)), bool(y & (1 << 18)))

    # ---------------------------------------------------------- compute
    def _fix(self, val):
        iv = int(val) if (self.u[U_MODE1] & TRUNC) else int(round(val))
        return max(-1 << 31, min((1 << 31) - 1, iv))

    def compute1(self, c):
        """One compute operation, with the ALU carry kept as the 21469 keeps it: the carry
        operations set AC, Rx+1, Rx-1, -Rx and (Rx+Ry)/2 set their own carry, and every
        other single-function ALU operation clears it (on the unit, 2026-10-25:
        `if ac r0 = pass r2; if ac r1 = pass r3` ran the second move with AC cleared)."""
        if c and not c >> 22 and c >> 20 & 3 == 0:
            op = c >> 12 & 0xFF
            dual = c >> 16 & 15 in (0x7, 0xF) and op >> 4 in (0x7, 0xF)
            if not dual and not 0x11 <= op <= 0x1F:
                rx, ry = self.R(c >> 4 & 15), self.R(c & 15)
                self._compute1(c)
                if op in (0x01, 0x02, 0x05, 0x06, 0x25, 0x26): pass
                elif op == 0x29: self.ac = rx == M32
                elif op == 0x2A: self.ac = rx != 0
                elif op == 0x22: self.ac = rx == 0
                elif op == 0x09: self.ac = rx + ry > M32
                else: self.ac = False
                return
        self._compute1(c)

    def _compute1(self, c):
        if c == 0:
            return
        n, x, y = c >> 8 & 15, c >> 4 & 15, c & 15
        if c >> 22:                                           # multifunction
            code = c >> 16 & 0x3F
            m, a = c >> 12 & 15, n
            xm, ym, xa, ya = c >> 6 & 3, 4 + (c >> 4 & 3), 8 + (c >> 2 & 3), 12 + (c & 3)
            if code == 0x00:
                self.u[n] = (self.mrb[m & 3] if m & 4 else self.mrf[m & 3]) & M32
                return
            if code == 0x01:
                if m & 4: self.mrb[m & 3] = self.u[n] & M32
                else: self.mrf[m & 3] = self.u[n] & M32
                return
            if code == 0x17:                                  # T1 double dmul + dsub
                p = self.D(xm) * self.D(ym)
                d = self.D(xa) - self.D(ya)
                self.setD(m, p)
                self.setD(a, d)
                self.az, self.an = d == 0.0, d < 0.0
                return
            if 0x18 <= code <= 0x1F:
                p = ftz(f2b(self.F(xm) * self.F(ym)))
                k = code - 0x18
                fxa, fya = self.F(xa), self.F(ya)
                rxa, rya = self.R(xa), self.R(ya)
                self.u[m] = p
                if k == 0: self.setF(a, fxa + fya)
                elif k == 1: self.setF(a, fxa - fya)
                elif k == 2: self.setF(a, float(s32(rxa)) * exp2f(max(-127, min(127, s32(rya)))))
                elif k == 3: self.setR(a, self._fix(fxa * exp2f(max(-127, min(127, s32(rya))))))
                elif k == 4: self.setF(a, (fxa + fya) * 0.5)
                elif k == 5:
                    self.setF(a, abs(fxa))
                    self.an = False
                elif k == 6: self.setF(a, max(fxa, fya))
                elif k == 7: self.setF(a, min(fxa, fya))
                return
            if code >> 4 == 3:                                # Fm = Fxm*Fym, Fa = Fxa+Fya, Fs = Fxa-Fya
                s = code & 15
                p = ftz(f2b(self.F(xm) * self.F(ym)))
                sm, df = self.F(xa) + self.F(ya), self.F(xa) - self.F(ya)
                self.u[m] = p
                self.setF(s, df)
                df_az, df_an = self.az, self.an
                self.setF(a, sm)
                self.az = self.az or df_az
                self.an = self.an or df_an
                return
            raise SimError(f"multifunction compute {code:#x} is not modelled")
        cu, op = c >> 20 & 3, c >> 12 & 0xFF
        if cu == 0:
            if c >> 16 & 15 in (0x7, 0xF) and op >> 4 in (0x7, 0xF):       # dual add/subtract
                s = c >> 12 & 15
                if op >> 4 == 0xF:
                    a, d = self.F(x) + self.F(y), self.F(x) - self.F(y)
                    self.setF(s, d)
                    d_az, d_an = self.az, self.an
                    self.setF(n, a)
                    self.az = self.az or d_az
                    self.an = self.an or d_an
                else:
                    a, d = s32(self.R(x)) + s32(self.R(y)), s32(self.R(x)) - s32(self.R(y))
                    self.u[s] = d & M32
                    self.setR(n, a)
                    self.az = self.az or (d & M32) == 0
                    self.an = self.an or (d < 0)
                return
            if 0x11 <= op <= 0x1F:                            # T1 64-bit float ALU
                if op == 0x11:
                    v = self.D(x) + self.D(y)
                    self.setD(n, v)
                    self.az, self.an = v == 0.0, v < 0.0
                elif op == 0x12:
                    v = self.D(x) - self.D(y)
                    self.setD(n, v)
                    self.az, self.an = v == 0.0, v < 0.0
                elif op == 0x13:
                    vx, vy = self.D(x), self.D(y)
                    self.az, self.an = vx == vy, vx < vy
                elif op == 0x14:
                    v = -self.D(x)
                    self.setD(n, v)
                    self.az, self.an = v == 0.0, v < 0.0
                elif op == 0x15:
                    v = abs(self.D(x))
                    self.setD(n, v)
                    self.az, self.an = v == 0.0, False
                elif op == 0x19:
                    self.setR(n, int(self.D(x)))
                    self.sv = False
                elif op == 0x1B:
                    v = float(s32(self.R(x)))
                    self.setD(n, v)
                    self.az, self.an = v == 0.0, v < 0.0
                elif op == 0x1D:
                    v = float(self.F(x))
                    self.setD(n, v)
                    self.az, self.an = v == 0.0, v < 0.0
                elif op == 0x1E:
                    self.setF(n, self.D(x))
                elif op == 0x1F:
                    v = self.D(x) * (2.0 ** s32(self.R(y)))
                    self.setD(n, v)
                    self.az, self.an = v == 0.0, v < 0.0
                else:
                    raise SimError(f"64-bit ALU operation {op:#x} is not modelled")
                return
            rx, ry, fx, fy = self.R(x), self.R(y), self.F(x), self.F(y)
            if op == 0x01:
                s = rx + ry
                self.ac = s > M32
                self.setR(n, s)
            elif op == 0x02:
                self.ac = rx >= ry
                self.setR(n, rx - ry)
            elif op == 0x05:
                s = rx + ry + int(self.ac)
                self.ac = s > M32
                self.setR(n, s)
            elif op == 0x06:
                s = rx + (ry ^ M32) + int(self.ac)
                self.ac = s > M32
                self.setR(n, s)
            elif op == 0x09: self.setR(n, (s32(rx) + s32(ry)) >> 1)
            elif op == 0x0A: self.az, self.an = s32(rx) == s32(ry), s32(rx) < s32(ry)
            elif op == 0x0B: self.az, self.an = rx == ry, rx < ry
            elif op == 0x25:
                s = rx + int(self.ac)
                self.ac = s > M32
                self.setR(n, s)
            elif op == 0x26:
                s = rx + M32 + int(self.ac)
                self.ac = s > M32
                self.setR(n, s)
            elif op == 0x29: self.setR(n, rx + 1)
            elif op == 0x2A: self.setR(n, rx - 1)
            elif op == 0x22: self.setR(n, -s32(rx))
            elif op == 0x30:
                self.setR(n, abs(s32(rx)))
                self.an = False
            elif op == 0x21: self.setR(n, rx)
            elif op == 0x40:
                self.u[n] = (rx & ry) & M32
                self.az = self.u[n] == 0
            elif op == 0x41:
                self.u[n] = (rx | ry) & M32
                self.az = self.u[n] == 0
            elif op == 0x42:
                self.u[n] = (rx ^ ry) & M32
                self.az = self.u[n] == 0
            elif op == 0x43:
                self.u[n] = (~rx) & M32
                self.az = self.u[n] == 0
            elif op == 0x61: self.setR(n, min(s32(rx), s32(ry)))
            elif op == 0x62: self.setR(n, max(s32(rx), s32(ry)))
            elif op == 0x63:
                lim = abs(s32(ry))
                self.setR(n, max(-lim, min(lim, s32(rx))))
            elif op == 0x81: self.setF(n, fx + fy)
            elif op == 0x82: self.setF(n, fx - fy)
            elif op == 0x89: self.setR(n, ftz(f2b((fx + fy) * 0.5)))
            elif op == 0x8A: self.az, self.an = fx == fy, fx < fy
            elif op == 0x91:
                self.setF(n, abs(fx + fy))
                self.an = False
            elif op == 0x92:
                self.setF(n, abs(fx - fy))
                self.an = False
            elif op == 0xA2: self.setF(n, -fx)
            elif op == 0xB0:
                self.setF(n, abs(fx))
                self.an = False
            elif op == 0xA1: self.setF(n, fx)
            elif op == 0xA5: self.u[n] = ftz(f2b(fx))
            elif op == 0xBD: self.setF(n, fx * exp2f(max(-127, min(127, s32(ry)))))
            elif op == 0xC1: self.setR(n, ((rx >> 23) & 0xFF) - 127)
            elif op == 0xC4:
                if RECIPS_HW:
                    self.u[n] = recips_hw(rx)
                    v = b2f(self.u[n])
                    self.az, self.an = v == 0.0, v < 0.0
                else:
                    self.setF(n, 0.0 if fx == 0.0 else 1.0 / fx)
            elif op == 0xCA: self.setF(n, float(s32(rx)))
            elif op == 0xC9: self.setR(n, self._fix(fx))
            elif op == 0xCD: self.setR(n, int(fx))
            elif op == 0xDA: self.setF(n, float(s32(rx)) * exp2f(max(-127, min(127, s32(ry)))))
            elif op == 0xD9: self.setR(n, self._fix(fx * exp2f(max(-127, min(127, s32(ry))))))
            elif op == 0xDD: self.setR(n, int(fx * exp2f(max(-127, min(127, s32(ry))))))
            elif op == 0xE0:
                res = (rx & 0x7FFFFFFF) | (ry & 0x80000000)
                self.u[n] = res
                self.az, self.an = (res & 0x7FFFFFFF) == 0, bool(res & 0x80000000)
            elif op == 0xE1: self.setF(n, min(fx, fy))
            elif op == 0xE2: self.setF(n, max(fx, fy))
            elif op == 0xE3:
                lim = abs(fy)
                self.setF(n, max(-lim, min(lim, fx)))
            else: raise SimError(f"ALU operation {op:#x} is not modelled")
        elif cu == 1:
            if op == 0x30: self.u[n] = ftz(f2b(self.F(x) * self.F(y)))
            elif op == 0x31: self.setD(n, self.D(x) * self.D(y))
            elif op == 0x32: self.setD(n, self.D(x) * float(self.F(y)))
            elif op == 0x33: self.setD(n, float(self.F(x)) * float(self.F(y)))
            elif op == 0x40: self.u[n] = (self.R(x) * self.R(y)) & M32
            elif op == 0x44:
                prod = self.R(x) * self.R(y)
                self.mrf[0], self.mrf[1], self.mrf[2] = prod & M32, (prod >> 32) & M32, 0
            elif op == 0x70: self.u[n] = (s32(self.R(x)) * s32(self.R(y))) & M32
            elif op == 0xB4:                                  # MRF = MRF + Rx * Ry (SSI): 80 bits
                acc = (sx(self.mrf[2] & 0xFFFF, 16) << 64) | (self.mrf[1] << 32) | self.mrf[0]
                acc += s32(self.R(x)) * s32(self.R(y))
                self.mrf[0], self.mrf[1], self.mrf[2] = acc & M32, (acc >> 32) & M32, (acc >> 64) & 0xFFFF
            elif op == 0x14: self.mrf[0] = self.mrf[1] = self.mrf[2] = 0     # MRF = 0
            else: raise SimError(f"multiplier operation {op:#x} is not modelled")
        else:
            rx, ry = self.R(x), self.R(y)
            k = sx(ry & 0xFF, 8)
            if op in (0x00, 0x20):
                v = 0 if (k >= 32 or k <= -32) else ((rx << k) & M32 if k >= 0 else rx >> -k)
                self.u[n] = (self.u[n] | v) if op == 0x20 else v
                self.sz = self.u[n] == 0
            elif op in (0x04, 0x24):
                srx = s32(rx)
                v = 0 if k >= 32 else ((srx << k) & M32 if k >= 0 else (M32 if (k <= -32 and srx < 0) else (srx >> -k) & M32))
                self.u[n] = (self.u[n] | v) if op == 0x24 else v
                self.sz = self.u[n] == 0
            elif op == 0x88:
                res = clz32(rx)
                self.u[n] = res
                self.sv, self.sz = rx == 0, res == 0
            elif op == 0x8C:
                inv = (~rx) & M32
                res = clz32(inv)
                self.u[n] = res
                self.sv, self.sz = inv == 0, res == 0
            elif op == 0xC0:
                self.u[n] = (rx | (1 << (ry & 31))) & M32
                self.sz = self.u[n] == 0
            elif op == 0xC4:
                self.u[n] = (rx & ~(1 << (ry & 31))) & M32
                self.sz = self.u[n] == 0
            elif op == 0xC8:
                self.u[n] = (rx ^ (1 << (ry & 31))) & M32
                self.sz = self.u[n] == 0
            elif op == 0xCC:                                  # BTST: sets SZ only (not TF), as the 21469 does
                b = (rx >> (ry & 31)) & 1
                self.sz = b == 0
            else: raise SimError(f"shifter operation {op:#x} is not modelled")

    def shimm1(self, w):
        op6 = w >> 16 & 0x3F
        raw12 = (w >> 27 & 15) << 8 | (w >> 8 & 0xFF)
        k = sx(raw12, 12)
        n, x = w >> 4 & 15, w & 15
        rx = self.R(x)
        if op6 in (0x00, 0x08):                               # LSHIFT / OR LSHIFT
            v = 0 if (k >= 32 or k <= -32) else ((rx << k) & M32 if k >= 0 else rx >> -k)
            self.u[n] = (self.u[n] | v) if op6 == 0x08 else v
            self.sz = self.u[n] == 0
            self.az, self.an = self.u[n] == 0, bool(self.u[n] >> 31)
        elif op6 in (0x01, 0x09):                             # ASHIFT / OR ASHIFT
            srx = s32(rx)
            v = 0 if k >= 32 else ((srx << k) & M32 if k >= 0 else (M32 if (k <= -32 and srx < 0) else (srx >> -k) & M32))
            self.u[n] = (self.u[n] | v) if op6 == 0x09 else v
            self.sz = self.u[n] == 0
            self.az, self.an = self.u[n] == 0, bool(self.u[n] >> 31)
        elif op6 in (0x10, 0x11, 0x18, 0x19):                 # FEXT / FDEP / OR FDEP
            pos, ln = raw12 & 0x3F, (raw12 >> 6) & 0x3F
            mask = M32 if ln >= 32 else (0 if ln == 0 else (1 << ln) - 1)
            if op6 == 0x10:
                v = (rx >> (pos & 31)) & mask
                self.u[n] = v
            else:
                v = ((rx & mask) << (pos & 31)) & M32
                self.u[n] = (self.u[n] | v) if (op6 & 8) else v
            self.sz = self.u[n] == 0
        elif op6 == 0x30:                                     # BSET
            self.u[n] = (rx | (1 << (k & 31))) & M32
            self.sz = self.u[n] == 0
        elif op6 == 0x31:                                     # BCLR
            self.u[n] = (rx & ~(1 << (k & 31))) & M32
            self.sz = self.u[n] == 0
        elif op6 == 0x32:                                     # BTGL
            self.u[n] = (rx ^ (1 << (k & 31))) & M32
            self.sz = self.u[n] == 0
        elif op6 == 0x33:                                     # BTST: sets SZ only, not TF (on the unit,
            b = (rx >> (k & 31)) & 1                          # 2026-10-25, code that read TF after BTST
            self.sz = b == 0                                  # branched on a stale TF)
        else:
            raise SimError(f"immediate shift {op6:#x} is not modelled")

    def shimm(self, w):
        self._scalar(0)
        self.shimm1(w)
        if self.simd:
            x_flags = self._pack_flags()
            self._unpack_flags(self.u[U_ASTATY])
            self._swap_pe()
            self.shimm1(w)
            self.u[U_ASTATY] = (self.u[U_ASTATY] & ~ASTAT_MASK) | self._pack_flags()
            self._swap_pe()
            self._unpack_flags(x_flags)

    # ---------------------------------------------------------- one instruction
    def _cond_exec(self, cc, fn):
        if not self.simd or cc == 31:
            if self.cond(cc):
                fn()
            return
        cx, cy = self.cond(cc), self.cond_pey(cc)
        if not cx and not cy:
            return
        if cx and cy:
            fn()
        elif cx:
            m1, eff = self.u[U_MODE1], self._pey_eff
            self.u[U_MODE1] &= ~PEYEN
            self._pey_eff = None
            fn()
            self.u[U_MODE1] = (self.u[U_MODE1] & ~PEYEN) | (m1 & PEYEN)
            self._pey_eff = eff
        else:
            saved_r = self.u[0:16]
            saved_mrf = list(self.mrf)
            saved_flags = self._pack_flags()
            fn()
            self.u[0:16] = saved_r
            self.mrf = saved_mrf
            self._unpack_flags(saved_flags)

    def step(self):
        # BIT SET/CLR MODE1 changing PEYEN takes effect one instruction later;
        # POP STS at once (measured on the unit, 2026-10-25).
        self._pey_eff, self._pey_next = self._pey_next, None
        before = self.u[U_MODE1] & PEYEN
        w = self.pm.get(self.pc, 0)
        r = self._step()
        if (w >> 40) == 0x14 and (self.u[U_MODE1] & PEYEN) != before:
            self._pey_next = bool(before)
        sel = self.u[U_MODE1] & (SRRFL | SRRFH)
        if sel != self.srrf:                 # register file switch: seen by the next instruction
            for lo, bit in ((0, SRRFL), (8, SRRFH)):
                if (sel ^ self.srrf) & bit:
                    for base, a in ((lo, lo), (0x50 + lo, 16 + lo)):
                        self.u[base:base + 8], self.alt[a:a + 8] = self.alt[a:a + 8], self.u[base:base + 8]
            self.srrf = sel
        return r

    def _step(self):
        pc = self.pc
        if pc in self.hle:
            self.cycles += 1
            return self.hle[pc](self)
        if pc not in self.pm:
            raise SimError(f"no code at {pc:#x}")
        w = self.pm[pc]
        self.cycles += 1
        if self.u[U_MODE2] & TIMEN:
            self.u[U_TCOUNT] = (self.u[U_TCOUNT] - 1) & M32
        nxt = pc + 1
        branched = False
        top, op8, cc, cmp_ = w >> 45, w >> 40, w >> 33 & 31, w & 0x7FFFFF

        def branch(target, call, db):
            nonlocal nxt, branched
            branched = True
            t = target & 0xFFFFFF
            if call:
                for lp in self.loops:                         # seen on the unit (a test kernel,
                    if 0 <= lp[1] - pc < 3:                   # 2026-10-25): the loop ran half its count
                        raise SimError(f"a CALL in the last three instructions of a loop (pc {pc:#x})")
                self.pcstk.append(pc + 3 if db else pc + 1)
            if db:
                self.pending_branch = (t, 2)
            else:
                nxt = t

        if top == 1:                                          # compute, DM and PM moves
            di, dmm, dr = w >> 41 & 7, w >> 38 & 7, w >> 33 & 15
            pi, pmm, pr = 8 + (w >> 30 & 7), 8 + (w >> 27 & 7), w >> 23 & 15
            dst, pst = w >> 44 & 1, w >> 37 & 1
            dv, pv = self.dget(dr), self.dget(pr)
            da, pa = self.post(di, self.u[0x20 + dmm]), self.post(pi, self.u[0x20 + pmm])
            dl = None if dst else self.dload(da, di)
            pl = None if pst else self.dload(pa, pi)
            self.compute(cmp_)
            if dst: self.dstore(da, dv)
            else: self.dset(dr, dl)
            if pst: self.dstore(pa, pv)
            else: self.dset(pr, pl)
        elif top == 2:                                        # ureg <-> memory through I, M
            def _do_top2():
                g = w >> 32 & 1
                i, m, ur = (w >> 41 & 7) + 8 * g, (w >> 38 & 7) + 8 * g, w >> 23 & 0x7F
                lw = bool(w >> 30 & 1)
                bw = self.byte_mode and cmp_ in (1, 2)
                c = 0 if bw else cmp_
                if 0x10 <= ur < 0x50 and (ur & 15 >= 8) == bool(g) and (w >> 31 & 1 or w >> 44 & 1):
                    raise SimError(f"an address-generator register moved through its own generator (pc {pc:#x})")
                sc = (1 if cmp_ == 1 else 2) if bw else None
                a = self.post(i, self.u[0x20 + m], sc) if w >> 44 & 1 else self.pre(i, self.u[0x20 + m], sc)
                if bw:
                    if w >> 31 & 1:
                        v = self.get(ur)
                        if cmp_ == 1: self.wr8(a, v)
                        else:
                            self.wr8(a, v & 0xFF)
                            self.wr8(a + 1, (v >> 8) & 0xFF)
                    else:
                        v = self.rd8(a) if cmp_ == 1 else (self.rd8(a) | (self.rd8(a + 1) << 8))
                        self.set(ur, v)
                    return
                if lw:
                    ws = self.wstep
                    if w >> 31 & 1:
                        lo, hi = (self.u[ur & ~1], self.u[ur | 1]) if (ur < 16 or 0x50 <= ur < 0x60) else (self.get(ur), 0)
                        self.compute(c)
                        self.wr(a, lo)
                        self.wr(a + ws, hi)
                    else:
                        lo, hi = self.rd(a), self.rd(a + ws)
                        self.compute(c)
                        if ur < 16 or 0x50 <= ur < 0x60:
                            self.u[ur & ~1], self.u[ur | 1] = lo, hi
                        else:
                            self.set(ur, lo)
                    return
                pair = ur < 16 or 0x50 <= ur < 0x60
                self._scalar(*([] if pair else [ur]))
                if w >> 31 & 1:
                    v = self.dget(ur) if pair else self.get(ur)
                    self.compute(c)
                    self.dstore(a, v) if pair else self.ustore(a, v)
                else:
                    v = self.dload(a, i) if pair else self.rd(a)
                    self.compute(c)
                    self.dset(ur, v) if pair else self.set(ur, v)
            self._cond_exec(cc, _do_top2)
        elif top == 3 and not w >> 44 & 1:                    # dreg <-> memory, 6-bit offset
            def _do_top3m():
                i, r, d6 = (w >> 41 & 7) + 8 * (w >> 40 & 1), w >> 23 & 15, sx(w >> 27 & 0x3F, 6)
                bw = self.byte_mode and cmp_ == 1
                c = 0 if bw else cmp_
                sc = 1 if bw else None
                a = self.post(i, d6, sc) if w >> 38 & 1 else self.pre(i, d6, sc)
                if bw:
                    if w >> 39 & 1: self.wr8(a, self.u[r])
                    else: self.u[r] = self.rd8(a)
                    return
                if w >> 39 & 1:
                    v = self.dget(r)
                    self.compute(c)
                    self.dstore(a, v)
                else:
                    v = self.dload(a, i)
                    self.compute(c)
                    self.dset(r, v)
            self._cond_exec(cc, _do_top3m)
        elif top == 3:
            if w >> 43 & 1:                                   # R <-> S swap
                if self.cond(cc):
                    rx, sy = w >> 23 & 15, 0x50 + (w >> 38 & 15)
                    v_r, v_s = self.u[rx], self.u[sy]
                    self.compute(cmp_)
                    self.u[rx], self.u[sy] = v_s, v_r
            else:
                def _do_top3u():
                    s, d = (w >> 38 & 0x1F) << 2 | w >> 31 & 3, w >> 23 & 0x7F
                    self._scalar(s, d)
                    v = self.get(s)
                    vs = self.u[0x50 + s] if (self.simd and s < 16) else v
                    self.compute(cmp_)
                    self.set(d, v)
                    if self.simd and d < 16 and not (0x50 <= s < 0x60):
                        self.u[0x50 + d] = vs
                self._cond_exec(cc, _do_top3u)
        elif top == 4 and w >> 44 & 1:                        # memory = constant
            g = w >> 37 & 1
            self.wr(self.post((w >> 41 & 7) + 8 * g, self.u[0x20 + (w >> 38 & 7) + 8 * g]), w)
        elif top == 4:                                        # immediate shift with a move
            def _do_top4s():
                g = w >> 32 & 1
                i, m, r = (w >> 41 & 7) + 8 * g, (w >> 38 & 7) + 8 * g, w >> 23 & 15
                a = self.post(i, self.u[0x20 + m])
                if w >> 31 & 1:
                    v = self.dget(r)
                    self.shimm(w)
                    self.dstore(a, v)
                else:
                    v = self.dload(a, i)
                    self.shimm(w)
                    self.dset(r, v)
            self._cond_exec(cc, _do_top4s)
        elif top == 5:                                        # ureg <-> DM(offset, I)
            ur = w >> 32 & 0x7F
            i = (w >> 41 & 7) + 8 * (w >> 44 & 1)
            lw = bool(w >> 39 & 1)
            a = self.pre(i, s32(w))
            if lw:
                ws = self.wstep
                if w >> 40 & 1:
                    lo, hi = (self.u[ur & ~1], self.u[ur | 1]) if (ur < 16 or 0x50 <= ur < 0x60) else (self.get(ur), 0)
                    self.wr(a, lo)
                    self.wr(a + ws, hi)
                else:
                    lo, hi = self.rd(a), self.rd(a + ws)
                    if ur < 16 or 0x50 <= ur < 0x60:
                        self.u[ur & ~1], self.u[ur | 1] = lo, hi
                    else:
                        self.set(ur, lo)
            elif (ur < 16 or 0x50 <= ur < 0x60) and self.simd:
                if w >> 40 & 1: self.dstore(a, self.dget(ur))
                else: self.dset(ur, self.dload(a, i))
            else:
                self._scalar(ur)
                if w >> 40 & 1: self.ustore(a, self.get(ur))
                else: self.set(ur, self.rd(a))
        elif top:
            raise SimError(f"instruction {w:012x} is not modelled")
        elif op8 == 0x00:
            if w >> 39 & 1:
                raise SimError("IDLE")
        elif op8 == 0x01:
            self._cond_exec(cc, lambda: self.compute(cmp_))
        elif op8 == 0x02:
            self._cond_exec(cc, lambda: self.shimm(w))
        elif op8 == 0x04:                                     # MODIFY (I, M)
            def _do_modm():
                g = 8 * (w >> 38 & 1)
                src = g + (w >> 30 & 7)
                sc = (4 if (w >> 39 & 1) else 1) if self.byte_mode else 1
                self.compute(cmp_)
                v = self._wrap(src, self.u[0x10 + src] + s32(self.u[0x20 + g + (w >> 27 & 7)]) * sc)
                self.u[0x10 + (src ^ (w >> 24 & 7))] = v
            self._cond_exec(cc, _do_modm)
        elif op8 in (0x06, 0x07):                             # direct jump / call
            if self.cond(cc):
                if w >> 38 & 1 and self.loops:
                    self.loops.pop()
                t = w & 0xFFFFFF
                branch(pc + sx(t, 24) if op8 & 1 else t, w >> 39 & 1, w >> 26 & 1)
        elif op8 in (0x08, 0x09):                             # indirect or short relative, with compute
            taken = self.cond(cc)
            if taken != bool(w >> 25 & 1):
                self.compute(cmp_)
            if taken:
                if w >> 38 & 1 and self.loops:
                    self.loops.pop()
                if op8 & 1:
                    t = pc + sx(w >> 27 & 0x3F, 6)
                else:
                    t = self.u[0x18 + (w >> 30 & 7)] + s32(self.u[0x28 + (w >> 27 & 7)])
                branch(t, w >> 39 & 1, w >> 26 & 1)
        elif op8 in (0x0A, 0x0B):                             # RTS / RTI
            taken = self.cond(cc)
            if taken != bool(w >> 25 & 1):
                self.compute(cmp_)
            if taken:
                db = bool(w >> 26 & 1)
                if not self.pcstk and not db:
                    return False                              # return from the entry call
                t = self.pcstk.pop() if self.pcstk else 0x00F8FFFF
                branch(t, False, db)
        elif op8 in (0x0C, 0x0D):                             # counted loop
            n = w >> 24 & 0xFFFF if op8 == 0x0C else self.get(w >> 32 & 0x7F)
            end_pc = (pc + sx(w & 0xFFFFFF, 24)) & 0xFFFFFF
            if s32(n) <= 0:
                nxt = end_pc + 1
                branched = True
            else:
                self.u[U_LCNTR] = n
                self.loops.append([pc + 1, end_pc, n])
        elif op8 == 0x0F:
            ur = w >> 32 & 0x7F
            self._scalar(ur)
            self.set(ur, w)
            if self.simd and ur < 16:
                self.u[0x50 + ur] = w & M32
        elif 0x10 <= op8 <= 0x13:                             # ureg <-> DM(address)
            ur = w >> 32 & 0x7F
            a = w & M32
            if w >> 39 & 1:
                ws = self.wstep
                if op8 & 1:
                    lo, hi = (self.u[ur & ~1], self.u[ur | 1]) if (ur < 16 or 0x50 <= ur < 0x60) else (self.get(ur), 0)
                    self.wr(a, lo)
                    self.wr(a + ws, hi)
                else:
                    lo, hi = self.rd(a), self.rd(a + ws)
                    if ur < 16 or 0x50 <= ur < 0x60:
                        self.u[ur & ~1], self.u[ur | 1] = lo, hi
                    else:
                        self.set(ur, lo)
            else:
                self._scalar(ur)
                if op8 & 1: self.ustore(a, self.get(ur))
                else: self.set(ur, self.rd(a))
        elif op8 == 0x14:                                     # BIT
            r, d, bop = 0x70 + (w >> 32 & 15), w & M32, w >> 37 & 7
            v = self.get(r)
            if bop == 0: self.set(r, v | d)
            elif bop == 1: self.set(r, v & ~d)
            elif bop == 2: self.set(r, v ^ d)
            elif bop == 4:
                self.sz = (v & d) == 0
                self.tf = (v & d) != 0
            elif bop == 5: self.tf = v == d
            if r == U_FLAGS and self.u[r] != v:
                self.flag_log.append((self.cycles, self.u[r]))
        elif op8 == 0x16 and not w >> 39 & 1:                 # MODIFY (I, constant)
            src = 8 * (w >> 38 & 1) + (w >> 32 & 7)
            self.u[0x10 + (src ^ (w >> 35 & 7))] = self._wrap(src, self.u[0x10 + src] + s32(w))
        elif op8 == 0x17:                                     # PUSH/POP LOOP/STS/PCSTK
            bits = w >> 33 & 0x7F
            if bits & 0x40: self.loops.append([M32, M32, self.u[U_LCNTR]])
            if bits & 0x20 and self.loops: self.loops.pop()
            if bits & 0x10: self.stsstk.append((self.u[U_MODE1], self.u[U_ASTATX], self.u[U_ASTATY], self._pack_flags()))
            if bits & 0x08 and self.stsstk:
                m1, ax, ay, pf = self.stsstk.pop()
                self.u[U_MODE1], self.u[U_ASTATX], self.u[U_ASTATY] = m1, ax, ay
                self._unpack_flags(pf)
            if bits & 0x04: self.pcstk.append(0)
            if bits & 0x02 and self.pcstk: self.pcstk.pop()
        elif op8 == 0x18:                                     # CJUMP
            t = w & 0xFFFFFF
            if w >> 38 & 1:
                t = (pc + sx(t, 24)) & 0xFFFFFF
            self.u[2] = self.u[0x16]
            self.u[0x16] = self.u[0x17]
            branch(t, False, bool(w >> 34 & 1 or w >> 26 & 1))
        elif op8 == 0x19:                                     # RFRAME
            old_fp = self.rd(self.u[0x16])
            self.u[0x17] = self.u[0x16]
            self.u[0x16] = old_fp
        else:
            raise SimError(f"instruction {w:012x} at {pc:#x} is not modelled")

        while self.loops and self.loops[-1][1] == pc:
            lp = self.loops[-1]
            if lp[2] > 1:
                lp[2] -= 1
                nxt = lp[0]
                break
            else:
                self.loops.pop()

        if not branched and self.pending_branch is not None:
            t, left = self.pending_branch
            if left == 1:
                self.pending_branch = None
                if t in (0x00F8FFFE, 0x00F8FFFF):
                    self.pc = t
                    return False
                nxt = t
            else:
                self.pending_branch = (t, left - 1)
        elif branched and nxt in (0x00F8FFFE, 0x00F8FFFF) and self.pending_branch is None:
            self.pc = nxt
            return False

        self.pc = nxt
        return True

    def call(self, entry, limit=50_000_000):
        """Run from `entry` until its RTS; returns the instructions executed."""
        self.pc, self.pcstk, self.loops, self.pending_branch = entry, [], [], None
        start = self.cycles
        while self.step():
            if self.cycles - start > limit:
                raise SimError(f"no return after {limit} instructions (pc {self.pc:#x})")
        return self.cycles - start
