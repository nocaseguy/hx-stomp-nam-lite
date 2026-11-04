"""The gain-reduction meter: the DSP wrapper (src/sharc/frame_probe.asm) in ssim, the compressor knobs (tools/patch_comp.py),
--wrap-prim (tools/patch_amp.py), the M4 meter (src/m4/gr_meter.s) in unicorn and its feature (tools/features/gr.py)."""
import math
import os
import re
import struct
from pathlib import Path

import pytest

import features
import patch_amp as pa
import patch_comp as pc
import patch_menu as pm
import sasm
import ssim

ROOT = Path(__file__).resolve().parent.parent
f2u = ssim.f2b


def u2f(u):
    return struct.unpack('<f', struct.pack('<I', u))[0]


# ---- the DSP wrapper, in ssim

CORE, CTRL, FRAME = 0x90100, 0x90300, 0xa0000           # the stand-in core and control function; one frame, the whole scan
IN1, OUT, IN3, PMW = 0x7000, 0x7100, 0x7200, 0x7300     # the core's buffers (I1, I2, I3) and pm words (I8)
SCALE = 0.25                                            # the stand-in core: I2 = I1 * SCALE


def probe():
    """(sim, symbol lookup) of frame_probe.asm, with a stand-in core and control function and the scan over one frame."""
    src = (ROOT / 'src/sharc/frame_probe.asm').read_text()
    for k, v in (('ORIG', CORE), ('ORIG_2719', CORE), ('ORIG_CTRL_271A', CTRL), ('ORIG_CTRL_2719', CTRL),
                 ('ORIG_CTRL_2710', CTRL), ('SCAN_A', FRAME), ('SCAN_B', FRAME + 256), ('SCAN_C', FRAME + 256),
                 ('SCAN_D', FRAME + 256)):
        src, n = re.subn(r'(\.equ %s,\s*)0x[0-9a-fA-F]+' % k, r'\g<1>%#x' % v, src)
        assert n == 1, k
    ret = 'fc_ret:\n    I12 = DM(M7, I6);\n    JUMP (M14, I12) (DB);\n    NOP;\n    RFRAME;'
    assert ret in src
    src = src.replace(ret, 'fc_ret:\n    RTS;')     # the C return needs the caller's frame
    src += f"""
.section dm 0x6f00
FAKE_CTRL: .space 1
.section pm {CORE:#x}
FAKE_CORE:
    I4 = I1;
    I5 = I2;
    R2 = {f2u(SCALE):#x};
    LCNTR = 16, DO fk UNTIL LCE;
      F0 = DM(I4, 1);
      F0 = F0 * F2;
fk:   DM(I5, 1) = F0;
    RTS;
.section pm {CTRL:#x}
    R0 = 0x777;
    DM(FAKE_CTRL) = R0;
    RTS;
"""
    secs, syms = sasm.assemble(src, 'frame_probe_test')
    s = ssim.Sim()
    s.load(secs)
    s.wr(FRAME, 0xFACEF00D)
    s.wr(FRAME + 255, 0xD00FECAF)
    return s, lambda n: syms.get(n, syms.get(n.lower()))


def ctrl(s, sym, entry, state, pid, value):
    """The control function as the framework calls it: pid R4, a pointer to the value R8, the state R12 (its first word the core's I0)."""
    s.wr(0x5000, value)
    s.wr(0x6000, state)
    s.u[4], s.u[8], s.u[12], s.u[3] = pid, 0x5000, 0x6000, 0x1234
    s.call(sym(entry))
    assert s.u[3] == 0x1234


def block(s, sym, entry, state, peak, gain=1.0):
    """One block of 16 samples peaking at `peak` through the wrapped core."""
    for k in range(16):
        s.wr(IN1 + k, f2u(peak * (-1) ** k * (1 - k / 32)))
        s.wr(IN3 + k, f2u(peak))
        s.wr(OUT + k, 0)
    s.wr(PMW + 1, f2u(gain))
    s.u[0x10], s.u[0x11], s.u[0x12], s.u[0x13], s.u[0x18] = state, IN1, OUT, IN3, PMW
    s.call(sym(entry))


def knobs(s, sym, entry, state, pos, dir_, thk):
    for pid, v in ((100, pos), (101, dir_), (102, thk)):
        ctrl(s, sym, entry, state, pid, v)


