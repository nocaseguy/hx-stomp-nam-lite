#!/usr/bin/env python3
"""visa_dis - a disassembler for the SHARC code in Entry 2, 48-bit ISA and VISA.

Entry 2 is an LDR boot stream: blocks {tag, count, addr} from word 384 of the raw payload.
Its code is in three kinds of block:

    tag 5    48-bit ISA instructions in PM, at normal-word addresses (0x8c100..0x8ee95)
    tag 3    VISA in internal memory: 16-bit parcels at short-word addresses,
             the high half of each 32-bit word first
    tag 10   VISA in DDR2: word 0x300000 + k holds the parcels at short-word
             0x600000 + 2k (low half) and 0x600000 + 2k + 1 (high half)

VISA keeps every ISA instruction as three parcels, highest first, and adds 32- and 16-bit
forms (types 1b..25c of the ADSP-2136x/2137x/214xx Programming Reference rev 2.4, chapter 10);
docs/research/SHARC_VISA.md has the rules and how they were checked. A form not worked out
comes out as `?? xxxx` (one parcel), never a guess.
Branch and loop targets are printed as absolute addresses, as sasm takes them.

    python3 tools/sharc/visa_dis.py [--hxf F] START [END | +N]     VISA, short-word addresses
    python3 tools/sharc/visa_dis.py --pm START [END | +N]           ISA, PM addresses
"""
import argparse
import os
import struct
import sys
from typing import NamedTuple

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [p for p in (_HERE, os.path.dirname(_HERE)) if p not in sys.path]

from sasm import ALU, COND, MRREG, MULALU, SHIFT, STACKOP, TERM, UREG, _SREG7, mult_text  # noqa: E402

BOP = {0: "SET", 1: "CLR", 2: "TGL", 4: "TST", 5: "XOR"}
DDR_VISA = 0x600000                  # short-word address of tag-10 word 0x300000
SW_SPACE = (0x100000, 0x200000)      # internal memory's short-word addresses, where tag 3 loads

# type 2c short compute (1100 op Rn Rx), the Programming Reference's "Short Compute Opcodes"
SHORT = {0x0: "R{n} = R{n} + R{x}", 0x1: "R{n} = R{n} - R{x}", 0x2: "R{n} = PASS R{x}", 0x3: "COMP(R{n}, R{x})",
         0x4: "R{n} = NOT R{x}", 0x5: "R{n} = R{x} + 1", 0x6: "R{n} = R{x} - 1", 0x7: "R{n} = R{n} * R{x} (SSI)",
         0x8: "F{n} = F{n} + F{x}", 0x9: "F{n} = F{n} - F{x}", 0xA: "F{n} = FLOAT R{x}", 0xB: "COMP(F{n}, F{x})",
         0xC: "R{n} = R{n} AND R{x}", 0xD: "R{n} = R{n} OR R{x}", 0xE: "R{n} = R{n} XOR R{x}", 0xF: "F{n} = F{n} * F{x}"}


# ------------------------------------------------------------------ Entry 2
class Image(NamedTuple):
    pm: dict        # PM address -> 48-bit ISA word
    dm: dict        # DM address -> 32-bit word (tag 4)
    sw: dict        # short-word address -> 16-bit VISA parcel


_WORDS = {5: lambda c: ((c + 1) & ~1) * 3 // 2, 4: lambda c: c, 3: lambda c: (c + 1) // 2,
          6: lambda c: c * 2, 0: lambda c: 384, 10: lambda c: c, 9: lambda c: c}


