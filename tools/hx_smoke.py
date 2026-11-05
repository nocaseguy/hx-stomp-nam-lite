#!/usr/bin/env python3
"""hx_smoke.py - test a NAM A2 Lite firmware image on the HX Stomp over USB.

usage: python3 tools/hx_smoke.py IMAGE [--stock STOCK.hxf]
                                 [--only CASES|TAGS] [--skip CASES|TAGS] [--record S] [--soak S]
                                 [--json OUT] [--no-ramrun] [--list] [--steps]

IMAGE (.hxf or .l6ia, e.g. build/HX_Stomp_v3.80.0_NAM_A2_Lite.hxf) runs from RAM
(tools/hx_ramrun.sh: the eMMC is not touched, what the image saves stays in RAM, a power
cycle brings the installed firmware back) and is driven with tools/hx_ctl.py. Cases, with
their tags (--only / --skip take names or tags, comma-separated; --list prints them):

  boot              control   the unit answers after the RAM run
  presets_list      control   the setlist's preset names read (100 or more)
  preset_roundtrip  control   the edit buffer read, written back and read again, byte for byte
  preset_select     control   preset 1 selected and preset 0 again, the edit buffer then restored
  nam1, nam2, nam3  nam audio 1, 2 (Amp > NAM, 147) and 3 blocks (+ Distortion > NAM, 148, when the
                              image has it) load; recorded: no repeated block, dropout or click
  nam_path_b        nam       a NAM block on path B beside one on path A
  nam_bypass        nam       a NAM block bypassed and on again, read back each time
  nam_knob_types    nam       Model an int, the tone knobs floats, Polarity a bool, as read back
  nam_model_edges   nam       Model 0, an empty slot (6) and 128 (the silence path): unit stays up
  model_switch      nam audio a block's Model knob changed under full load; recorded clean
  nam_takeover      nam audio risky  the first of three blocks removed and a new one added (it
                              takes the freed slot); recorded clean. Run last: it hung the unit on
                              2026-10-30, past the stock ~30-write limit; clean since the reboots
  budget_admit      limits    the NAM blocks plus a stock effect that fits the DSP budget load
  budget_refuse     limits    the NAM blocks plus one that does not are refused, unit stays up
  recovery          limits    after that refusal a valid preset loads again
  nam_delay         limits audio  the NAM blocks plus the dearest stock delay that fits (recorded
                              clean); nam_delay_refuse: plus the cheapest that does not, refused
  amp_limit         limits    a third amp (343) is refused (the Stomp's two-amp rule), unit up
  stock_<category>  stock     a stock block of each placeable browser category (distortion,
                              dynamics, eq, modulation, delay, reverb, pitch, filter, wah, amp,
                              preamp, cab (single), volume),
                              the cheapest the image lists, alone (recorded clean) and beside
                              NAM blocks when the budget lets it (an amp beside one NAM block)
  stock_sweep       sweep     every placeable stock block (~160) once, alone; opt-in (--only sweep),
                              ~12 minutes
  stress_model      stress    6 Model changes in a row, unit up and the last one read back
  stress_presets    stress    7 preset changes in a row, unit up
  rewrites_stock,   rewrites  the edit buffer rewritten from empty 40 times, the unit asked after
  rewrites_nam1,              each (a stock drive; one NAM block; three): where it stops answering.
                              Stock and nam3 both die on USB write 31 (2026-10-31).
  rewrites_nam3               Opt-in (--only rewrites, or one name)
  soak              stress audio  --soak S seconds with three blocks (two without 148): recorded clean
  restore           control   the edit buffer found at the start put back (always runs)

The budget cases take each block's dsp_cost from IMAGE's own Entry 0 Table 1 and the empty
preset's count from the unit (1,476..1,500 units, docs/research/NAM_LITE_DSP_LOAD.md), so they
hold when dsp_cost changes. Amps, kind-1 effects, delays and reverbs (kind 8) and single cabs
(kind 31) are placed; dual cabs and amp + cab blocks only as hx_ctl --cab-id copies of factory
blocks. After one dropped preset the unit may drop the next cab write too: test from a fresh
boot. Audio cases need build/record_mac (macOS: swiftc -O tools/mac/record_mac.swift -o
build/record_mac) and the unit's USB audio (after many RAM runs macOS can lose it: a power cycle or re-plug brings it back);
without it they are reported SKIP. Captures are expected in User IR slots 4 and 5; slot 6
empty. The stock 3.80 firmware stops answering after ~30 whole-preset writes over USB in one boot
(measured from RAM with no NAM block: docs/research/NAM_LITE_DSP_LOAD.md), and every hx_ctl
set-model, load-preset and select is one; the suite reboots the image from RAM before a case
once 10 writes are used, so a run never comes near it (the rewrites cases cross it on
purpose). Exit status 0 when nothing failed.
"""
import json
import math
import os
import statistics
import struct
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import hx_ctl  # noqa: E402
import patch_amp  # noqa: E402