def test_probe_keeps_the_core_output_and_registers():
    """The wrapped core's output and the registers it returns are those of the core called alone."""
    alone, sym = probe()
    for r in range(8):
        alone.u[r] = 0x100 + r
    block(alone, sym, 'FAKE_CORE', 0x96000, 0.5)
    wrapped, sym = probe()
    knobs(wrapped, sym, 'CTRL_2719', 0x96000, 0, 0, 20)
    for r in range(8):
        wrapped.u[r] = 0x100 + r
    block(wrapped, sym, 'ENTRY_2719', 0x96000, 0.5)
    assert [wrapped.rd(OUT + k) for k in range(16)] == [alone.rd(OUT + k) for k in range(16)]
    assert [wrapped.rd(IN1 + k) for k in range(16)] == [alone.rd(IN1 + k) for k in range(16)]
    assert [wrapped.u[r] for r in range(8)] == [alone.u[r] for r in range(8)]


def test_probe_window_peaks_and_frame_tail():
    """After 64 blocks the frame carries the window peaks of input (216) and output (217), the knobs (218) and the window count (250)."""
    s, sym = probe()
    knobs(s, sym, 'CTRL_2719', 0x96000, 2, 1, 20)
    for k in range(64):
        block(s, sym, 'ENTRY_2719', 0x96000, 0.5 if k != 40 else 0.8)
    assert s.rd(FRAME + 200) == 0x600DF00D
    assert u2f(s.rd(FRAME + 216)) == pytest.approx(0.8)
    assert u2f(s.rd(FRAME + 217)) == pytest.approx(0.8 * SCALE)
    assert s.rd(FRAME + 218) == 0x6B020114
    assert s.rd(FRAME + 250) == 1
    assert s.rd(FRAME + 255) == 0xD00FECAF


def test_probe_measures_only_the_metered_core():
    """Another core's blocks (another compressor, an amp sharing the core) move no window; the meter goes off 64 blocks after its core."""
    s, sym = probe()
    knobs(s, sym, 'CTRL_2719', 0x96000, 0, 0, 20)
    for _ in range(65):
        block(s, sym, 'ENTRY_2719', 0x97000, 0.5)
    assert s.rd(FRAME + 250) == 0
    assert s.rd(FRAME + 218) == 0
    block(s, sym, 'ENTRY_2719', 0x96000, 0.5)
    assert s.rd(FRAME + 218) == 0x6B000014


def test_probe_meter_follows_the_last_core_switched_on():
    s, sym = probe()
    knobs(s, sym, 'CTRL_271A', 0x96000, 1, 0, 10)
    knobs(s, sym, 'CTRL_271A', 0x97000, 3, 0, 5)
    assert s.rd(sym('GR_CORE')) == 0x97000
    ctrl(s, sym, 'CTRL_271A', 0x97000, 102, 0)
    assert s.rd(sym('GR_CORE')) == 0x96000
    assert s.rd(sym('FAKE_CTRL')) == 0, 'the GR pids reach the stock control function'
    ctrl(s, sym, 'CTRL_271A', 0x97000, 5, 0)
    assert s.rd(sym('FAKE_CTRL')) == 0x777, 'a stock pid does not reach the stock control function'


def test_probe_deluxe_reads_the_core_gain():
    """For the Deluxe Comp the window is A = 1 / the core's gain (its pm word 1), B = 1."""
    s, sym = probe()
    knobs(s, sym, 'CTRL_271A', 0x96000, 0, 0, 20)
    for _ in range(64):
        block(s, sym, 'ENTRY_271A', 0x96000, 0.5, gain=0.25)
    assert u2f(s.rd(FRAME + 216)) == pytest.approx(4.0, rel=1 / 64)
    assert u2f(s.rd(FRAME + 217)) == 1.0


def test_probe_kinky_meter_uses_its_attack_and_release():
    """Kinky Comp Attack (pid 2) and Release (3) in ms become the window's coefficients: words 252 and 251."""
    s, sym = probe()
    knobs(s, sym, 'CTRL_2710', 0x96000, 0, 0, 20)
    ctrl(s, sym, 'CTRL_2710', 0x96000, 2, f2u(10.0))
    ctrl(s, sym, 'CTRL_2710', 0x96000, 3, f2u(100.0))
    assert s.rd(sym('FAKE_CTRL')) == 0x777, 'Attack and Release reach the stock control function'
    for _ in range(64):
        block(s, sym, 'ENTRY_2710', 0x96000, 0.5)
    att, rel = 1 - 2 * math.pi / 48 / 10, 1 - 2 * math.pi / 48 / 100
    assert u2f(s.rd(FRAME + 251)) == pytest.approx(rel ** 1024, rel=1e-3)
    assert u2f(s.rd(FRAME + 252)) == pytest.approx(att ** 512, rel=1e-2)


