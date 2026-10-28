#!/usr/bin/env python3
"""NAM A2 Lite's kernel: up to three blocks at once, each with its own capture.

usage: nam_multi.py [model.nam] [-o out.asm] [--slots 2|3] [--staging b2|b3] [--check]

The built-in model (Model 0) is model.nam's A2 Lite submodel, or the seeded
placeholder (nam_lite.placeholder) without one. The image needs each block's
SDRAM block: patch_amp.py add-model --sdram-words 0x5000. Run on an HX Stomp:
two blocks, each with its own capture.

The kernel is nam_multi_kernel.asm; this file lays out its memory (layout()),
writes the .equ block and the shared tables (build()), and holds its check:
KernelCheck runs it in ssim with a model of external-port DMA channel 0
(ChainDma: chained DMA as the ADSP-214xx Hardware Reference describes it, with a
timing model), and compares every instance's output with nam_a2.asm
(nam_lite.reference) on that instance's own model, through Pipe (the crossfade
and the tone stack in float32), bit for bit.

Memory (normal words):
  Block 2 after the code: the two staging buffers (a far layer's taps; the model
      load's chunk buffer).
  Block 3 0xe4850..: globals, a report area 0xe4860 (16 words of counters, for
      a probe kernel), saved registers, scratch, the write-back buffer, the TCB chains,
      the job, layer and clear tables, Drive's and the fade's tables, then NSLOTS
      slots: state, tone stack, the model's 1,943 words, its short rings.
  DDR2 0x324500..: the built-in model (laid out as an IR slot), the tone
      stack's table and STOMP_GAIN (10^(STOMP_DBU/20): a loaded model's IR word 5,
      10^(-input_level_dbu/20), x this is its slot's input trim, x Drive).
  Each instance's SDRAM block: its long rings (d >= FAR_D), each with a 16-word
      mirror, HIST (the crossfade's 512 outputs) and the two sentinel words.
"""
import math
import os
import random
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
import nam_lite  # noqa: E402  (the model format, the reference and the shared tables)
import nam_pack  # noqa: E402
import sasm  # noqa: E402
import ssim  # noqa: E402

C = 3
KERNEL, DILATION = nam_pack.KERNEL, nam_pack.DILATION
NL = len(KERNEL)
CODE = 0xC4EF8                    # the kernel's address (48-bit, Block 2's free tail)
NW0 = 0xC0000
B2_END = 0xC8000
B3 = 0xE4850                      # Block 3 from here (0xe4842..0xe4850 left free)
B3_END = 0xE8000
REP = 0xE4860                     # the report area: 16 words of counters
DDR2 = 0x324500
DDR2_END = 0x328000
IR_FLAG, IR_TOP = 0x2AB56E, 0x2ABDED
N_STREAM = nam_lite.N_WEIGHTS + C * (1 + NL)        # 1,943: weights, then the silence state
HIST_N = 512
MAGIC = 0x6E6D6D31                # "nmm1": the report's word 0 and the read chains' sentinel
POLLMAX = 300                     # polls of a chain before it counts as failed
LPOLLMAX = 1000                   # a model load's chunk
BACKOFF_N = 1500                  # calls every instance is silent after a DMA failure
T_MAX = 0x10000
TCB = 6                           # EP TCB: CP, EMEP, EIEP, ICEP, IMEP, IIEP (HRM table 2-22)
TCB_EI, TCB_IC, TCB_II = 2, 3, 5
SB_WORDS = C * 6 * 16             # a staging buffer: [channel][tap][16]
JOB = 8
T_SIZE = 17

DMAC0, EIEP0, EMEP0, ECEP0, IIEP0, IMEP0, ICEP0, CPEP0 = 0x180B, 0x1820, 0x1821, 0x1822, 0x1823, 0x1824, 0x1825, 0x1826
DEN, TRAN, CHEN, DFLSH, DMAS, CHS, EXTS = 1, 2, 4, 0x20, 1 << 20, 1 << 21, 1 << 24
EP0IMSK = 0x2000

# slot state (offsets in a slot)
S = dict(S_OWNER=0, S_LAST=1, S_INIT=2, S_SIG=3, S_GAIN=4, S_G1=5, S_MG=6, S_MR=7, S_HW=8, S_T=9,
         S_SEQ=10, S_HHW=11, S_SDR=12, S_FRESH=13, S_EQDIRTY=14, S_TRIM=15, S_EQIDX=16, S_EQC=20, S_EQS=40, S_LW=48)
S_STREAM = 72
ST = dict(ST_RECH=0, ST_HEAD=3, ST_SCALE=52, ST_SIL=nam_lite.N_WEIGHTS)
REPW = dict(R_MAGIC=0, R_CALLS=1, R_TIMEOUTS=2, R_SKIPS=3, R_LOADS=4, R_CLAIMS=5, R_OWNERS=6, R_POLLS=9,
            R_MAXPOLLS=10, R_BACKOFF=11, R_NOSLOT=12, R_NOSDR=13, R_DMAC=14, R_ICEP=15)
T = dict(T_RB=0, T_STRIDE=1, T_L=2, T_LW=3, T_K=4, T_S=5, T_WT=6, T_KD=7, T_FAR=8, T_RPOS=9, T_KS=10,
         T_D=11, T_SB=12, T_OB=13, T_WA=14, T_SIL=15, T_NW=16)
J = dict(J_TYPE=0, J_READY=1, J_ROW=2, J_CHAIN=3, J_FLAG=4, J_CP=5, J_N=6)
P = dict(P_SLOT=12, P_SEEN=13, P_MET=14, P_PHASE=15)   # P_PHASE: the Polarity knob (patch_amp pid 15)
FAR_D = {2: 41, 3: 17}            # with 3 slots the d = 17 rings go to SDRAM too, to fit