STOCK = os.environ.get("HX_STOMP_HXF") or os.path.join(ROOT, "HX_Stomp_v3.80.0_0x103966115.hxf")
CAP = 9000                                   # the ARM's DSP budget
BASE_LO, BASE_HI = 1450, 1530                # the empty preset's count, 1,476..1,500 measured, with margin
NAM_PARAMS = "{m},0.5,0.5,0.5,0.5,0.5,0.5,False"
# The NAM entries of the image under test (set_profile, from the image): the release (Amp > NAM
# 147 and Distortion > NAM 148, 8 knobs, Model first and an int) or the donor build
# (patch_amp.py remove-model / add-fx-model: Distortion > NAM on Xenomorph Fuzz Mono's id 555, 10 knobs in Xenomorph's
# types, Model 7th and a float; not an amp, so the two-amp rule does not count it), or the 4-knob
# donor build (MM4 Frequency Shifter's id 461: Model, Polarity, Input, Output; no tone knobs), or the EQ
# build (--knobs eq: 555 again, Mid Freq 150..3000 Hz at 8, Q at 9, High Cut at 10).
PROFILES = {"release": dict(name="release", a=147, c=148, kinds={147: 17, 148: 1}, amp=True, model_at=0),
            "donor": dict(name="donor", a=555, c=555, kinds={555: 1}, amp=False, model_at=6),
            "donor4": dict(name="donor4", a=461, c=461, kinds={461: 1}, amp=False, model_at=0),
            "donor_eq": dict(name="donor_eq", a=555, c=555, kinds={555: 1}, amp=False, model_at=6)}
NAM = PROFILES["release"]


def read_wav(path):
    d = open(path, "rb").read()
    i, fmt, data = 12, None, None
    while i + 8 <= len(d):
        tag, n = d[i:i + 4], struct.unpack_from("<I", d, i + 4)[0]
        if tag == b"fmt ":
            fmt = struct.unpack_from("<HHIIHH", d, i + 8)
        elif tag == b"data":
            data = d[i + 8:i + 8 + n]
        i += 8 + n + (n & 1)
    code, ch, rate, _, align, bits = fmt
    n = len(data) // align
    if code == 3 and bits == 32:
        x = struct.unpack(f"<{n * ch}f", data[:n * align])
    elif bits == 16:
        x = [v / 32768 for v in struct.unpack(f"<{n * ch}h", data[:n * align])]
    elif bits == 24:
        x = [int.from_bytes(data[k:k + 3], "little", signed=True) / 2 ** 23 for k in range(0, n * align, 3)]
    else:
        x = [v / 2 ** 31 for v in struct.unpack(f"<{n * ch}i", data[:n * align])]
    return x[::ch], rate


def entry3_layouts(l6ia):
    """{preset_id: (model name, [param dicts in slot order, ints decoded])} through the browser rows' name index."""
    e3 = patch_amp.parse_entry3_full(patch_amp.get_entry_swapped(l6ia, 3))
    by_name = {m["words"][2]: m for m in e3["models"]}
    e0 = patch_amp.get_entry_swapped(l6ia, 0)
    segs = patch_amp._parse_e0_segments(e0)
    A = patch_amp.e0_device(segs)
    vr = lambda va, n: e0[patch_amp._e0_vaddr_to_foff(segs, va, n):][:n]
    u32 = lambda va: struct.unpack("<I", vr(va, 4))[0]
    as_int = lambda f: struct.unpack("<i", struct.pack("<f", f))[0]
    out = {}
    for idx in range(patch_amp.E0_BLIST_SLOTS):
        lp, lc = u32(A.BLIST_PTR_TAB + 4 * idx), u32(A.BLIST_CNT_TAB + 4 * idx)
        for k in range(lc if lp else 0):
            _, mi, _, pid = struct.unpack("<IIiH", vr(lp + 48 * k, 14))
            m = by_name.get(mi)
            if m is None or pid in out:
                continue
            ps = []
            for p in sorted(m["params"], key=lambda p: p["slot"]):
                q = dict(name=p["name"], type=p["type"], lo=p["min"], hi=p["max"])
                if p["type"] == 2:
                    q["lo"], q["hi"] = as_int(p["min"]), as_int(p["max"])
                ps.append(q)
            out[pid] = (m["name"], ps)
    return out