# ---- --wrap-prim

def registry(entries):
    """An Entry 2 with an LDR block of tag 4 at 0x200000 holding 8-word primitive records."""
    words = [0] * 384 + [4, 8 * len(entries), 0x200000] + [w for e in entries for w in e] + [0, 0, 0]
    return struct.pack(f'<{len(words)}I', *words)


def test_wrap_prim_points_the_entry_at_ours():
    e2 = registry([[0x2700, 0, 0, 0, 0x600000, 0x8d000, 0, 0], [0x271a, 0, 0, 0, 0x6100bd, 0x8d9c9, 0, 0]])
    out = pa.wrap_primitive(e2, '0x271a:0x8d9c9', 0xc4ef8, ctrl=(0x6100bd, 0xc5000))
    assert out == pa.pack_init_l32(0x200008, [0x271a, 0, 0, 0, 0xc5000, 0xc4ef8, 0, 0])


def test_wrap_prim_refuses_a_stock_address_that_differs():
    e2 = registry([[0x271a, 0, 0, 0, 0x6100bd, 0x8d9c9, 0, 0]])
    with pytest.raises(SystemExit, match='process address'):
        pa.wrap_primitive(e2, '0x271a:0x8d342', 0xc4ef8)
    with pytest.raises(SystemExit, match='control function'):
        pa.wrap_primitive(e2, '0x271a:0x8d9c9', 0xc4ef8, ctrl=(0x60cc71, 0xc5000))
    with pytest.raises(SystemExit, match='not in the registry'):
        pa.wrap_primitive(e2, '0x2719:0x8d342', 0xc4ef8)


# ---- the compressor knobs, on the stock firmware

def stock_l6ia():
    stock = os.environ.get('HX_STOMP_HXF')
    if not stock:
        pytest.skip('HX_STOMP_HXF is not set')
    return pa.load_l6ia_from_any(stock)[0]


@pytest.fixture(scope='module')
def comp_patched():
    data = stock_l6ia()
    return data, pc.patch_comp(data, log=lambda *_: None)


@pytest.mark.firmware
@pytest.mark.parametrize('model, prim', pc.COMP_MODELS)
def test_comp_models_get_the_three_knobs(comp_patched, model, prim):
    data, new = comp_patched
    old_m = pa.find_model(pa.parse_entry3_full(pa.get_entry_swapped(data, 3)), model)
    m = pa.find_model(pa.parse_entry3_full(pa.get_entry_swapped(new, 3)), model)
    n = len(old_m['params'])
    assert [p['slot'] for p in m['params']] == list(range(1, n + 4))
    assert [p['name'] for p in m['params'][n:]] == [k[0] for k in pc.GR_KNOBS]
    # integer lists: their raw words, which the parser reads as floats
    assert [tuple(f2u(p[k]) for k in ('min', 'max', 'default')) for p in m['params'][n:]] == [(0, len(k[3]) - 1, k[4]) for k in pc.GR_KNOBS]
    assert [p['name'] for p in m['params'][:n]] == [p['name'] for p in old_m['params']]

    e4 = pa.get_entry_swapped(new, 4)
    w4 = struct.unpack(f'<{len(e4) // 4}I', e4)
    b = pa.entry4_blob.blob(w4, m['blob_index'])
    po, pl, pin, npin = b[6], b[7], b[10], b[11]
    pmw = b[po:po + pl]
    cores = pc.core_paths(b, pmw, [pmw[pmw[0] + 10 * k:pmw[0] + 10 * k + 10] for k in range(pmw[18])],
                          pa.entry4_blob.blob(w4, 0), prim)
    for pid in (100, 101, 102):     # a writer {the first core's path, pid, 1} for each knob
        assert any(tuple(pmw[k:k + 3]) == (cores[0][0], pid, 1) for k in range(len(pmw) - 2)), pid
    oris = [b[pin + 4 * k:pin + 4 * k + 4] for k in range(npin) if b[pin + 4 * k + 1] == pc.GR_PID + 3]
    assert len(oris) == len(cores) >= 1, 'one output record (pid 103) per compressor core'
    assert not pa.pmap_slots_without_param(e4, m['blob_index'], m['params'])