def parse_entry2(raw):
    """Image of Entry 2's raw payload (l6ia.parse(l6)[2]'s bytes, not swapped)."""
    w = struct.unpack("<%dI" % (len(raw) // 4), raw[:len(raw) // 4 * 4])
    pm, dm, sw = {}, {}, {}
    i = 384
    while i + 3 <= len(w):
        tag, cnt, addr = w[i:i + 3]
        if tag == 0:
            break
        n = _WORDS.get(tag, lambda c: 0)(cnt)
        body = w[i + 3:i + 3 + n]
        if tag == 5:
            b = struct.pack("<%dI" % len(body), *body)
            for k in range(cnt):
                pm[addr + k] = int.from_bytes(b[6 * k:6 * k + 6], "little")
        elif tag == 4:
            dm.update((addr + k, v) for k, v in enumerate(body))
        elif tag == 3:
            for k in range(cnt):
                sw[addr + k] = body[k >> 1] >> (0 if k & 1 else 16) & 0xFFFF
        elif tag == 10:
            for k, v in enumerate(body):
                a = DDR_VISA + 2 * (addr + k - 0x300000)
                sw[a], sw[a + 1] = v & 0xFFFF, v >> 16
        elif tag == 1 and SW_SPACE[0] <= addr < SW_SPACE[1]:        # zeros, even mid-instruction
            sw.update((addr + k, 0) for k in range(cnt))
        elif tag == 1 and 0x300000 <= addr < 0x400000:
            sw.update((DDR_VISA + 2 * (addr - 0x300000) + k, 0) for k in range(2 * cnt))
        i += 3 + n
    return Image(pm, dm, sw)


def load(path=None):
    """Image of Entry 2 from a .hxf or L6IA file (default: $HX_STOMP_HXF)."""
    import l6ia
    import patch_amp
    path = path or os.environ.get("HX_STOMP_HXF")
    if not path:
        raise SystemExit("no firmware: pass --hxf or set HX_STOMP_HXF")
    l6, _ = patch_amp.load_l6ia_from_any(path)
    e = l6ia.parse(l6)[2]
    return parse_entry2(l6[e["payload_off"]:e["payload_off"] + e["payload_len"]])


# ------------------------------------------------------------------ ISA
def _sx(v, bits):
    return v - (1 << bits) if v >> (bits - 1) & 1 else v


def _num(v):
    return str(v) if -10 < v < 10 else ("-0x%x" % -v if v < 0 else "0x%x" % v)


def _cond(c):
    return "" if c == 31 else f"IF {COND[c]} "


def compute_text(c):
    """ADI text of a 23-bit compute field ('' for none), or None."""
    if c == 0:
        return ""
    if not c >> 22:
        cu, op, n, x, y = c >> 20 & 3, c >> 12 & 0xFF, c >> 8 & 15, c >> 4 & 15, c & 15
        if cu == 0 and op >> 4 in (0x7, 0xF):
            p = "R" if op >> 4 == 7 else "F"
            return f"{p}{n} = {p}{x} + {p}{y}, {p}{op & 15} = {p}{x} - {p}{y}"
        t = {0: ALU.get(op), 1: mult_text(op), 2: SHIFT.get(op)}.get(cu)
        return t and t.replace("{f}", "R{y}").replace("BY {y}", "BY R{y}").format(n=n, x=x, y=y)
    f = dict(m=c >> 12 & 15, a=c >> 8 & 15, xm=c >> 6 & 3, ym=4 + (c >> 4 & 3), xa=8 + (c >> 2 & 3), ya=12 + (c & 3))
    if c >> 21 & 1:
        p = "F" if c >> 20 & 1 else "R"
        mul = "F{m} = F{xm} * F{ym}" if p == "F" else "R{m} = R{xm} * R{ym} (SSFR)"
        return (mul + ", {p}{a} = {p}{xa} + {p}{ya}, {p}{s} = {p}{xa} - {p}{ya}").format(p=p, s=c >> 16 & 15, **f)
    code = c >> 16 & 0x3F
    if code in (0, 1) and (c >> 12 & 15) in MRREG and not c & 0xFF:
        mr, r = MRREG[c >> 12 & 15], f"R{c >> 8 & 15}"
        return f"{r} = {mr}" if code == 0 else f"{mr} = {r}"
    return MULALU[code].format(**f) if code in MULALU else None


def _with(cond, moves, comp):
    """`IF cond compute, move` text, or None when the compute does not decode."""
    ct = compute_text(comp)
    if ct is None:
        return None
    return _cond(cond) + ", ".join(p for p in [ct] + moves if p)


def _mem(g, a, store, reg, lw=0):
    sp = "PM" if g else "DM"
    lw = " (LW)" if lw else ""
    return f"{sp}({a}) = {reg}{lw}" if store else f"{reg} = {sp}({a}){lw}"


def _shimm(op6, ex, f):
    """Immediate shift text from its 6-bit op, the 4-bit dataex and the low 16 bits of the field."""
    key = op6 << 2
    t = SHIFT.get(key)
    if t is None or ("{y}" not in t and "{f}" not in t):
        return None
    d8, n, x = f >> 8 & 0xFF, f >> 4 & 15, f & 15
    if "{f}" in t:
        return t.format(n=n, x=x, f=f"{d8 & 63}:{ex << 2 | d8 >> 6}")
    return t.format(n=n, x=x, y=_sx(ex << 8 | d8, 12))


def _branch(kind, cond, target, mods, comp=0, els=0):
    m = f" ({', '.join(mods)})" if mods else ""
    ct = compute_text(comp)
    if ct is None:
        return None
    tail = f", {'ELSE ' if els else ''}{ct}" if ct else ""
    return f"{_cond(cond)}{' '.join(p for p in (kind, target) if p)}{m}{tail}"


def isa_text(w, pc=0, unit=1):
    """ADI text of 48-bit instruction word `w` at `pc`, or None. PC-relative offsets count `unit` addresses."""
    top3, cond = w >> 45, w >> 33 & 31
    comp = w & 0x7FFFFF
    rel = lambda off: f"(PC, {_num(pc + off * unit)})"  # noqa: E731
    if top3 == 1:                                                    # type 1: compute, dual move
        dm = _mem(0, f"I{w >> 41 & 7},M{w >> 38 & 7}", w >> 44 & 1, f"R{w >> 33 & 15}")
        pm = _mem(1, f"I{8 + (w >> 30 & 7)},M{8 + (w >> 27 & 7)}", w >> 37 & 1, f"R{w >> 23 & 15}")
        return _with(31, [dm, pm], comp)
    if top3 == 2:                                                    # type 3: compute, ureg <-> DM|PM(Ia,Mb)
        g, i, m = w >> 32 & 1, w >> 41 & 7, w >> 38 & 7
        ii, mm = f"I{i + 8 * g}", f"M{m + 8 * g}"
        a = f"{ii},{mm}" if w >> 44 & 1 else f"{mm},{ii}"
        return _with(cond, [_mem(g, a, w >> 31 & 1, UREG[w >> 23 & 0x7F], w >> 30 & 1)], comp)
    if top3 == 3 and not w >> 44 & 1:                                # type 4: compute, dreg <-> DM|PM(Ia, imm6)
        g, i, d6 = w >> 40 & 1, w >> 41 & 7, _sx(w >> 27 & 63, 6)
        a = f"I{i + 8 * g},{d6}" if w >> 38 & 1 else f"{d6},I{i + 8 * g}"
        return _with(cond, [_mem(g, a, w >> 39 & 1, f"R{w >> 23 & 15}")], comp)
    if top3 == 3 and not w >> 43 & 1:                                # type 5: compute, ureg = ureg
        if w >> 30 & 1:
            return None
        s = (w >> 38 & 31) << 2 | (w >> 31 & 3)
        return _with(cond, [f"{UREG[w >> 23 & 0x7F]} = {UREG[s]}"], comp)
    if top3 == 3:                                                    # type 5: compute, Rx <-> Sy
        if w >> 42 & 1 or w >> 27 & 7:
            return None
        return _with(cond, [f"R{w >> 23 & 15} <-> S{w >> 38 & 15}"], comp)
    if top3 == 4 and not w >> 44 & 1:                                # type 6: immediate shift, dreg <-> DM|PM(Ia,Mb)
        g, i, m = w >> 32 & 1, w >> 41 & 7, w >> 38 & 7
        sh = _shimm(comp >> 16 & 63, w >> 27 & 15, comp & 0xFFFF)
        if sh is None or comp >> 22:
            return None
        return _cond(cond) + sh + ", " + _mem(g, f"I{i + 8 * g},M{m + 8 * g}", w >> 31 & 1, f"R{w >> 23 & 15}")
    if top3 == 4:                                                    # type 16: DM|PM(Ia,Mb) = data32
        if w >> 32 & 31:
            return None
        g = w >> 37 & 1
        return _mem(g, f"I{(w >> 41 & 7) + 8 * g},M{(w >> 38 & 7) + 8 * g}", 1, _num(_sx(w & 0xFFFFFFFF, 32)))
    if top3 == 5:                                                    # type 15: ureg <-> DM|PM(data32, Ia)
        g = w >> 44 & 1
        return _mem(g, f"{_num(_sx(w & 0xFFFFFFFF, 32))},I{(w >> 41 & 7) + 8 * g}", w >> 40 & 1,
                    UREG[w >> 32 & 0x7F], w >> 39 & 1)
    if top3:
        return None
    op = w >> 40 & 0x1F
    if op == 0:
        return {0: "NOP", 1 << 39: "IDLE", 1 << 38: "EMUIDLE"}.get(w)
    if op == 1:                                                      # type 2: compute
        return _with(cond, [], comp) if comp and not (w >> 23 & 0x3FF or w >> 38 & 3) else None
    if op == 2:                                                      # type 6: immediate shift
        sh = _shimm(comp >> 16 & 63, w >> 27 & 15, comp & 0xFFFF)
        return None if sh is None or comp >> 22 or w >> 31 & 3 or w >> 38 & 3 else _cond(cond) + sh
    if op == 4:                                                      # type 7: compute, modify
        g = w >> 38 & 1
        src, mm, dst = (w >> 30 & 7) + 8 * g, (w >> 27 & 7) + 8 * g, (w >> 30 & 7 ^ w >> 24 & 7) + 8 * g
        if w >> 39 & 1:
            return None
        mod = f"MODIFY(I{src},M{mm})" if src == dst else f"I{dst} = MODIFY(I{src},M{mm})"
        return _with(cond, [mod], comp)
    mods = [k for k, b in (("DB", 26), ("LA", 38)) if w >> b & 1]
    if op in (6, 7):                                                 # type 8: direct jump|call
        kind = "CALL" if w >> 39 & 1 else "JUMP"
        mods += ["CI"] if w >> 24 & 1 else []
        tgt = rel(_sx(w & 0xFFFFFF, 24)) if op == 7 else _num(w & 0xFFFFFF)
        return None if w >> 25 & 1 or w >> 27 & 63 else _branch(kind, cond, tgt, mods)
    if op in (8, 9):                                                 # type 9: indirect jump|call, compute
        kind = "CALL" if w >> 39 & 1 else "JUMP"
        mods += ["CI"] if w >> 24 & 1 else []
        tgt = rel(_sx(w >> 27 & 63, 6)) if op == 9 else f"(M{8 + (w >> 27 & 7)},I{8 + (w >> 30 & 7)})"
        return _branch(kind, cond, tgt, mods, comp, w >> 25 & 1)
    if op in (10, 11):                                               # type 11: RTS|RTI, compute
        mods = [k for k, b in (("DB", 26), ("LR", 24)) if w >> b & 1]
        if w >> 38 & 3 or w >> 27 & 63:
            return None
        return _branch("RTS" if op == 10 else "RTI", cond, "", mods, comp, w >> 25 & 1)
    if op == 0x0C:                                                   # type 12: LCNTR = data16, DO
        return f"LCNTR = {_num(w >> 24 & 0xFFFF)}, DO {_num(pc + _sx(w & 0xFFFFFF, 24) * unit)} UNTIL LCE"
    if op == 0x0D:
        return f"LCNTR = {UREG[w >> 32 & 0x7F]}, DO {_num(pc + _sx(w & 0xFFFFFF, 24) * unit)} UNTIL LCE"
    if op == 0x0E:                                                   # type 13: DO UNTIL term
        return f"DO {_num(pc + _sx(w & 0xFFFFFF, 24) * unit)} UNTIL {TERM[cond]}"
    if op == 0x0F:                                                   # type 17: ureg = data32
        return None if w >> 39 & 1 else f"{UREG[w >> 32 & 0x7F]} = {_num(w & 0xFFFFFFFF)}"
    if op >> 2 == 4:                                                 # type 14: ureg <-> DM|PM(addr32)
        return _mem(w >> 41 & 1, _num(w & 0xFFFFFFFF), w >> 40 & 1, UREG[w >> 32 & 0x7F], w >> 39 & 1)
    if op == 0x14:                                                   # type 18: BIT op sreg data32
        b = w >> 37 & 7
        return None if b not in BOP or w >> 36 & 1 else f"BIT {BOP[b]} {_SREG7[w >> 32 & 15]} {_num(w & 0xFFFFFFFF)}"
    if op == 0x16:                                                   # type 19: MODIFY|BITREV(Ia, data32)
        g = w >> 38 & 1
        src, dst = (w >> 32 & 7) + 8 * g, (w >> 32 & 7 ^ w >> 35 & 7) + 8 * g
        f = "BITREV" if w >> 39 & 1 else "MODIFY"
        t = f"{f}(I{src},{_num(_sx(w & 0xFFFFFFFF, 32))})"
        return t if src == dst else f"I{dst} = {t}"
    if op == 0x17:                                                   # type 20: stack operations
        bits = w >> 33 & 0x7F
        if not bits or w & ((1 << 33) - 1) or w >> 40 & 0xFF != 0x17:
            return None
        return ", ".join(STACKOP[6 - k] for k in range(6, -1, -1) if bits >> k & 1)
    if op == 0x18:                                                   # type 25: CJUMP
        if w >> 32 == 0x1804:
            return f"CJUMP {_num(w & 0xFFFFFF)} (DB)"
        if w >> 32 == 0x1844:
            return f"CJUMP {rel(_sx(w & 0xFFFFFF, 24))} (DB)"
        return None
    if op == 0x19:
        return "RFRAME" if w == 0x1900 << 32 else None
    return None


# ------------------------------------------------------------------ VISA
_MARKED = {0x04, 0x08, 0x09} | set(range(0x20, 0x80))   # 32-bit when compute bits 22..16 are 0x3f
_LONG = {0x02, 0x06, 0x07, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x10, 0x11, 0x12, 0x13, 0x14, 0x16, 0x17, 0x18} | \
    set(range(0x80, 0x90)) | set(range(0xA0, 0xC0))


def length(p1, p2=0):
    """Parcels in the VISA instruction whose first two parcels are p1, p2 (None if unknown)."""
    t = p1 >> 8
    if t in (0x00, 0x19):
        return 1 if p1 & 1 else 3
    if t in (0x01, 0x0F):
        return 2 if p1 & 0x80 else 3
    if t in (0x0A, 0x0B) and p1 & 0x80:
        return 1
    if t in _MARKED:
        return 2 if p2 & 0x7F == 0x3F else 3
    if t >> 4 == 0x9:
        lo = p1 & 0x1F
        return 1 if lo & 0x10 else {0: 3, 4: 2, 8: 2}.get(lo)
    if t >> 4 == 0xC:
        return 1
    return 3 if t in _LONG else None


def visa_text(ps, pc):
    """Text of the VISA instruction made of parcels `ps` at short-word address `pc`, or None."""
    p1 = ps[0]
    t = p1 >> 8
    if len(ps) == 3:
        return isa_text(p1 << 32 | ps[1] << 16 | ps[2], pc)
    if len(ps) == 2:
        p2 = ps[1]
        if t == 0x01:                                                # type 2b: compute
            return compute_text((p1 & 0x7F) << 16 | p2) or None
        if t == 0x0F:                                                # type 17b: ureg = data16
            return f"{UREG[p1 & 0x7F]} = {_num(_sx(p2, 16))}"
        if t in _MARKED:                                             # the ISA form with no compute
            return isa_text(p1 << 32 | (p2 & 0xFF80) << 16, pc)
        if p1 & 0x1F == 4:                                           # type 16b: DM|PM(Ia,Mb) = data16
            g = p1 >> 5 & 1
            return _mem(g, f"I{(p1 >> 9 & 7) + 8 * g},M{(p1 >> 6 & 7) + 8 * g}", 1, _num(_sx(p2, 16)))
        if p1 & 0x1F == 8 and not p1 & 0xC0 and not p2 >> 14:       # type 15b: ureg <-> DM|PM(data7, Ia)
            g = p1 >> 5 & 1
            return _mem(g, f"{_sx(p2 & 0x7F, 7)},I{(p1 >> 9 & 7) + 8 * g}", p1 >> 8 & 1, UREG[p2 >> 7 & 0x7F])
        return None
    if t in (0x0A, 0x0B):                                            # type 11c: RTS|RTI
        mods = [k for k, b in (("DB", 6), ("LR", 0)) if p1 >> b & 1]
        return _cond(p1 >> 1 & 31) + ("RTS" if t == 0x0A else "RTI") + (f" ({', '.join(mods)})" if mods else "")
    if p1 == 0x0001:
        return "NOP"
    if p1 == 0x1901:
        return "RFRAME"
    if t >> 4 == 0x9:                                                # type 3c: dreg <-> DM(Ia,Mb)
        return _mem(0, f"I{p1 >> 9 & 7},M{p1 >> 6 & 7}", p1 >> 5 & 1, f"R{p1 & 15}")
    if t >> 4 == 0xC and (p1 >> 8 & 15) in SHORT:                   # type 2c: short compute
        return SHORT[p1 >> 8 & 15].format(n=p1 >> 4 & 15, x=p1 & 15)
    return None


class Insn(NamedTuple):
    addr: int
    parcels: tuple
    text: str


def decode(sw, addr):
    """The VISA instruction at short-word `addr` of parcel map `sw`."""
    p1 = sw[addr]
    n = length(p1, sw.get(addr + 1, 0))
    ps = tuple(sw.get(addr + k, 0) for k in range(n or 1))
    text = visa_text(ps, addr) if n else None
    if text is None:
        return Insn(addr, ps, "?? " + " ".join("%04x" % p for p in ps))
    return Insn(addr, ps, text)


def disasm(sw, start, end):
    """VISA instructions from `start` up to `end`, stopping at a gap in `sw`."""
    out, a = [], start
    while a < end and a in sw:
        ins = decode(sw, a)
        out.append(ins)
        a += len(ins.parcels)
    return out


def disasm_pm(pm, start, end):
    return [Insn(a, (pm[a],), isa_text(pm[a], a) or "?? %012x" % pm[a]) for a in range(start, end) if a in pm]


def fmt(ins, pm=False):
    raw = "%012x" % ins.parcels[0] if pm else " ".join("%04x" % p for p in ins.parcels)
    return f"{ins.addr:#08x}  {raw:<14}  {ins.text};"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--hxf", help="stock .hxf or L6IA (default $HX_STOMP_HXF)")
    ap.add_argument("--pm", action="store_true", help="disassemble 48-bit ISA code in PM")
    ap.add_argument("start", type=lambda s: int(s, 0))
    ap.add_argument("end", nargs="?", default="+64")
    a = ap.parse_args(argv)
    end = a.start + int(a.end[1:], 0) if a.end.startswith("+") else int(a.end, 0)
    img = load(a.hxf)
    lines = disasm_pm(img.pm, a.start, end) if a.pm else disasm(img.sw, a.start, end)
    for ins in lines:
        print(fmt(ins, a.pm))


if __name__ == "__main__":
    main()