def set_profile(l6ia_bytes):
    global NAM
    costs = table1_costs(l6ia_bytes)
    if 147 not in costs:
        lay = entry3_layouts(l6ia_bytes)
        for prof, pid in (("donor4", 461), ("donor", 555)):
            if pid in costs and lay[pid][0] == "HD2_DistNAMLite":
                if prof == "donor" and any(q["name"] == "Ch1 Mid Freq" for q in lay[pid][1]):
                    prof = "donor_eq"            # the EQ build: Mid Freq at 8
                NAM = PROFILES[prof]
                return
    NAM = PROFILES["release"]


def nam_pids():
    return {NAM["a"], NAM["c"]}


def nam_values(model, polarity=False):
    if NAM["name"] == "donor4":                    # MM4 Frequency Shifter's: Model, Polarity, Input, Output
        return f"{float(model)},{1 if polarity in (True, 'True') else 0},0.5,0.5"
    if NAM["name"] == "donor_eq":                  # Input, Treble, Output, Polarity, Bass, Mid, Model, Mid Freq, Q, High Cut
        return f"0.5,0.5,0.5,{1 if polarity in (True, 'True') else 0},0.5,0.5,{float(model)},650.0,0,1.0"
    if NAM["name"] == "donor":
        return f"0.5,0.5,0.5,{1 if polarity in (True, 'True') else 0},0.5,0.5,{float(model)},0.5,0,0.5"
    return f"{model},0.5,0.5,0.5,0.5,0.5,0.5,{polarity}"
RECORDER = os.path.join(ROOT, "build", "record_mac")   # tools/mac/record_mac.swift


STEPS = "--steps" in sys.argv                 # log every hx_ctl edit as it goes (to find a hanging step)
# The stock 3.80 firmware itself stops answering after ~30 whole-preset writes over USB in one
# boot (31 on 2026-10-31, from RAM, one stock drive, no NAM): every set-model, load-preset and
# select is one. So the suite counts them and reboots the image from RAM before each case once
# WRITE_BUDGET is used (the opt-in rewrites cases go past it on purpose).
WRITE_BUDGET = 10
WRITES = 0


def run(*args, timeout=60):
    global WRITES
    if any(a in ("set-model", "load-preset", "select") for a in args):
        WRITES += 1
    if STEPS and len(args) > 1 and args[1] not in ("status",) and "status" not in args:
        print("      $ hx_ctl " + " ".join(args[3:] if args[1] == "--timeout" else args[1:]), flush=True)
    return subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True, timeout=timeout)


def alive(tries=1):
    for _ in range(tries):
        if run("tools/hx_ctl.py", "--timeout", "3", "status").returncode == 0:
            return True
        time.sleep(3)
    return False


_EMPTY = object()                            # a "preset" with no blocks: find_kind_and_params then reads
_blocks = hx_ctl.blocks                      # the factory presets only
hx_ctl.blocks = lambda s: [] if s is _EMPTY else _blocks(s)


def table1_costs(l6ia_bytes):
    """{preset_id: dsp_cost} from an image's Entry 0 Table 1."""
    e0 = patch_amp.get_entry_swapped(l6ia_bytes, 0)
    segs = patch_amp._parse_e0_segments(e0)
    A = patch_amp.e0_device(segs)
    vr = lambda va, n: e0[patch_amp._e0_vaddr_to_foff(segs, va, n):][:n]
    t1 = struct.unpack("<I", vr(A.TAB1_BASE_PTRS[0], 4))[0]
    _, cnt = patch_amp._decode_thumb_movw(vr(A.TAB1_CNT_INSN, 4))
    out = {}
    for i in range(cnt):
        _, pid, _, c = struct.unpack("<IHHI", vr(t1 + 12 * i, 12))
        out[pid] = c
    return out


def kind1_fillers(costs):
    """[(cost, preset_id)] of stock kind-1 effects with factory knob values hx_ctl knows."""
    seen, out = set(), []
    for pid, c in sorted(costs.items(), key=lambda kv: kv[1]):
        if pid in nam_pids() or c < 30 or c in seen:
            continue
        k, v = hx_ctl.find_kind_and_params(_EMPTY, pid)
        if k == 1 and v:
            out.append((c, pid))
            seen.add(c)
    return out


# Browser categories (Entry 0 list index // 4) whose blocks hx_ctl can place (kind 1 effects,
# kind 17 amps and preamps, kind 8 delays and reverbs, kind 31 single cabs: category 14 sub 0, which
# no factory preset holds, built on hx_ctl.kind_params). Send/return blocks are left out.
STOCK_CATEGORIES = {2: "distortion", 3: "dynamics", 4: "eq", 5: "modulation", 6: "delay", 7: "reverb",
                    8: "pitch", 9: "filter", 10: "wah", 12: "amp", 13: "preamp", 14: "cab", 16: "volume"}
PLACEABLE_KINDS = (1, 8, 17, 31)
KIND_OF = {}                                 # preset_id -> kind for blocks hx_ctl cannot look up (single cabs)