@pytest.mark.firmware
def test_kinky_core_is_0x2710_in_the_node_tree():
    """The Kinky Comp's composite says 0x2719, its node tree 0x2710: patch_comp finds its core only as 0x2710."""
    data = stock_l6ia()
    e3, e4 = pa.get_entry_swapped(data, 3), pa.get_entry_swapped(data, 4)
    m = pa.find_model(pa.parse_entry3_full(e3), 'HD2_CompressorKinkyCompMono')
    w4 = struct.unpack(f'<{len(e4) // 4}I', e4)
    b, b0 = pa.entry4_blob.blob(w4, m['blob_index']), pa.entry4_blob.blob(w4, 0)
    pmw = b[b[6]:b[6] + b[7]]
    nodes = [pmw[pmw[0] + 10 * k:pmw[0] + 10 * k + 10] for k in range(pmw[18])]
    assert pc.core_paths(b, pmw, nodes, b0, 0x2710)
    assert pc.core_paths(b, pmw, nodes, b0, 0x2719) == []


@pytest.mark.firmware
def test_comp_patch_refuses_a_second_run(comp_patched):
    _, new = comp_patched
    with pytest.raises(AssertionError, match='has the knobs already'):
        pc.patch_comp(new, log=lambda *_: None)


# ---- the whole GR build, pinned as tests/test_firmware.py pins the default one

GR_BUILT_MD5 = {                # HX_GR alone has the meter's M4 side and knobs; the DSP side needs HX_FRAMEPROBE too
    'HX_GR': '7062017a42931abcd059b5141493d602',
    'HX_GR HX_FRAMEPROBE': '05837d5cc9685044711e7cf6c1fee4fd',
}