def rup16(x):
    return -(-x // 16) * 16


def stream_offsets():
    """Where each layer's weights start in the model stream (nam_lite.stream order)."""
    o, out = 3 + 49 + 1, []
    for k in KERNEL:
        out.append(o)
        o += 2 * C + k * C * C + 4 * C
    assert o == nam_lite.N_WEIGHTS
    return out


def code_size():
    src = open(os.path.join(here, "nam_multi_kernel.asm")).read()
    secs, _ = sasm.assemble(src.replace("// EQUS (nam_multi.py puts the layout here)\n",
                                        equs({k: 0 for k in names()})), "nam_multi_kernel.asm")
    return sum(len(s.words) for s in secs if s.kind == "pm")


def names():
    return list(S) + list(ST) + list(REPW) + list(T) + list(J) + list(P) + [
        "SAVE", "REP", "G_SDR", "G_JOBS", "G_LEVEL", "J_NEXT", "J_BUSY", "J_DONE", "EVENTS", "DMA_FAIL", "J_CHKADR",
        "J_CHKVAL", "FLAGL", "SLOTTAB", "NSLOTS", "IN", "X", "HS", "TABLE", "NLAYERS", "JOBS", "NJOBS", "CLR",
        "NCLR", "DRIVE_TAB", "FADE_TAB", "EQ_TAB", "STOMP_GAIN", "BUILTIN_TOP", "LBUF", "LBUF_N", "LCH", "LCH_CP",
        "FARTAB", "WADDR", "NFAR", "S_STREAM", "S_HB0", "S_HB1", "S_HB2", "HIST_OFF", "SENT_OFF", "SENT2_OFF",
        "SDR_NEED", "MAGIC", "POLLMAX", "LPOLLMAX", "BACKOFF_N", "T_MAX", "N_STREAM", "KM1", "T_SIZE",
        "TCB_EI", "TCB_IC", "TCB_II", "IR_FLAG", "IR_TOP", "DMAC0", "EIEP0", "EMEP0", "ICEP0", "IIEP0", "IMEP0",
        "CPEP0", "DFLSH", "DEN_CHEN", "TRAN", "BUSYM", "EXTSM", "EP0IMSK", "HXK_ENTRY_INST", "HXK_INST_SDRAM",
        "HXK_INST_SDRAM_END"]


def equs(v):
    return "".join(f".equ {k}, {v[k]:#x}\n" for k in names())


class Layout:
    """Every address of the kernel's memory, for `slots` slots."""

    def __init__(self, slots=3, n_code=None, backoff=BACKOFF_N, staging="b2"):
        """staging: "b2" puts the staging buffers in Block 2 after the code (the far layers'
        tap reads then never meet their weights' block); "b3" in Block 3, which leaves
        Block 2 free after the code for another kernel."""
        self.slots, self.far_d, self.staging = slots, FAR_D[slots], staging
        self.n_code = code_size() if n_code is None else n_code
        n = self.n_code
        self.b2_data = NW0 + (CODE - NW0) * 3 // 2 + -(-(n + (n & 1)) * 3 // 2)
        self.far = [i for i, (k, d) in enumerate(zip(KERNEL, DILATION)) if k == 6 and d >= self.far_d]
        F = self.nfar = len(self.far)
        self.groups = []                  # far layers next to each other: one write-back each
        for j, i in enumerate(self.far):
            if j and i == self.far[j - 1] + 1:
                self.groups[-1].append(j)
            else:
                self.groups.append([j])
        # the job queue: each far layer's taps (R), and after the first R of a group the
        # previous group's write-back (W), the last group's at the end
        self.queue = []
        first = {grp[0]: g for g, grp in enumerate(self.groups)}
        for j in range(F):
            self.queue.append(("R", j))
            if j in first and first[j] > 0:
                self.queue.append(("W", first[j] - 1))
        self.queue.append(("W", len(self.groups) - 1))
        self.ring = [(k - 1) * d + 16 for k, d in zip(KERNEL, DILATION)]
        v = {k: x for k, x in list(S.items()) + list(ST.items()) + list(REPW.items()) + list(T.items())
             + list(J.items()) + list(P.items())}
        # Block 2: the staging buffers, contiguous (they are the load's chunk buffer too)
        a = self.b2_data
        if staging == "b2" and a + 2 * SB_WORDS <= B2_END:
            self.sb = [a, a + SB_WORDS]
            self.b2_to = a + 2 * SB_WORDS
            b3 = None
        else:
            self.b2_to = a
            b3 = 2 * SB_WORDS
        # Block 3
        g = dict(G_SDR=B3, G_LEVEL=B3 + 1, J_NEXT=B3 + 2, J_BUSY=B3 + 3, J_DONE=B3 + 4, EVENTS=B3 + 5,
                 DMA_FAIL=B3 + 6, J_CHKADR=B3 + 7, J_CHKVAL=B3 + 8, FLAGL=B3 + 9)
        self.flags = [B3 + 10, B3 + 11]
        g["G_JOBS"] = B3 + 12
        assert B3 + 13 <= REP
        v.update(g)
        a = REP + 16
        alloc = {}

        def take(name, n):
            nonlocal a
            alloc[name] = a
            a += n
            return alloc[name]

        take("SAVE", 64)
        take("SLOTTAB", slots)
        take("IN", 16)
        take("X", 48)
        take("HS", 48)
        if b3:
            take("SB", b3)
            self.sb = [alloc["SB"], alloc["SB"] + SB_WORDS]
        take("OUTBUF", 48 * F)
        take("RCH0", 16 * TCB)
        take("RCH1", 16 * TCB)
        self.wch = [take(f"WCH{g}", (3 * len(grp) + 1) * TCB) for g, grp in enumerate(self.groups)]
        take("LCH", 2 * TCB)
        take("JOBS", (F + len(self.groups)) * JOB)
        take("TABLE", NL * T_SIZE)
        take("FARTAB", F)
        take("WADDR", F)
        near = [i for i in range(NL) if i not in self.far]
        self.nclr = 3 + 3 * len(near)
        take("CLR", 3 * self.nclr)
        take("DRIVE_TAB", 101)
        take("FADE_TAB", 18)
        self.alloc = alloc
        # the slots
        self.hb = [S_STREAM + N_STREAM + 32 * j for j in range(C)]
        o = self.hb[-1] + 32
        self.near_off = {}
        for i in near:
            self.near_off[i] = o
            o += C * (self.ring[i] + 1)
        self.slot_size = o
        self.slot = [a + s * o for s in range(slots)]
        a += slots * o
        self.b3_to = a
        if a > B3_END:
            raise SystemExit(f"{slots} slots do not fit: Block 3 to {a:#x} (> {B3_END:#x})")
        # each instance's SDRAM block: the far rings (L' + a 16-word mirror each), HIST, sentinels
        self.lp = {i: rup16(self.ring[i]) for i in self.far}
        o, self.far_off = 0, {}
        for i in self.far:
            self.far_off[i] = o
            o += C * (self.lp[i] + 16)
        self.hist_off = o
        self.sent_off = o + HIST_N
        self.sdr_need = self.sent_off + 2
        # DDR2 (shared): the built-in model as an IR slot, the tone stack's table
        self.builtin_top = DDR2 + 2047
        self.eq_tab = DDR2 + 2048
        self.stomp_gain = self.eq_tab + 4 * 101 * 5      # 10^(STOMP_DBU/20) (nam_lite.py)
        self.ddr2_to = self.stomp_gain + 1
        assert self.ddr2_to <= DDR2_END
        v.update(SAVE=alloc["SAVE"], REP=REP, SLOTTAB=alloc["SLOTTAB"], NSLOTS=slots, IN=alloc["IN"], X=alloc["X"],
                 HS=alloc["HS"], TABLE=alloc["TABLE"], NLAYERS=NL, JOBS=alloc["JOBS"], NJOBS=F + len(self.groups), CLR=alloc["CLR"],
                 NCLR=self.nclr, DRIVE_TAB=alloc["DRIVE_TAB"], FADE_TAB=alloc["FADE_TAB"], EQ_TAB=self.eq_tab,
                 STOMP_GAIN=self.stomp_gain,
                 BUILTIN_TOP=self.builtin_top, LBUF=self.sb[0], LBUF_N=2 * SB_WORDS, LCH=alloc["LCH"],
                 LCH_CP=(alloc["LCH"] + TCB_II) & 0x7FFFF, FARTAB=alloc["FARTAB"],
                 WADDR=alloc["WADDR"], NFAR=F, S_STREAM=S_STREAM, S_HB0=self.hb[0], S_HB1=self.hb[1],
                 S_HB2=self.hb[2], HIST_OFF=self.hist_off, SENT_OFF=self.sent_off, SENT2_OFF=self.sent_off + 1,
                 SDR_NEED=self.sdr_need, MAGIC=MAGIC, POLLMAX=POLLMAX, LPOLLMAX=LPOLLMAX, BACKOFF_N=backoff,
                 T_MAX=T_MAX, N_STREAM=N_STREAM, KM1=5, T_SIZE=T_SIZE, TCB_EI=TCB_EI, TCB_IC=TCB_IC,
                 TCB_II=TCB_II, IR_FLAG=IR_FLAG, IR_TOP=IR_TOP, DMAC0=DMAC0, EIEP0=EIEP0, EMEP0=EMEP0,
                 ICEP0=ICEP0, IIEP0=IIEP0, IMEP0=IMEP0, CPEP0=CPEP0, DFLSH=DFLSH, DEN_CHEN=DEN | CHEN, TRAN=TRAN,
                 BUSYM=DEN | DMAS | CHS | EXTS, EXTSM=EXTS, EP0IMSK=EP0IMSK, HXK_ENTRY_INST=2, HXK_INST_SDRAM=6,
                 HXK_INST_SDRAM_END=7)
        self.v = v

    def sdram_words(self):
        return -(-self.sdr_need // 0x400) * 0x400

    # ------------------------------------------------------------ the tables
    def words(self, w):
        """{address: word}: everything the kernel finds in memory at boot."""
        v, al, F = self.v, self.alloc, self.nfar
        mem = {}

        def put(a, vals):
            for i, x in enumerate(vals):
                assert a + i not in mem, hex(a + i)
                mem[a + i] = x & 0xFFFFFFFF

        put(B3, [0] * 13)
        put(self.sb[0], [0] * (2 * SB_WORDS))                # static: part of the boot-loaded sections
        put(REP, [MAGIC] + [0] * 15)
        put(al["SLOTTAB"], self.slot)
        for s in self.slot:
            put(s + S["S_OWNER"], [0])                      # free (the rest is set when it is taken)
        wo = stream_offsets()
        tab = []
        rpos = {self.far[j]: q for q, (t, j) in enumerate(self.queue) if t == "R"}
        for i, (k, d) in enumerate(zip(KERNEL, DILATION)):
            row = [0] * T_SIZE
            row[T["T_LW"]] = S["S_LW"] + i
            row[T["T_K"]] = k
            row[T["T_WT"]] = S_STREAM + wo[i]
            row[T["T_KD"]] = -(k - 1) * d
            row[T["T_D"]] = d
            row[T["T_NW"]] = -(2 * C + k * C * C + 4 * C)
            if i in self.far:
                j = self.far.index(i)
                L = self.lp[i]
                row[T["T_RB"]] = self.far_off[i]
                row[T["T_STRIDE"]] = L + 16
                row[T["T_L"]] = L
                row[T["T_S"]] = 16
                row[T["T_KS"]] = -(k - 1) * 16
                row[T["T_FAR"]] = j + 1
                row[T["T_RPOS"]] = rpos[i]
                row[T["T_SB"]] = self.sb[j % 2]
                row[T["T_OB"]] = al["OUTBUF"] + 48 * j
                row[T["T_WA"]] = al["WADDR"] + j
                row[T["T_SIL"]] = S_STREAM + nam_lite.N_WEIGHTS + C + C * i
            else:
                L = self.ring[i]
                row[T["T_RB"]] = self.near_off[i]
                row[T["T_STRIDE"]] = L + 1
                row[T["T_L"]] = L
                row[T["T_S"]] = d
                row[T["T_KS"]] = -(k - 1) * d
                steps = [-(k - 1) * d, 2 - 2 * d, 2 - d]
                assert all(abs(x) < L for x in steps), "a step as long as the ring"
            tab += row
        put(al["TABLE"], tab)
        put(al["FARTAB"], [al["TABLE"] + T_SIZE * i for i in self.far])
        put(al["WADDR"], [0] * F)
        clr = [(self.hb[c], 32, c) for c in range(C)]
        for i in sorted(self.near_off):
            for c in range(C):
                clr.append((self.near_off[i] + c * (self.ring[i] + 1), self.ring[i] + 1, C + C * i + c))
        assert len(clr) == self.nclr
        put(al["CLR"], [x for r in clr for x in r])
        put(al["DRIVE_TAB"], [nam_pack.f2b(10.0 ** ((step - 50) * 0.4 / 20)) for step in range(101)])
        put(al["FADE_TAB"], nam_lite.fade_table())

        def tcb(cp, ic, ii):
            return [cp & 0x7FFFF if cp else 0, 1, 0, ic, 1, ii]

        for b, ch in enumerate((al["RCH0"], al["RCH1"])):
            t = []
            for n in range(15):
                tt, c = divmod(n, 3)
                t += tcb(ch + TCB * (n + 1) + TCB_II, 16, self.sb[b] + 96 * c + 16 * tt)
            t += tcb(0, 1, self.flags[b])
            put(ch, t)
        for g, grp in enumerate(self.groups):
            t = []
            for m in range(3 * len(grp)):
                jj, c = divmod(m, 3)
                t += tcb(self.wch[g] + TCB * (m + 1) + TCB_II, 16, al["OUTBUF"] + 48 * grp[jj] + 16 * c)
            t += tcb(0, 1, 0)
            put(self.wch[g], t)
        put(al["LCH"], tcb(al["LCH"] + TCB + TCB_II, 0, self.sb[0]) + tcb(0, 1, v["FLAGL"]))
        jobs = []
        for t_, j in self.queue:
            if t_ == "R":
                ch = (al["RCH0"], al["RCH1"])[j % 2]
                jobs += [0, 0 if j < 2 else 2 * j - 2, al["TABLE"] + T_SIZE * self.far[j], ch, self.flags[j % 2],
                         (ch + TCB_II) & 0x7FFFF, 0, 0]
            else:
                grp = self.groups[j]
                jobs += [1, 2 * grp[-1] + 1, al["FARTAB"] + grp[0], self.wch[j], al["WADDR"] + grp[0],
                         (self.wch[j] + TCB_II) & 0x7FFFF, len(grp), 0]
        put(al["JOBS"], jobs)
        # DDR2: the built-in model, top-down as in an IR slot; the tone stack's table
        for k, x in enumerate(nam_lite.ir_samples(w)):
            mem[self.builtin_top - k] = x
        put(self.eq_tab, nam_lite.eq_table())
        put(self.stomp_gain, [nam_pack.f2b(10.0 ** (nam_lite.STOMP_DBU / 20))])
        return mem

    def claims(self):
        """[start, end) ranges the kernel writes at run time (module.toml [[memory]] and its
        static sections must cover them)."""
        sb = (self.sb[0], self.sb[0] + 2 * SB_WORDS)
        return [sb, (B3, self.b3_to), (DDR2, self.ddr2_to), (DMAC0, DMAC0 + 1), (EIEP0, CPEP0 + 1)]

    def report(self):
        return {"slots": self.slots, "far layers": len(self.far), "far d >=": self.far_d,
                "code instructions": self.n_code, "staging": f"{self.sb[0]:#x}..{self.sb[0] + 2 * SB_WORDS:#x}",
                "block 2 free after": f"{self.b2_to:#x} ({B2_END - self.b2_to} words)",
                "block 3": f"{B3:#x}..{self.b3_to:#x} ({B3_END - self.b3_to} words free)",
                "slot words": self.slot_size, "sdram words needed": self.sdr_need,
                "DDR2": f"{DDR2:#x}..{self.ddr2_to:#x}"}


def build(w, slots=3, backoff=BACKOFF_N, staging="b2"):
    """(asm, layout): the kernel with its addresses and tables."""
    lay = Layout(slots, backoff=backoff, staging=staging)
    src = open(os.path.join(here, "nam_multi_kernel.asm")).read()
    src = src.replace("// EQUS (nam_multi.py puts the layout here)\n", equs(lay.v))
    secs, _ = sasm.assemble(src, "nam_multi_kernel.asm")
    assert sum(len(s.words) for s in secs if s.kind == "pm") == lay.n_code
    mem = lay.words(w)
    lines = ["", "// ---- tables, written by nam_multi.py ----"]
    last = None
    for a in sorted(mem):
        if a != (last or 0) + 1:
            lines.append(f".section dm {a:#x}")
        lines.append(f"    .word {mem[a]:#010x}")
        last = a
    return src + "\n".join(lines) + "\n", lay


# ---------------------------------------------------------------- the DMA model
class ChainDma:
    """External-port DMA channel 0 as the ADSP-214xx Hardware Reference describes it
    (pp. 2-19, 3-100..3-124), for ssim, which has no DMA:

    - writing DMAC0 with DEN | CHEN, then CPEP0 with a TCB address, starts a chain; a
      TCB is 6 words, and the chain pointer holds the address of its last (IIEP), the
      DMA loading it downwards (19 bits + 0x80000); CP = 0 ends the chain;
    - each TCB moves ICEP words, direction TRAN (1: internal -> external), modifiers
      IMEP and EMEP; a standard DMA (DEN without CHEN) moves the registers' block;
    - timing: a chain starts `start` cycles after CPEP is written; a TCB takes
      `tcb + word * ICEP` cycles; its words land when it ends (an internal
      destination reads POISON until then, so a kernel that reads early fails);
    - DMAC0 reads DMAS while the chain runs (and EXTS for writes); clearing DEN stops it.

    mode: "ok"; "stall" (a chain never ends); "nocopy" (ends, moves nothing).
    `cycles_busy` sums the time the channel was busy (the DMA time of the calls).
    """
    POISON = 0x7FC0BAD0

    def __init__(self, sim, mode="ok", start=20, tcb=40, word=2.1):
        self.sim, self.mode, self.c_start, self.c_tcb, self.c_word = sim, mode, start, tcb, word
        self.rd0, self.wr0 = sim.rd, sim.wr
        sim.rd, sim.wr = self.rd, self.wr
        self.active, self.due, self.cur, self.t0 = False, None, None, 0
        self.chains, self.writes, self.cycles_busy, self.words, self.tcbs = [], [], 0, 0, 0
        self.log = []                     # (to external, external, internal, count, emep, imep) per TCB

    def _int(self, a):
        return 0x80000 | (a & 0x7FFFF)

    def _load(self, cp, now):
        p = self._int(cp)
        r = self.rd0
        t = dict(ii=self._int(r(p)), im=r(p - 1), ic=r(p - 2) & 0xFFFF or 0x10000, ei=r(p - 3), em=r(p - 4),
                 cp=r(p - 5) & 0x7FFFF)
        for reg, k in ((IIEP0, "ii"), (IMEP0, "im"), (ICEP0, "ic"), (EIEP0, "ei"), (EMEP0, "em"), (CPEP0, "cp")):
            self.wr0(reg, t[k])
        self.wr0(ECEP0, t["ic"])
        self.cur = t
        self.tcbs += 1
        self.log.append((self.tran, t["ei"], t["ii"], t["ic"], s32(t["em"]), s32(t["im"])))
        if not self.tran:
            for k in range(t["ic"]):
                self.wr0(t["ii"] + k * s32(t["im"]), self.POISON)
        self.due = math.inf if self.mode == "stall" else now + self.c_tcb + self.c_word * t["ic"]

    def _finish(self):
        t = self.cur
        if self.mode != "nocopy":
            for k in range(t["ic"]):
                ia, ea = t["ii"] + k * s32(t["im"]), t["ei"] + k * s32(t["em"])
                src, dst = (ia, ea) if self.tran else (ea, ia)
                self.wr0(dst, self.rd0(src))
        self.words += t["ic"]
        self.wr0(ICEP0, 0)
        self.wr0(ECEP0, 0)
        now = self.due
        if t["cp"] and self.chained:
            self._load(t["cp"], now)
        else:
            self.active = False
            self.cycles_busy += now - self.t0
            self.wr0(DMAC0, self.rd0(DMAC0) & ~(DMAS | EXTS | CHS))

    def advance(self):
        while self.active and self.sim.cycles >= self.due:
            self._finish()

    def wr(self, a, v):
        self.advance()
        self.wr0(a, v)
        a &= 0xFFFFFFFF
        if a == DMAC0 or EIEP0 <= a <= CPEP0:
            self.writes.append((a, v & 0xFFFFFFFF))
        if a == ICEP0:
            self.wr0(ECEP0, v)
        if a == DMAC0:
            if self.active and not v & DEN:
                self.active = False                       # switched off mid-chain
                self.cycles_busy += self.sim.cycles - self.t0
            elif v & DEN and not v & CHEN and not self.active:
                self._start(v, None)
        if a == CPEP0 and v & 0x7FFFF and not self.active:
            ctl = self.rd0(DMAC0)
            if ctl & DEN and ctl & CHEN:
                self._start(ctl, v)

    def _start(self, ctl, cp):
        self.tran, self.chained, self.active = bool(ctl & TRAN), cp is not None, True
        self.t0 = self.sim.cycles
        self.wr0(DMAC0, ctl | DMAS | (EXTS if self.tran else 0))
        self.chains.append(dict(ctl=ctl, cp=cp, at=self.sim.cycles))
        now = self.sim.cycles + self.c_start
        if cp is None:
            r = self.rd0
            self.cur = dict(ii=self._int(r(IIEP0)), im=r(IMEP0), ic=r(ICEP0) & 0xFFFF or 0x10000, ei=r(EIEP0),
                            em=r(EMEP0), cp=0)
            self.due = math.inf if self.mode == "stall" else now + self.c_word * self.cur["ic"]
        else:
            self._load(cp, now)

    def rd(self, a):
        if self.active and self.sim.cycles >= self.due:
            self.advance()
        return self.rd0(a)


def s32(v):
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


# ---------------------------------------------------------------- what an instance plays
def f32(x):
    return ssim.b2f(ssim.f2b(x))


class Pipe:
    """The kernel after the model, in float32 op for op, per instance: the crossfade
    (the model's output x its fade-in gain, plus, while the tail plays, HIST played
    backwards x the tail's gain; into HIST) and the tone stack. nam_lite.Pipe, except
    that a block whose tail gain starts at 0 adds no tail (HIST is in SDRAM: it is
    not read then), and a fresh slot's first model has no tail."""

    def __init__(self):
        self.tab = [ssim.b2f(v) for v in nam_lite.fade_table()]
        self.hist = [0] * HIST_N
        self.hw = self.mr = self.mg = self.gain = 0
        self.fresh = True
        self.co = [[1.0, 0.0, 0.0, 0.0, 0.0] for _ in range(4)]
        self.st = [[0.0, 0.0] for _ in range(4)]

    def knobs(self, knobs):
        tab = nam_lite.eq_table()
        self.co = []
        for band, k in enumerate(knobs):
            i = min(100, max(0, int(f32(f32(f32(k) * 100.0) + 0.5))))
            self.co.append([ssim.b2f(v) for v in tab[(band * 101 + i) * 5: (band * 101 + i) * 5 + 5]])

    def cut(self):
        self.mg = 0 if self.fresh else 17
        self.mr, self.gain, self.fresh = (self.hw - 1) % HIST_N, 0, False

    def block(self, words):
        f, tab = f32, self.tab
        g1 = 0 if words is None else min(16, self.gain + 1)
        words = words or [0] * 16
        tail = self.mg > 0
        g, m1 = tab[self.gain], max(0, self.mg - 1)
        dg = f(f(tab[g1] - g) * 0.0625)
        m = tab[self.mg]
        dm = f(f(tab[m1] - m) * 0.0625)
        out = []
        for wd in words:
            x = f(ssim.b2f(wd) * g)
            if tail:
                x = f(x + f(ssim.b2f(self.hist[self.mr]) * m))
                self.mr = (self.mr - 1) % HIST_N
            self.hist[self.hw] = ssim.f2b(x)
            self.hw = (self.hw + 1) % HIST_N
            for (b0, b1, b2, na1, na2), z in zip(self.co, self.st):
                y = f(f(b0 * x) + z[0])
                z[0] = f(f(f(b1 * x) + f(na1 * y)) + z[1])
                z[1] = f(f(b2 * x) + f(na2 * y))
                x = y
            out.append(ssim.f2b(x))
            g, m = f(g + dg), f(m + dm)
        self.gain, self.mg = g1, m1
        return out


def drive_gain(k):
    """DRIVE_TAB's gain for knob value k, as the kernel picks the step."""
    step = min(100, max(0, int(f32(f32(f32(k) * 100.0) + 0.5))))
    return ssim.b2f(nam_pack.f2b(10.0 ** ((step - 50) * 0.4 / 20)))


def level(k):
    k = f32(k)
    return f32(f32(k * k) * 4.0)


# ---------------------------------------------------------------- the check
class CheckFailed(Exception):
    pass


MAX_STEADY = 33000                # instructions a steady block, at most (KernelCheck.cycle_budget)


class Inst:
    """An instance as the stock graph makes one: its DM block (I0, 145 words zeroed,
    DM(3) = 1), PM block (I8), call-list entry (I3) -> instance struct -> SDRAM block
    (stale: random words), and what it should play."""

    def __init__(self, rig, name, i0, i8, entry, sdram, sdram_words):
        self.rig, self.name, self.i0, self.i8, self.entry, self.sdram = rig, name, i0, i8, entry, sdram
        sim = rig.sim
        for k in range(145):
            sim.wr(i0 + k, 0)
        sim.wr(i0 + 3, 1)
        for k in range(13):
            sim.wr(i8 + k, 0)
        sim.wr(entry + 2, entry + 0x10)
        sim.wr(entry + 0x10 + 6, sdram)
        sim.wr(entry + 0x10 + 7, sdram + sdram_words)
        rnd = rig.rnd
        for k in range(sdram_words):
            sim.dm[sdram + k] = rnd.getrandbits(32)
        self.pipe = Pipe()
        self.knobs(drive=0.5, vol=0.5, model=0, eq=nam_lite.EQ_TEST)
        self.polarity = 0

    def knobs(self, drive=None, vol=None, model=None, eq=None, polarity=None):
        sim = self.rig.sim
        if polarity is not None:            # the raw word: 0/1, or a float's bits
            self.polarity = polarity
            sim.wr(self.i0 + P["P_PHASE"], polarity)
        if drive is not None:
            self.drive = drive
            sim.wr(self.i0 + 5, ssim.f2b(drive))
        if vol is not None:
            self.vol = vol
            sim.wr(self.i0 + 6, ssim.f2b(vol))
        if model is not None:
            self.model = model
            sim.wr(self.i0 + 7, model if isinstance(model, int) else ssim.f2b(model))
        if eq is not None:
            self.eq = eq
            for j, k in enumerate(eq):
                sim.wr(self.i0 + 8 + j, ssim.f2b(k))
        sim.wr(self.i0 + 3, 1)

    def call(self, block, label):
        return self.rig.call(self, block, label)


class Rig:
    """The kernel in ssim with the DMA model, and instances to call."""

    def __init__(self, asm, lay, seed=1, **dma):
        secs, self.syms = sasm.assemble(asm, "nam_multi.asm")
        self.lay = lay
        sim = self.sim = ssim.Sim()
        sim.strict_cbufen = True
        sim.load(secs)
        rnd = self.rnd = random.Random(seed)
        static = set()
        for s in secs:
            if s.kind == "dm":
                static.update(range(s.addr, s.addr + len(s.words)))
        for a, b in lay.claims()[1:2]:
            for x in range(a, b):
                if x not in static:
                    sim.dm[x] = rnd.getrandbits(32)
        sim.dm[DMAC0] = 0
        self.dma = ChainDma(sim, **dma)
        self.keep = [c for c in range(0x10, 0x50) if c not in (0x11, 0x12, 0x13, 0x1F)]
        self.n, self.foreign = 0, False
        self.cycles = []                      # (label, instructions)
        self.allowed = [(a, b) for a, b in lay.claims()]

    def inst(self, name, k):
        """Instance k (0..7): blocks far apart, an SDRAM block of the manifest's size."""
        return Inst(self, name, 0xB3000 + 0x400 * k, 0x91000 + 0x200 * k, 0xB6000 + 0x40 * k,
                    0x400000 + 0x10000 * k, self.lay.sdram_words())

    def call(self, inst, block, label):
        sim, rnd = self.sim, self.rnd
        BI, BO = 0xB8000, 0xB8100
        for k in range(16):
            sim.wr(BI + k, block[k])
        for r in range(16):
            sim.setR(r, rnd.getrandbits(32))
            sim.alt[r] = rnd.getrandbits(32)
        for c in self.keep + [0x1F]:
            if 0x30 <= c < 0x40:
                sim.set(c, rnd.getrandbits(8) or 1)
            elif c >= 0x40:
                sim.u[c] = rnd.getrandbits(32) & 0xFFFFF
            elif c not in (0x10, 0x18):
                sim.set(c, rnd.getrandbits(32) & 0xFFFFF)
        for b, v in ((0x40, inst.i0), (0x48, inst.i8), (0x41, BI), (0x42, BO)):
            sim.set(b, v)
        sim.set(0x13, inst.entry)
        sim.u[ssim.U_MODE1] |= 0x1000000
        mode1 = sim.u[ssim.U_MODE1]
        before = ([sim.R(r) for r in range(16)], list(sim.alt[:16]), {c: sim.get(c) for c in self.keep})
        cyc = sim.call(self.syms["CUSTOM_AMP_ENTRY"], limit=2_000_000)
        self.dma.advance()
        self.n += 1
        self.cycles.append((label, cyc))
        bad = [f"R{r}" for r in range(16) if sim.R(r) != before[0][r]]
        bad += [f"S{r}" for r in range(16) if sim.alt[r] != before[1][r]]
        bad += [f"{c:#x}" for c in self.keep
                if sim.get(c) != before[2][c] and not (0x30 <= c < 0x40 and c != 0x37 and sim.get(c) == 0)]
        if sim.u[ssim.U_MODE1] != mode1:
            bad.append("MODE1")
        if bad:
            raise CheckFailed(f"{label}: registers changed: {bad}")
        if sim.loops or sim.pcstk:
            raise CheckFailed(f"{label}: returns with the loop or PC stack not empty")
        if self.dma.active:
            raise CheckFailed(f"{label}: returns with a DMA running")
        if sim.rd(DMAC0) & DEN and not self.foreign:
            raise CheckFailed(f"{label}: returns with DMAC0 enabled")
        self.check_dma(inst, label)
        return [sim.rd(BO + k) for k in range(16)]

    def rep(self):
        return [self.sim.rd(REP + k) for k in range(16)]

    def check_dma(self, inst, label):
        """Every word a TCB moved: external words in the calling instance's SDRAM block
        (or, read only, the User IR slots and the built-in model), internal words in the
        module's memory."""
        sd = (inst.sdram, inst.sdram + self.lay.sdram_words())
        ir = (IR_TOP - 0x800 + 1, IR_TOP + 128 * 0x800)
        bi = (self.lay.builtin_top - 2047, self.lay.builtin_top + 1)
        for out, ei, ii, n, em, im in self.dma.log:
            e0, e1 = sorted((ei, ei + (n - 1) * em))
            i0, i1 = sorted((ii, ii + (n - 1) * im))
            ok_e = sd[0] <= e0 and e1 < sd[1] or not out and any(a <= e0 and e1 < b for a, b in (ir, bi))
            ok_i = any(a <= i0 and i1 < b for a, b in self.allowed[:2])
            if not (ok_e and ok_i):
                raise CheckFailed(f"{label}: a TCB {'to' if out else 'from'} {ei:#x} ({n} words) / internal "
                                  f"{ii:#x} is outside the instance's memory")
        self.dma.log.clear()


def set_ir(sim, slot, words):
    """User IR slot `slot` (1..128) holds `words` (2048), top-down, and is flagged loaded."""
    top = IR_TOP + (slot - 1) * 0x800
    for k, v in enumerate(words):
        sim.wr(top - k, v)
    sim.wr(IR_FLAG + slot - 1, 1)


def variant(w, seed):
    r = random.Random(seed)
    return [ssim.b2f(nam_pack.f2b(x * (1 + 0.1 * r.uniform(-1, 1)))) for x in w]


class Player:
    """What one instance should play from its model's load on: the reference on
    its input (x its drive gain x its model's input trim), x its level, through its Pipe."""

    def __init__(self, inst, w, sig_blocks, trim=1.0):
        self.inst, self.w = inst, w
        g = f32(drive_gain(inst.drive) * trim)
        lv = level(inst.vol)
        ins = [f32(ssim.b2f(v) * g) for blk in sig_blocks for v in blk]
        ref = nam_lite.reference(w, ins)
        self.words = [ssim.f2b(f32(ssim.b2f(v) * lv)) for v in ref]
        self.b = 0

    def next(self):
        out = self.words[16 * self.b: 16 * self.b + 16]
        self.b += 1
        if self.inst.polarity:              # Inverted: x -level, exactly the sign flipped
            out = [v ^ 0x80000000 for v in out]
        return out


class KernelCheck:
    """The steps, in order; each carries on from the state the ones before left."""

    STEPS = ("silence_fixed_point", "two_models_load", "two_models_play", "model_change_crossfades",
             "polarity_inverts", "cab_ir_is_silent", "back_to_builtin", "third_and_fourth", "takeover", "recreated",
             "dma_timeout", "busy_channel", "cycle_budget")

    def __init__(self, asm, lay, w, nblk=8, **dma):
        self.lay, self.w, self.nblk = lay, w, nblk
        self.rig = Rig(asm, lay, **dma)
        self.w2, self.w3, self.w4 = variant(w, 2), variant(w, 3), variant(w, 4)
        rnd = random.Random(7)
        self.sigs = {}

        def sig(name, n):
            if name not in self.sigs:
                ph = rnd.uniform(0, 6)
                x = [0.3 * math.sin(0.031 * i + ph) * math.exp(-i / 400) + 0.1 * math.sin(0.41 * i + ph)
                     + (0.5 if i == 7 else 0) for i in range(16 * n)]
                self.sigs[name] = [[ssim.f2b(v) for v in x[16 * b: 16 * b + 16]] for b in range(n)]
            return self.sigs[name]
        self.sig = sig
        sim = self.rig.sim
        # each slot model's capture at its own input level (IR word 5): the kernel trims
        # each block's input by STOMP_DBU - that; the built-in model (no level) by nothing
        self.dbu = {id(self.w2): 15.0, id(self.w3): 6.0, id(self.w4): None}
        set_ir(sim, 3, nam_lite.ir_samples(self.w2, 15.0))
        set_ir(sim, 7, nam_lite.ir_samples(self.w3, 6.0))
        set_ir(sim, 9, nam_lite.ir_samples(self.w4, None))
        cab = [ssim.f2b(rnd.uniform(-1, 1) * math.exp(-k / 300)) for k in range(2048)]
        set_ir(sim, 5, cab)
        self.steady = []                  # (label, instructions) of steady blocks
        self.loads = []                   # (label, instructions) of blocks that load or start a slot
        self.zero = [0] * 16

    def run(self):
        for name in self.STEPS:
            getattr(self, name)()

    # helpers
    def expect(self, inst, block, label, words, kind="steady"):
        got = inst.call(block, label)
        want = inst.pipe.block(words)
        cyc = self.rig.cycles[-1]
        (self.steady if kind == "steady" else self.loads).append(cyc)
        if got != want:
            n = sum(a != b for a, b in zip(got, want))
            err = max(abs(ssim.b2f(a) - ssim.b2f(b)) for a, b in zip(got, want))
            raise CheckFailed(f"{label}: {n} of 16 samples differ from the reference, by up to {err:.3g}")
        return got

    def start(self, inst, w, sig, label):
        """inst's next call loads its model (crossfade: the tail alone), then it plays
        w from the silence state on sig, fading in."""
        inst.pipe.cut()
        self.expect(inst, sig[0], f"{label} (load)", None, kind="load")
        inst.player = Player(inst, w, sig[1:], nam_lite.input_trim(self.dbu.get(id(w))))
        inst.sig = sig[1:]
        inst.pipe.knobs(inst.eq)

    def play(self, inst, label, n=1):
        for _ in range(n):
            b = inst.player.b
            self.expect(inst, inst.sig[b], f"{label} block {b}", inst.player.next())

    # steps
    def silence_fixed_point(self):
        _, before, after = nam_lite.reference(self.w, [0.0] * 32, rings=True)
        if before != after:
            raise CheckFailed("silence(): not a fixed point of nam_a2.asm")

    def two_models_load(self):
        """A (Model 0, the built-in model, no input trim) and B (Model 3, another capture
        in User IR slot 3, made at 15 dBu: its input x 10^((STOMP_DBU - 15)/20), other
        knobs) each claim a slot and load their model on their first call."""
        r = self.rig
        self.A = r.inst("A", 0)
        self.B = r.inst("B", 1)
        self.B.knobs(drive=0.62, vol=0.7, model=3, eq=(0.3, 0.7, 0.45, 0.9))
        self.start(self.A, self.w, self.sig("A", 80), "A")
        self.start(self.B, self.w2, self.sig("B", 12), "B")
        rep = r.rep()
        if rep[REPW["R_CLAIMS"]] != 2 or rep[REPW["R_LOADS"]] != 2:
            raise CheckFailed(f"claims {rep[5]}, loads {rep[4]}: want 2 and 2")

    def two_models_play(self):
        """A and B interleaved, each bit for bit nam_a2.asm on its own model, input x its
        own trim (B's; none for A), and knobs."""
        peak = 0
        for b in range(self.nblk):
            self.play(self.A, "A")
            self.play(self.B, "B")
        for p in (self.A.player, self.B.player):
            peak = max(peak, max(abs(ssim.b2f(v)) for v in p.words[:16 * self.nblk]))
        if peak < 1e-3:
            raise CheckFailed("the test signal is too quiet to show anything")
        if self.A.player.words[:64] == self.B.player.words[:64]:
            raise CheckFailed("A and B play the same: the test shows nothing")

    def model_change_crossfades(self):
        """B to User IR slot 7 (made at 6 dBu, another trim): the loading block plays the
        tail alone, then the new model from its silence state, on its input x its own
        trim, fades in as the tail fades out. A plays on, untrimmed."""
        self.B.knobs(model=7)
        self.start(self.B, self.w3, self.sig("B7", 36), "B to slot 7")
        for b in range(20):
            self.play(self.A, "A")
            self.play(self.B, "B slot 7")

    def polarity_inverts(self):
        """B's Polarity to Inverted (1, then a float 1.0's bits), then back to Normal:
        from the next block on its output is the reference with the sign flipped, through
        the tone stack; A, Normal, plays on unchanged."""
        for pol, n in ((1, 4), (ssim.f2b(1.0), 3), (0, 4)):
            self.B.knobs(polarity=pol)
            for b in range(n):
                self.play(self.A, "A")
                self.play(self.B, f"B polarity {pol:#x}")

    def cab_ir_is_silent(self):
        """B to slot 5, an ordinary cab IR (Model 5.0 as a float): the tail fades out to silence."""
        self.B.knobs(model=5.0)
        self.B.pipe.cut()
        for k in range(20):
            self.expect(self.B, self.sig("B7", 24)[k % 8], f"B to a cab IR, {k}", None)
            self.play(self.A, "A")

    def back_to_builtin(self):
        """B to Model 0: the built-in model again (not a fresh slot: no fade from nothing),
        without slot 7's trim."""
        self.B.knobs(model=0)
        self.start(self.B, self.w, self.sig("B0", 18), "B to Model 0")
        for b in range(4):
            self.play(self.B, "B built-in")
            self.play(self.A, "A")

    def third_and_fourth(self):
        """C (slot 9) takes the last free slot; D finds none and passes its input through."""
        r = self.rig
        if self.lay.slots < 3:
            self.C = None
        else:
            self.C = r.inst("C", 2)
            self.C.knobs(model=9, drive=0.4, vol=0.55)
            self.start(self.C, self.w4, self.sig("C", 14), "C")
        self.D = r.inst("D", 3)
        self.D.knobs(model=3)
        for b in range(4):
            self.play(self.A, "A")
            self.play(self.B, "B built-in")
            if self.C:
                self.play(self.C, "C")
            blk = self.sig("D", 4)[b]
            if self.D.call(blk, f"D block {b}") != blk:
                raise CheckFailed(f"D block {b}: no slot left, but it did not pass its input through")

    def takeover(self):
        """A removed (no longer called): D's next call finds A's slot unused since its
        own last call, takes it, loads its model and plays it from the silence state."""
        self.start(self.D, self.w2, self.sig("D2", 14), "D takes A's slot")
        if self.rig.sim.rd(self.D.i0 + P["P_SLOT"]) != self.rig.sim.rd(self.A.i0 + P["P_SLOT"]):
            raise CheckFailed("D did not take A's slot")
        for b in range(6):
            self.play(self.D, "D")
            self.play(self.B, "B built-in")
            if self.C:
                self.play(self.C, "C")

    def recreated(self):
        """B created again at the same place (its DM block zeroed, a model change in the
        stock): it finds its own slot again and starts it from nothing."""
        B = self.B
        sim = self.rig.sim
        for k in range(145):
            sim.wr(B.i0 + k, 0)
        sim.wr(B.i0 + 3, 1)
        B.pipe = Pipe()
        B.knobs(drive=0.5, vol=0.5, model=3, eq=(0.5, 0.5, 0.5, 0.5))
        self.start(B, self.w2, self.sig("B3", 6), "B recreated")
        for b in range(4):
            self.play(B, "B again")
            self.play(self.D, "D")

    def dma_timeout(self):
        """A chain that never ends: the block is silent, the channel is switched off,
        every instance is silent for BACKOFF_N calls, then each slot starts again from
        nothing (load, then its model from the silence state)."""
        r = self.rig
        r.dma.mode = "stall"
        to = r.rep()[REPW["R_TIMEOUTS"]]
        got = self.D.call(self.sig("D2", 14)[0], "D, DMA stalls")
        r.dma.mode = "ok"
        if got != self.zero:
            raise CheckFailed("a stalled DMA: the block is not silent")
        if r.rep()[REPW["R_TIMEOUTS"]] != to + 1 or r.sim.rd(DMAC0) != 0 or r.dma.active:
            raise CheckFailed("a stalled DMA: not counted, or the channel not switched off")
        self.timeout_cycles = r.cycles[-1][1]
        live = [x for x in (self.B, self.C, self.D) if x]
        n = 0
        while r.rep()[REPW["R_BACKOFF"]]:
            x = live[n % len(live)]
            if x.call(self.zero, f"{x.name} backoff") != self.zero:
                raise CheckFailed(f"{x.name}: not silent after a DMA failure")
            n += 1
        live = live[n % len(live):] + live[:n % len(live)]      # the order the graph calls them in
        for x in live:
            x.pipe = Pipe()
        sigs = {"B": (self.w2, "Bt"), "C": (self.w4, "Ct"), "D": (self.w2, "Dt")}
        for x in live:
            w, s = sigs[x.name]
            self.start(x, w, self.sig(s, 6), f"{x.name} after the failure")
        for b in range(4):
            for x in live:
                self.play(x, f"{x.name} after the failure")

    def busy_channel(self):
        """The channel found busy (someone else's DMA): the block is silent and DMAC0 is not touched."""
        r = self.rig
        sk = r.rep()[REPW["R_SKIPS"]]
        r.dma.wr0(DMAC0, DEN | DMAS)
        r.foreign = True
        got = self.B.call(self.zero, "B, channel busy")
        r.foreign = False
        if got != self.zero or r.rep()[REPW["R_SKIPS"]] != sk + 1 or r.dma.rd0(DMAC0) != DEN | DMAS:
            raise CheckFailed("a busy channel: not silent, not counted, or DMAC0 touched")
        r.dma.wr0(DMAC0, 0)

    def cycle_budget(self):
        worst = max(c for _, c in self.steady)
        if worst > MAX_STEADY:
            raise CheckFailed(f"{worst} instructions a steady block, over {MAX_STEADY}")

    def summary(self):
        st = [c for _, c in self.steady]
        ld = [c for _, c in self.loads]
        return dict(steady_worst=max(st), steady_mean=sum(st) / len(st), load_worst=max(ld),
                    worst=max(c for _, c in self.rig.cycles), timeout=getattr(self, "timeout_cycles", None))


def check(asm, lay, w, **kw):
    k = KernelCheck(asm, lay, w, **kw)
    try:
        k.run()
    except CheckFailed as e:
        return False, str(e), k
    return True, k.summary(), k


def main():
    slots = int(sys.argv[sys.argv.index("--slots") + 1]) if "--slots" in sys.argv else 3
    args = sys.argv[1:]
    opt = lambda k: args[args.index(k) + 1] if k in args else None
    skip = {opt(k) for k in ("-o", "--slots", "--staging")}
    src = [a for a in args if not a.startswith("-") and a not in skip]
    if src:
        w, c = nam_lite.nam_pack.load(src[0], channels=C)
        if c != C:
            sys.exit(f"{src[0]}: {c} channels, NAM A2 Lite has {C}")
    else:
        w = nam_lite.placeholder()
    asm, lay = build(w, slots, staging=opt("--staging") or "b2")
    if "-o" in sys.argv:
        open(sys.argv[sys.argv.index("-o") + 1], "w").write(asm)
    for k, v in lay.report().items():
        print(f"{k}: {v}")
    if "--check" in sys.argv:
        ok, res, _ = check(asm, lay, w)
        print(res)
        if not ok:
            sys.exit(1)


if __name__ == "__main__":
    main()