def stock_catalog(l6ia_bytes, costs):
    """{category name: [(dsp_cost, preset_id, kind)]} of the image's stock browser items with
    factory knob values hx_ctl knows, cheapest first."""
    e0 = patch_amp.get_entry_swapped(l6ia_bytes, 0)
    segs = patch_amp._parse_e0_segments(e0)
    A = patch_amp.e0_device(segs)
    vr = lambda va, n: e0[patch_amp._e0_vaddr_to_foff(segs, va, n):][:n]
    u32 = lambda va: struct.unpack("<I", vr(va, 4))[0]
    out = {}
    for idx in range(patch_amp.E0_BLIST_SLOTS):
        cat = STOCK_CATEGORIES.get(idx // 4)
        if not cat:
            continue
        lp, lc = u32(A.BLIST_PTR_TAB + 4 * idx), u32(A.BLIST_CNT_TAB + 4 * idx)
        for k in range(lc if lp else 0):
            _, _, ci, pid = struct.unpack("<IIiH", vr(lp + 48 * k, 14))
            if ci != -1 or pid in nam_pids() or pid not in costs:
                continue
            if cat == "cab":                 # single cabs only (sub 0): kind 31, one knob layout
                if idx % 4:
                    continue
                KIND_OF[pid] = hx_ctl.SINGLE_CAB_KIND
                kind, vals = KIND_OF[pid], hx_ctl.kind_params(KIND_OF[pid])
            else:
                kind, vals = hx_ctl.find_kind_and_params(_EMPTY, pid)
            if kind in PLACEABLE_KINDS and vals:
                out.setdefault(cat, set()).add((costs[pid], pid, kind))
    return {c: sorted(v) for c, v in out.items()}


def place(pids, model=None):
    """Build a preset from an empty edit buffer, block by block; True when every block reads back."""
    for k, pid in enumerate(pids):
        args = ["tools/hx_ctl.py", "--timeout", "5", "set-model", "--slot", "0" if k == 0 else "end",
                "--model-id", str(pid)]
        if pid in nam_pids():
            args += ["--kind", str(NAM["kinds"][pid]), "--params", nam_values((model or [4] * 9)[k])]
        elif pid in KIND_OF:
            args += ["--kind", str(KIND_OF[pid])]
        if k == 0:
            args += ["--clear-after", "--clear-path-b"]
        if "verified" not in run(*args).stdout:
            return False
    return True


def scan(path):
    """(rms dBFS, peak, repeated blocks, zero runs, clicks) of channel 0 of a recording."""
    x, _ = read_wav(path)
    n = len(x)
    rms = math.sqrt(sum(v * v for v in x) / max(n, 1))
    rep = sum(1 for b in range(1, n // 16) if x[16 * b:16 * b + 16] == x[16 * b - 16:16 * b]
              and any(abs(v) > 1e-4 for v in x[16 * b:16 * b + 16]))
    zr, z, seen = 0, 0, False                  # a dropout: 16+ zeros with signal on both sides
    for v in x:                                # (a silent block, e.g. a gate with no input, is none)
        if v == 0.0:
            z += 1
            continue
        zr += seen and z >= 16
        z, seen = 0, True
    d2 = [abs(x[k] - 2 * x[k - 1] + x[k - 2]) for k in range(2, n)]
    W, clicks = 480, 0
    for k0 in range(0, len(d2), W):
        seg = d2[k0:k0 + W]
        m = sorted(seg)[len(seg) // 2] if seg else 0
        clicks += sum(1 for v in seg if m > 1e-5 and v > 25 * m and v > 0.02)
    return 20 * math.log10(rms + 1e-12), max((abs(v) for v in x), default=0), rep, zr, clicks


class NoAudio(Exception):
    pass


def record(seconds, tries=4):
    """A recording of the unit's USB output (a .wav path), None without the recorder; NoAudio
    when macOS gives no frames (its USB audio driver can lose the unit after many RAM runs: a
    power cycle or a re-plug brings it back)."""
    if not os.path.exists(RECORDER):
        return None
    path = tempfile.mktemp(suffix=".wav")
    for _ in range(tries):
        subprocess.run([RECORDER, "HX Stomp", str(seconds), path], capture_output=True, timeout=seconds + 30)
        if os.path.exists(path) and os.path.getsize(path) > 1000:
            return path
        time.sleep(3)
    raise NoAudio("no audio frames from the unit (power-cycle or re-plug it)")


def ramrun(image, stock):
    l6ia, _ = patch_amp.load_l6ia_from_any(image)
    tmp = tempfile.mktemp(suffix=".l6ia")
    open(tmp, "wb").write(l6ia)
    r = subprocess.run(["sh", "tools/hx_ramrun.sh", tmp, stock], cwd=ROOT, capture_output=True, text=True, timeout=600)
    os.remove(tmp)
    return r.returncode == 0 and alive(tries=40), l6ia


class Report:
    def __init__(self):
        self.rows = []

    def add(self, name, ok, detail):
        state = "SKIP" if ok is None else ("PASS" if ok else "FAIL")
        self.rows.append({"case": name, "state": state, "detail": detail})
        print(f"  {state}  {name:16} {detail}", flush=True)

    @property
    def ok(self):
        return all(r["state"] != "FAIL" for r in self.rows)


def audio_check(secs):
    """(True/False/None, detail) of a recording of the unit's output now; None: no audio."""
    try:
        path = record(secs)
    except NoAudio as e:
        return None, str(e)
    if not path:
        return None, "no recorder"
    db, pk, r, z, c = scan(path)
    os.remove(path)
    return r == 0 and z == 0 and c == 0, f"{db:.1f} dBFS, peak {pk:.3f}; repeated blocks {r}, dropouts {z}, clicks {c}"


def status_blocks():
    """[(path, slot, model, enabled, params)] of the edit buffer, from get-preset's JSON."""
    out = tempfile.mktemp(suffix=".json")
    if run("tools/hx_ctl.py", "--timeout", "5", "get-preset", "-o", out).returncode:
        return None
    bl = json.load(open(out))["blocks"]
    os.remove(out)
    return [(b["path"], b["slot"], b["model_id"], b["enabled"], b["params"]) for b in bl]


def set_nam(slot, model, pid=None, extra=(), polarity="False"):
    pid = pid or NAM["a"]
    args = ["tools/hx_ctl.py", "--timeout", "5", "set-model", "--slot", slot, "--model-id", str(pid),
            "--kind", str(NAM["kinds"][pid]), "--params", nam_values(model, polarity), *extra]
    return "verified" in run(*args).stdout


class Suite:
    def __init__(self, image_l6ia, opts):
        self.costs = table1_costs(image_l6ia)
        self.catalog = stock_catalog(image_l6ia, self.costs)
        self.three = NAM["c"] in self.costs
        self.nam = [NAM["a"], NAM["a"]] + ([NAM["c"]] if self.three else [])
        self.nam_cost = sum(self.costs.get(p, 0) for p in self.nam)   # (0 on a stock image: no NAM)
        self.opts = opts
        self.saved = tempfile.mktemp(suffix=".json")
        self.audio = True                         # cleared on the first NoAudio

    def audio_case(self, rep, name, ok_so_far, secs=None, what=""):
        """what: a prefix for the detail (which blocks)."""
        add = lambda ok, d: rep.add(name, ok, what + d)
        if not ok_so_far:
            add(False, "did not load")
            return
        if not self.audio:
            add(None if alive() else False, "no audio: only checked the unit answers")
            return
        res, detail = audio_check(secs or self.opts["record"])
        if res is None:
            self.audio = False
            add(None if alive() else False, detail + "; the unit answers")
        else:
            add(res and alive(), detail)

    # ---- control
    def presets_list(self, rep):
        r = run("tools/hx_ctl.py", "--timeout", "5", "presets")
        n = sum(1 for line in r.stdout.splitlines() if line.strip()[:1].isdigit())
        rep.add("presets_list", n >= 100, f"{n} preset names")

    def preset_roundtrip(self, rep):
        """The edit buffer read, written back and read again: the same blocks (models, kinds,
        bypass, knob values and their types). (The unit re-encodes a written preset, so the
        bytes may differ.)"""
        before = status_blocks()
        a = tempfile.mktemp(suffix=".bin")
        ok = before is not None and run("tools/hx_ctl.py", "--timeout", "5", "get-preset", "--bin", a).returncode == 0
        ok = ok and "match" in run("tools/hx_ctl.py", "--timeout", "5", "load-preset", a).stdout
        after = status_blocks() if ok else None
        same = ok and repr(before) == repr(after)
        rep.add("preset_roundtrip", same, f"{len(before or [])} blocks, the same after a write" if same else "differs")
        if os.path.exists(a):
            os.remove(a)

    def preset_select(self, rep):
        r1 = run("tools/hx_ctl.py", "--timeout", "5", "select", "1")
        s1 = run("tools/hx_ctl.py", "--timeout", "5", "status").stdout
        r0 = run("tools/hx_ctl.py", "--timeout", "5", "select", "0")
        s0 = run("tools/hx_ctl.py", "--timeout", "5", "status").stdout
        ok = r1.returncode == 0 and "preset 1" in s1 and r0.returncode == 0 and "preset 0" in s0
        rep.add("preset_select", ok, "preset 1, then preset 0")

    # ---- NAM blocks
    def nam_n(self, rep, n):
        if n == 3 and not self.three:
            rep.add("nam3", None, f"the image has no Distortion > NAM entry ({NAM['c']})")
            return
        self.audio_case(rep, f"nam{n}", place(self.nam[:n]))

    def nam_path_b(self, rep):
        ok = place([NAM["a"]]) and set_nam("1:end", 5)            # (hx_ctl's paths are 0 and 1; they share the 8 positions)
        bl = status_blocks() if ok else None
        ok = ok and bl is not None and any(b[0] == 1 and b[2] == NAM["a"] for b in bl)
        rep.add("nam_path_b", ok and alive(), "a NAM block on path B beside one on path A")

    def nam_bypass(self, rep):
        ok = place([NAM["a"]]) and set_nam("0", 4, extra=["--disabled"])
        off = status_blocks() if ok else None
        ok2 = set_nam("0", 4)
        on = status_blocks() if ok2 else None
        ok = bool(off and on) and off[0][3] is False and on[0][3] is True
        rep.add("nam_bypass", ok and alive(), "bypassed, then on again (read back)")

    def nam_knob_types(self, rep):
        ok = place([NAM["a"]]) and set_nam("0", 4, polarity="True")
        bl = status_blocks() if ok else None
        p = bl[0][4] if bl else []
        if NAM["name"] == "donor4":                    # MM4's: f i f f
            good = (len(p) == 4 and [type(v) for v in p] == [float, int, float, float] and p[0] == 4.0 and p[1] == 1)
            what = "4 knobs in MM4's types, Model 4.0 (1st), Polarity 1 (2nd)"
        elif NAM["name"] in ("donor", "donor_eq"):     # Xenomorph's: f f f i f f f f i f
            good = (len(p) == 10 and [type(v) for v in p] == [float] * 3 + [int] + [float] * 4 + [int, float]
                    and p[3] == 1 and p[6] == 4.0)
            what = "10 knobs in Xenomorph's types, Model 4.0 (7th), Polarity 1 (4th)"
        else:
            good = (len(p) == 8 and type(p[0]) is int and all(type(v) is float for v in p[1:7])
                    and p[7] is True)
            what = "Model int, 6 floats, Polarity bool"
        rep.add("nam_knob_types", good and alive(), f"read back {p}" if not good else what)

    def nam_model_edges(self, rep):
        res = []
        for m in (0, 6, 128):
            res.append(place([NAM["a"]], model=[m]) and alive())
        rep.add("nam_model_edges", all(res), f"Model 0, 6 (empty), 128: {res}")

    def model_switch(self, rep):
        ok = place(self.nam)
        for m in (5, 4, 5, 4):
            ok = ok and set_nam("0", m)
        self.audio_case(rep, "model_switch", ok)

    def nam_takeover(self, rep):
        if not self.three:
            rep.add("nam_takeover", None, f"needs three blocks ({NAM['c']})")
            return
        ok = place(self.nam)
        ok = ok and place([NAM["a"], NAM["c"]], model=[5, 4])         # the first block gone: two remain
        ok = ok and set_nam("end", 4)                       # a new one: it takes the freed slot
        self.audio_case(rep, "nam_takeover", ok)

    # ---- limits
    def budget(self, rep):
        fill = kind1_fillers(self.costs)
        free_lo, free_hi = CAP - BASE_HI - self.nam_cost, CAP - BASE_LO - self.nam_cost
        fit = [f for f in fill if f[0] <= free_lo]
        over = [f for f in fill if f[0] > free_hi]
        if fit:
            c, pid = fit[-1]
            rep.add("budget_admit", place(self.nam + [pid]),
                    f"NAM x{len(self.nam)} ({self.nam_cost}) + preset {pid} ({c}) fits")
        else:
            rep.add("budget_admit", None, f"no stock effect fits beside {self.nam_cost} (by design)")
        if over:
            c, pid = over[0]
            rep.add("budget_refuse", (not place(self.nam + [pid])) and alive(tries=3),
                    f"NAM x{len(self.nam)} + preset {pid} ({c}) refused, unit up")
        else:
            rep.add("budget_refuse", None, "no stock effect is too big (?)")
        rep.add("recovery", place([NAM["a"], NAM["a"]]) and alive(), "two NAM blocks load after the refusal")

    def nam_delay(self, rep):
        """Every NAM block plus the dearest stock delay that fits the budget (recorded clean), then
        plus the cheapest that does not (refused, unit up): the room left for a delay."""
        dl = self.catalog.get("delay", [])
        free_lo, free_hi = CAP - BASE_HI - self.nam_cost, CAP - BASE_LO - self.nam_cost
        fit = [d for d in dl if d[0] <= free_lo]
        over = [d for d in dl if d[0] > free_hi]
        if fit:
            c, pid, _ = fit[-1]
            self.audio_case(rep, "nam_delay", place(self.nam + [pid]),
                            what=f"NAM x{len(self.nam)} + delay {pid} ({c}): ")
        else:
            rep.add("nam_delay", None, f"no stock delay fits beside {self.nam_cost}")
        if over:
            c, pid, _ = over[0]
            rep.add("nam_delay_refuse", (not place(self.nam + [pid])) and alive(tries=3),
                    f"NAM x{len(self.nam)} + delay {pid} ({c}) refused, unit up")

    def amp_limit(self, rep):
        if NAM["amp"]:
            rep.add("amp_limit", (not place([147, 147, 343])) and alive(tries=3), "a third amp (343) refused, unit up")
        else:                                          # NAM is an effect: two stock amps beside it, a third refused
            ok = place([NAM["a"], 343, 343]) and alive()
            ok = ok and (not place([343, 343, 343])) and alive(tries=3)
            rep.add("amp_limit", ok, "NAM + two amps (343) load; three amps refused, unit up")

    # ---- stock blocks
    def stock(self, rep, cat):
        items = self.catalog.get(cat)
        if not items:
            rep.add(f"stock_{cat}", None, "no placeable stock block in this category")
            return
        c, pid, kind = items[0]
        self.audio_case(rep, f"stock_{cat}", place([pid]), what=f"preset {pid} ({c} units): ")
        free = CAP - BASE_HI - 2 * self.costs.get(NAM["a"], 0)
        if kind == 17 and NAM["amp"]:
            ok = place([NAM["a"], pid]) and alive()       # (two amps at most: one NAM beside it)
            rep.add(f"stock_{cat}_nam", ok, f"preset {pid} beside a NAM block")
        elif c <= free:
            ok = place([NAM["a"], NAM["a"], pid]) and alive()
            rep.add(f"stock_{cat}_nam", ok, f"preset {pid} beside two NAM blocks")
        else:
            rep.add(f"stock_{cat}_nam", None, f"preset {pid} ({c}) does not fit beside two NAM blocks")

    def stock_sweep(self, rep):
        """Every placeable stock block once, alone (opt-in: --only sweep)."""
        bad, n = [], 0
        for cat, items in self.catalog.items():
            for c, pid, kind in items:
                n += 1
                if not (place([pid]) and alive()):
                    bad.append(pid)
                    if not alive(tries=3):
                        rep.add("stock_sweep", False, f"unit gone after preset {pid}; {n} tried")
                        return
        rep.add("stock_sweep", not bad, f"{n} stock blocks loaded alone" + (f"; failed: {bad}" if bad else ""))

    # ---- stress
    def stress_model(self, rep):
        ok = place(self.nam)
        n = 0
        for i in range(6):                                  # (within the write budget)
            if not set_nam("0", 4 + (i & 1)):
                break
            n += 1
        bl = status_blocks()
        rep.add("stress_model", ok and n == 6 and bool(bl) and bl[0][4][NAM["model_at"]] == 5 and alive(),
                f"{n}/6 Model changes in a row read back")

    def stress_presets(self, rep):
        good = 0
        for i in (0, 1, 2, 3, 0, 1, 2):
            good += run("tools/hx_ctl.py", "--timeout", "5", "select", str(i)).returncode == 0
        run("tools/hx_ctl.py", "--timeout", "5", "select", "0")
        rep.add("stress_presets", good == 7 and alive(), f"{good}/7 preset changes")

    def rewrites(self, rep, label, pids, n=40):
        """The edit buffer rewritten from empty n times (each a full preset write), the unit
        asked after each: where it stops answering, if it does (opt-in: --only rewrites)."""
        pids = [NAM[p] if p in ("a", "c") else p for p in pids]   # "a"/"c": the image's NAM entries
        w0 = WRITES                            # a rewrite is one USB preset write a block
        for i in range(1, n + 1):
            if not place(pids, model=[4 + (i & 1)] * len(pids)):
                up = alive(tries=3)
                rep.add(f"rewrites_{label}", False, f"rewrite {i} (USB write {WRITES - w0}) failed; "
                        f"unit {'up' if up else 'GONE'}")
                return
            if not alive(tries=2):
                rep.add(f"rewrites_{label}", False, f"unit gone after rewrite {i} (USB write {WRITES - w0})")
                return
        rep.add(f"rewrites_{label}", True, f"{n} rewrites of {pids}, unit up")

    def soak(self, rep):
        secs = self.opts["soak"]
        if not secs:
            rep.add("soak", None, "--soak not given")
            return
        self.audio_case(rep, "soak", place(self.nam), secs=secs)

    def restore(self, rep):
        ok = os.path.exists(self.saved) and "match" in run("tools/hx_ctl.py", "--timeout", "5",
                                                            "load-preset", self.saved).stdout
        rep.add("restore", ok, "edit buffer put back" if ok else "could not put the edit buffer back")


CASES = [  # (name, tags, method, args)
    ("presets_list", "control", "presets_list", ()),
    ("preset_roundtrip", "control", "preset_roundtrip", ()),
    ("preset_select", "control", "preset_select", ()),
    ("nam1", "nam audio", "nam_n", (1,)),
    ("nam2", "nam audio", "nam_n", (2,)),
    ("nam3", "nam audio", "nam_n", (3,)),
    ("nam_path_b", "nam", "nam_path_b", ()),
    ("nam_bypass", "nam", "nam_bypass", ()),
    ("nam_knob_types", "nam", "nam_knob_types", ()),
    ("nam_model_edges", "nam", "nam_model_edges", ()),
    ("model_switch", "nam audio", "model_switch", ()),
    ("budget", "limits", "budget", ()),
    ("nam_delay", "limits audio", "nam_delay", ()),
    ("amp_limit", "limits", "amp_limit", ()),
] + [(f"stock_{c}", "stock", "stock", (c,)) for c in STOCK_CATEGORIES.values()] + [
    ("stock_sweep", "sweep", "stock_sweep", ()),
    ("stress_model", "stress", "stress_model", ()),
    ("stress_presets", "stress", "stress_presets", ()),
    ("soak", "stress audio", "soak", ()),
    ("rewrites_stock", "rewrites", "rewrites", ("stock", [521])),   # (96 was refused on a stock RAM run)
    ("rewrites_nam1", "rewrites", "rewrites", ("nam1", ["a"])),
    ("rewrites_nam3", "rewrites", "rewrites", ("nam3", ["a", "a", "c"])),
    ("nam_takeover", "nam audio risky", "nam_takeover", ()),   # last: it hung the unit once (2026-10-30)
]


def selected(name, tags, only, skip):
    keys = {name, *tags.split()}
    if keys & {"sweep", "rewrites"} and not (only and keys & only):   # opt-in only
        return False
    if name == "budget":
        keys |= {"budget_admit", "budget_refuse", "recovery"}
    if name == "nam_delay":
        keys |= {"nam_delay_refuse"}
    return (not only or keys & only) and not (keys & skip)


def main():
    a = sys.argv[1:]
    if "--list" in a:
        for name, tags, _, _ in CASES:
            print(f"{name:18} {tags}")
        return
    if not a or a[0].startswith("-"):
        sys.exit(__doc__)
    opt = lambda k, d=None: a[a.index(k) + 1] if k in a else d
    image, stock = os.path.abspath(a[0]), os.path.abspath(opt("--stock", STOCK))
    only = set(filter(None, (opt("--only") or "").split(",")))
    skip = set(filter(None, (opt("--skip") or "").split(",")))
    opts = {"record": int(opt("--record", "5")), "soak": int(opt("--soak", "0"))}
    rep = Report()
    if "--no-ramrun" in a:
        l6ia, _ = patch_amp.load_l6ia_from_any(image)
        up = alive(tries=3)
    else:
        print(f"image {image}: RAM run", flush=True)
        up, l6ia = ramrun(image, stock)
    rep.add("boot", up, "answers over USB" if up else "no answer")
    set_profile(l6ia)
    print(f"NAM: the {NAM['name']} entries ({', '.join(map(str, sorted(nam_pids())))})", flush=True)
    if up:
        suite = Suite(l6ia, opts)
        run("tools/hx_ctl.py", "--timeout", "5", "get-preset", "-o", suite.saved)
        global WRITES
        WRITES = 0
        try:
            for name, tags, meth, args in CASES:
                if not selected(name, tags, only, skip):
                    continue
                if WRITES >= WRITE_BUDGET and "rewrites" not in tags:
                    print(f"  (reboot from RAM after {WRITES} writes: the stock firmware's USB write limit)",
                          flush=True)
                    up, _ = ramrun(image, stock)
                    WRITES = 0
                    if not up:
                        rep.add(f"reboot_before_{name}", False, "the image did not come back")
                        break
                getattr(suite, meth)(rep, *args)
        finally:
            suite.restore(rep)
    print(f"\n{'PASSED' if rep.ok else 'FAILED'}: " + ", ".join(
        f"{sum(r['state'] == s for r in rep.rows)} {s.lower()}" for s in ("PASS", "FAIL", "SKIP")))
    if opt("--json"):
        json.dump(rep.rows, open(opt("--json"), "w"), indent=1)
    sys.exit(0 if rep.ok else 1)


if __name__ == "__main__":
    main()