@pytest.mark.firmware
@pytest.mark.parametrize('flags', GR_BUILT_MD5)
def test_gr_build(tmp_path, flags):
    import hashlib
    import subprocess
    import sys
    stock = os.environ.get('HX_STOMP_HXF')
    if not stock:
        pytest.skip('HX_STOMP_HXF is not set')
    out = tmp_path / 'gr.hxf'
    env = {k: v for k, v in os.environ.items() if k not in ('HX_GR', 'HX_FRAMEPROBE')} | {f: '1' for f in flags.split()}
    r = subprocess.run([sys.executable, str(ROOT / 'build.py'), stock, '-o', str(out), '--no-check'],
                       capture_output=True, text=True, cwd=ROOT, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'ALL OK' in r.stdout and 'CustomOS (tuner, gr)' in r.stdout
    assert hashlib.md5(out.read_bytes()).hexdigest() == GR_BUILT_MD5[flags]


# ---- the feature: its hooks on the stock firmware

@pytest.mark.firmware
def test_gr_feature_chains_its_three_hooks():
    import features.gr as gr
    e0 = pa.get_entry_swapped(stock_l6ia(), 0)
    mods = features.load()
    plain, _ = pm.menu_entry0(e0, mods, {})
    new, on = pm.menu_entry0(e0, mods, {'HX_GR': '1'})
    assert 'gr' in [features.name(m) for m in on]
    segs, psegs = pa._parse_e0_segments(new), pa._parse_e0_segments(plain)

    def u32(e, s, va):
        o = pa._e0_vaddr_to_foff(s, va, 4)
        return struct.unpack('<I', e[o:o + 4])[0]

    for lit, stock in ((gr.RX_CB_LIT, gr.RX_CB), (gr.HOME_PAINT_LIT, gr.HOME_PAINT)):
        assert u32(plain, psegs, lit) == stock
        stub = u32(new, segs, lit)
        assert stub != stock and stub & 1
    o = pa._e0_vaddr_to_foff(segs, gr.HOME_CTOR_CALL, 4)
    assert new[o:o + 4] != pm.bl(gr.HOME_CTOR_CALL, gr.HOME_CTOR)


# ---- the M4 meter, in unicorn

MODULE, FRAME_VA = 0x28e60000, 0x28e80000                # where the module and a frame sit in the emulator's SDRAM
SET_COLOR, SET_POS, SET_SIZE, GET_VALUE, REDRAW = 0x28e24b98, 0x28e24af0, 0x28e24b28, 0x28e1f844, 0x28db8508
SETTERS = (SET_COLOR, SET_POS, SET_SIZE)
DIVIDER = 0x2812a594
OCT = 256 / (20 * math.log10(2))                         # 1/256 octaves per dB


def rot16(u):
    """A word as the M4 reads it from a frame: halfwords swapped."""
    return ((u << 16) | (u >> 16)) & 0xffffffff


def swapped(x):
    return rot16(f2u(x))


class Meter:
    """gr_meter.s in tests/m4emu.py: the stock widget setters write the widget as the firmware's do."""

    def __init__(self, m4emu):
        code, self.sym = m4emu.assemble('src/m4/gr_meter.s', [], {})
        m = self.m = m4emu.M4(code, MODULE)
        m.stub(SET_COLOR, lambda m: m.u32(m.reg('r0'), m.reg('r1')))
        m.stub(SET_POS, lambda m: m.write(m.reg('r0') + 4, struct.pack('<2I', m.reg('r1'), m.reg('r2'))))
        m.stub(SET_SIZE, lambda m: m.write(m.reg('r0') + 12, struct.pack('<2I', m.reg('r1'), m.reg('r2'))))
        m.stub(GET_VALUE, lambda m: (m.u32(m.reg('r1') + 4, 0), m.reg('r0', 0)))
        m.stub(REDRAW)

    def call(self, sym, *args):
        """(r0, r2) after the module's function sym."""
        r0 = self.m.call(MODULE + self.sym[sym], *args)
        return r0, self.m.reg('r2')

    def word(self, sym, k=0):
        return self.m.u32(MODULE + self.sym[sym] + 4 * k)

    def setters(self):
        """The widget setters the last frame called."""
        return [at for at, _ in self.m.log if at in SETTERS]

    def frame(self, a_peak, b_peak, window, pos=0, dir_=0, thk=20, release=0.5, knobs=True):
        w = [0] * 256
        w[200] = 0xf00d600d
        w[218] = rot16(0x6B000000 | pos << 16 | dir_ << 8 | thk) if knobs else 0
        w[216], w[217], w[250], w[251] = swapped(a_peak), swapped(b_peak), window, swapped(release)
        self.m.write(FRAME_VA, struct.pack('<256I', *w))
        self.m.log.clear()
        self.call('frame', 0, FRAME_VA)

    def colours(self, pos):
        """The colours of the ten lights, left to right, of Top (1) or Middle (0, the divider's four segments then ours)."""
        if pos == 0:
            segs = [DIVIDER + 0x1c * k for k in range(4)] + [MODULE + self.sym['widgets'] + 0x1c * (40 + k) for k in range(6)]
        else:
            segs = [MODULE + self.sym['widgets'] + 0x1c * (10 * (pos - 1) + k) for k in range(10)]
        return [self.m.u32(s) for s in segs]


def lit(m, pos=1):
    return sum(1 for c in m.colours(pos) if c)


def test_m4_log_maths(m4emu):
    m = Meter(m4emu)
    for x in (1.0, 0.5, 0.3, 1e-3, 1.7):
        got, _ = m.call('lg', swapped(x))
        assert got == pytest.approx(256 * math.log2(x) + 32512, abs=0.14 * OCT)


@pytest.mark.parametrize('db', [0.0, 3.0, 6.0, 12.0, 30.0])
def test_m4_grdb(db, m4emu):
    m = Meter(m4emu)
    _, r2 = m.call('grdb', swapped(0.5), swapped(0.5 * 10 ** (-db / 20)))
    assert r2 == pytest.approx(min(db * OCT, 1500), abs=0.3 * OCT)


def test_m4_grdb_gate_at_minus_72_db(m4emu):
    m = Meter(m4emu)
    _, r2 = m.call('grdb', swapped(10 ** (-75 / 20)), swapped(10 ** (-80 / 20)))
    assert r2 == 0xffffffff
    _, r2 = m.call('grdb', swapped(10 ** (-70 / 20)), swapped(10 ** (-75 / 20)))
    assert r2 == pytest.approx(5 * OCT, abs=0.3 * OCT)


LIGHTS_DB = (1, 2, 3, 4, 6, 8, 10, 14, 19, 25)


def test_m4_light_table(m4emu):
    m = Meter(m4emu)
    table = struct.unpack('<10H', m.m.read(MODULE + m.sym['lights'], 20))
    assert table == tuple(round(db * OCT) for db in LIGHTS_DB)


@pytest.mark.parametrize('n', range(10))
def test_m4_light_thresholds(n, m4emu):
    """Light n + 1 comes on between 0.25 dB below its step and 0.25 dB above it, in its colour."""
    for db, lights in ((LIGHTS_DB[n] - 0.25, n), (LIGHTS_DB[n] + 0.25, n + 1)):
        m = Meter(m4emu)
        m.frame(1.0, 10 ** (-db / 20), window=1, pos=1)
        assert lit(m) == lights, db
        assert m.colours(1)[:lights] == [m.word('colours', k) for k in range(lights)]


def test_m4_reverse_fills_from_the_other_end(m4emu):
    m = Meter(m4emu)
    m.frame(1.0, 10 ** (-4.5 / 20), window=1, pos=1, dir_=1)
    assert [bool(c) for c in m.colours(1)] == [False] * 6 + [True] * 4


def test_m4_rise_is_instant_and_silence_decays_at_release(m4emu):
    m = Meter(m4emu)
    m.frame(1.0, 10 ** (-12 / 20), window=1)
    assert (m.word('data') >> 16) == pytest.approx(12 * OCT, abs=0.3 * OCT)
    m.frame(1e-5, 1e-5, window=2, release=0.5)            # below -72 dB: the reduction recovers at the Release coefficient
    assert (m.word('data') >> 16) == pytest.approx(6 * OCT, abs=0.3 * OCT)
    m.frame(1e-5, 1e-5, window=2, release=0.5)            # a repeated window changes nothing
    assert (m.word('data') >> 16) == pytest.approx(6 * OCT, abs=0.3 * OCT)


def test_m4_setters_only_on_a_change(m4emu):
    m = Meter(m4emu)
    m.frame(1.0, 10 ** (-6.5 / 20), window=1, pos=1)
    assert m.setters()
    m.frame(1.0, 10 ** (-6.5 / 20), window=2, pos=1)
    assert m.setters() == []
    m.frame(1.0, 10 ** (-8.5 / 20), window=3, pos=1)
    assert m.setters() == [SET_COLOR]


def test_m4_off_without_knobs_or_at_thickness_0(m4emu):
    m = Meter(m4emu)
    m.frame(1.0, 0.1, window=1, pos=1, thk=0)
    assert lit(m) == 0
    m.frame(1.0, 0.1, window=2, pos=1, knobs=False)
    assert lit(m) == 0


def test_m4_handlers_through_the_chain_stubs(m4emu):
    """On their shared hooks the stock callback and paint still run, once, with the hook's arguments: every erase before the
    stock paint, every draw after it, as the stock paint does."""
    import features.gr as gr
    mt = Meter(m4emu)
    m, cave, home = mt.m, 0x28e70000, 0x28e90000
    erase, draw, lock, unlock = 0x28e24b40, 0x28e24b58, 0x28e24970, 0x28e24ae8
    for fn in (gr.RX_CB, gr.HOME_PAINT, erase, draw, lock, unlock, 0x28e24b00, 0x28dc87cc):
        m.stub(fn)
    m.load(cave, pm.chain_cave(cave, gr.RX_CB & ~1, [MODULE + mt.sym['frame']], []))
    m.write(FRAME_VA, bytes(1024))
    m.call(cave, 7, FRAME_VA, 8, 9)
    assert m.calls(gr.RX_CB) == [(7, FRAME_VA, 8, 9)]

    m.log.clear()
    paint = cave + 0x100
    m.load(paint, pm.chain_cave(paint, gr.HOME_PAINT & ~1, [MODULE + mt.sym['erase']], [MODULE + mt.sym['draw']]))
    m.call(paint, 0x1234, home, 5, 6)
    order = [at for at, _ in m.log if at in (erase, draw, gr.HOME_PAINT & ~1)]
    assert order == [erase] * 46 + [gr.HOME_PAINT & ~1] + [draw] * 46
    assert m.calls(gr.HOME_PAINT) == [(0x1234, home, 5, 6)]
