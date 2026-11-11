"""The gain-reduction meter: the DSP wrapper (src/sharc/frame_probe.asm) in ssim, the compressor knobs (tools/patch_comp.py),
its place beside the NAM and Metronome kernels, --wrap-prim (tools/patch_amp.py), the M4 meter (src/m4/gr_meter.s) in unicorn and its feature (tools/features/gr.py)."""
import math
import os
import re
import struct
from pathlib import Path

import pytest

import features
import nam_multi
import patch_amp as pa
import patch_click
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
    src = pc.dsp_asm(0xe4850, 0xc4ef8)
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



def test_probe_opto_meter_takes_la_attack_without_one():
    """The Ampeg Opto Comp's knobs send its core only Release (pid 3): Attack stays the LA Studio Comp's 10 ms."""
    s, sym = probe()
    knobs(s, sym, 'CTRL_2710', 0x96000, 0, 0, 20)
    ctrl(s, sym, 'CTRL_2710', 0x96000, 3, f2u(100.0))
    for _ in range(64):
        block(s, sym, 'ENTRY_2710', 0x96000, 0.5)
    att, rel = u2f(s.rd(sym('LA_ATT'))), 1 - 2 * math.pi / 48 / 100
    assert u2f(s.rd(FRAME + 251)) == pytest.approx(rel ** 1024, rel=1e-3)
    assert u2f(s.rd(FRAME + 252)) == pytest.approx(att ** 512, rel=1e-2)



def test_probe_red_squeeze_meter_takes_la_times_without_any():
    """No Red Squeeze knob reaches its core: Attack and Release stay the LA Studio Comp's 10 ms and 500 ms."""
    s, sym = probe()
    knobs(s, sym, 'CTRL_2710', 0x96000, 0, 0, 20)
    for _ in range(64):
        block(s, sym, 'ENTRY_2710', 0x96000, 0.5)
    att, rel = u2f(s.rd(sym('LA_ATT'))), u2f(s.rd(sym('LA_REL')))
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


# ---- the DSP wrapper's place, beside NAM A2 Lite's kernel and the Metronome's

def dsp_ranges():
    """[start, end) normal-word ranges of the wrapper's data and code, from pc.dsp_place()."""
    dm, pm = pc.dsp_place()
    secs, _ = sasm.assemble(pc.dsp_asm(dm, pm), 'frame_probe.asm')
    (n_dm,), (n_pm,) = ([len(s.words) for s in secs if s.kind == k] for k in ('dm', 'pm'))
    return (dm, dm + n_dm), (pc.nw(pm), pc.nw(pm + n_pm + (n_pm & 1)))


def overlap(a, b):
    return a[0] < b[1] and b[0] < a[1]


def test_dsp_sits_right_above_nams_two_slots():
    lay = patch_click.nam_layout(gr=True)
    (data, code) = dsp_ranges()
    assert lay.slots == 2 and data[0] == lay.b3_to and data[1] <= code[0]
    assert not any(overlap(r, c) for r in (data, code) for c in lay.claims())


def test_dsp_sits_under_the_metronome_and_nams_cold_code():
    lay = patch_click.nam_layout(gr=True)
    click = patch_click.pm_base(patch_click.kernel_size(), lay)
    _, code = dsp_ranges()
    assert code[1] <= pc.nw(click) < pc.nw(lay.cold_pm)
    _, pm = pc.dsp_place()
    assert 0x0e302c <= pm and pc.nw(pm) + (code[1] - code[0]) <= nam_multi.NW3 + 0x8000


def test_dsp_does_not_fit_beside_three_slots():
    lay = patch_click.nam_layout(gr=False)
    (data, code) = dsp_ranges()
    assert lay.slots == 3 and lay.cold_nw - lay.b3_to < (data[1] - data[0]) + (code[1] - code[0])


def test_wraps_call_the_stock_code_the_wrapper_calls():
    _, syms = sasm.assemble(pc.dsp_asm(*pc.dsp_place()), 'frame_probe.asm')
    assert dict(pc.WRAPS) == {0x271a: syms['ORIG'], 0x2719: syms['ORIG_2719'], 0x2710: syms['ORIG_2719']}
    assert {prim for _, prim in pc.COMP_MODELS} == set(dict(pc.WRAPS))


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
@pytest.mark.parametrize('model, n', (('HD2_CompressorOptoCompMono', 1), ('HD2_CompressorOptoCompStereo', 2),
                                      ('HD2_CompressorRedSqueezeMono', 1), ('HD2_CompressorRedSqueezeStereo', 2)))
def test_0x2710_cores_write_over_their_first_input(model, n):
    """The Opto's and Red Squeeze's node trees run 0x2710 on (audio, sidechain), its output over the audio, before the dry mix."""
    data = stock_l6ia()
    e3, e4 = pa.get_entry_swapped(data, 3), pa.get_entry_swapped(data, 4)
    m = pa.find_model(pa.parse_entry3_full(e3), model)
    w4 = struct.unpack(f'<{len(e4) // 4}I', e4)
    b, b0 = pa.entry4_blob.blob(w4, m['blob_index']), pa.entry4_blob.blob(w4, 0)
    pmw = b[b[6]:b[6] + b[7]]
    nodes = [pmw[pmw[0] + 10 * k:pmw[0] + 10 * k + 10] for k in range(pmw[18])]
    assert [(first, path is None) for path, first, _ in pc.core_paths(b, pmw, nodes, b0, 0x2710)] == [(1, 'RedSqueeze' in model)] * n


@pytest.mark.firmware
@pytest.mark.parametrize('model, slots', (('HD2_CompressorRochesterCompMono', [12]),
                                          ('HD2_CompressorRochesterCompStereo', [29, 22])))
def test_rochester_cores_are_the_deluxe_core_its_knobs_drive(model, slots):
    """The Rochester Comp runs 0x271a with no node-tree override, and Threshold, Ratio, Attack, Release and Knee reach each
    core as pids 1, 2, 3, 4 and 8, as on the Deluxe Comp, whose state the meter reads."""
    data = stock_l6ia()
    e3, e4 = pa.get_entry_swapped(data, 3), pa.get_entry_swapped(data, 4)
    m = pa.find_model(pa.parse_entry3_full(e3), model)
    w4 = struct.unpack(f'<{len(e4) // 4}I', e4)
    b, b0 = pa.entry4_blob.blob(w4, m['blob_index']), pa.entry4_blob.blob(w4, 0)
    assert all(t == 0xffffffff for _, t, _, _ in list(pa.entry4_blob.nodes(b))[1:])
    pmw = b[b[6]:b[6] + b[7]]
    nodes = [pmw[pmw[0] + 10 * k:pmw[0] + 10 * k + 10] for k in range(pmw[18])]
    cores = pc.core_paths(b, pmw, nodes, b0, 0x271a)
    assert [b[path + 1] for path, _, _ in cores] == slots
    for path, _, _ in cores:
        pids = {pmw[nd[0] + 1] for nd in nodes if nd[3] == 1 and pmw[nd[0]] == path}
        assert pids == {1, 2, 3, 4, 8}


def e2_words(data):
    e = pa.l6ia.parse(data)[2]
    raw = data[e['payload_off']: e['payload_off'] + e['payload_len']]
    return raw, list(struct.unpack(f'<{len(raw) // 4}I', raw))


@pytest.mark.firmware
def test_dsp_patch_points_each_core_and_its_control_function_at_the_wrapper():
    data = stock_l6ia()
    stock, _ = e2_words(data)
    _, words = e2_words(pc.patch_dsp(data, log=lambda *_: None))
    _, syms = sasm.assemble(pc.dsp_asm(*pc.dsp_place()), 'frame_probe.asm')
    joined = f",{','.join(map(str, words))},"
    for prim, orig in pc.WRAPS:
        block = pa.wrap_primitive(stock, f'{prim:#x}:{orig:#x}', syms[f'ENTRY_{prim:X}'],
                                  (syms[f'ORIG_CTRL_{prim:X}'], syms[f'CTRL_{prim:X}']))
        assert f",{','.join(map(str, block))}," in joined, f'{prim:#x}'


DEFAULT_E3 = 0xf0d00            # the default build's Entry 3: amps load [verified on unit]; 0xf3888 drops every amp and preamp


@pytest.fixture(scope='module')
def added_then_comp():
    """(Entry 3 after add-model, after patch_comp too): add-model has moved the string section and model table to the tail."""
    added, _ = patch_click.add_click(stock_l6ia(), log=lambda *_: None)
    return pa.get_entry_swapped(added, 3), pa.get_entry_swapped(pc.patch_comp(added, log=lambda *_: None), 3)


@pytest.mark.firmware
def test_comp_patch_puts_the_strings_back_in_the_stock_tables_place(added_then_comp):
    before, after = added_then_comp
    h0, h1 = struct.unpack_from('<10I', before, 0), struct.unpack_from('<10I', after, 0)
    assert h0[3] > pc.STOCK_E3_END and h1[3] == pc.STR_HOME and h1[6] == h0[3]
    assert len(after) < len(before) - 0x10000


@pytest.mark.firmware
def test_comp_patch_keeps_every_other_model_and_slot_list(added_then_comp):
    before, after = added_then_comp
    comps = {m for m, _ in pc.COMP_MODELS}
    view = lambda e3: [pc.models_view({'models': [m]}) for m in pa.parse_entry3_full(e3)['models'] if m['name'] not in comps]
    assert view(before) == view(after)
    assert pc.slot_lists(before) == pc.slot_lists(after)


@pytest.mark.firmware
def test_comp_patch_refuses_a_second_run(comp_patched):
    _, new = comp_patched
    with pytest.raises(AssertionError, match='has the knobs already'):
        pc.patch_comp(new, log=lambda *_: None)


# ---- the whole GR build, pinned as tests/test_firmware.py pins the default one

GR_BUILT_MD5 = {
    'HX_GR': '7f9d6aed355dd6142201064e3ea11c98',
    'HX_GR HX_CLICK': '3284dca1bb0c567822992c54f3f425ed',    # patch_click.py adds a model, which would drop knobs written before it
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
    env = {k: v for k, v in os.environ.items() if k not in ('HX_GR', 'HX_CLICK')} | {f: '1' for f in flags.split()}
    r = subprocess.run([sys.executable, str(ROOT / 'build.py'), stock, '-o', str(out), '--no-check'],
                       capture_output=True, text=True, cwd=ROOT, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    shown = 'gr, metronome, splash; Entry 7; Entry 8' if 'HX_CLICK' in flags else 'gr, splash; Entry 8'     # the Metronome's off icon; the boot picture
    assert 'ALL OK' in r.stdout and f'Entry 0: features {shown}\n' in r.stdout
    assert r.stdout.count(': Mtr Position, Mtr Direction, Mtr Thickness on slots') == len(pc.COMP_MODELS)
    assert hashlib.md5(out.read_bytes()).hexdigest() == GR_BUILT_MD5[flags]
    assert len(pa.get_entry_swapped(pa.load_l6ia_from_any(str(out))[0], 3)) <= DEFAULT_E3


def build_steps(tmp_path, monkeypatch, unit, env):
    """The commands build.py's main() runs for `unit` with `env`, each step stubbed out."""
    import hashlib
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location('customos_build', ROOT / 'build.py')
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    stock = tmp_path / 'stock.hxf'
    stock.write_bytes(b'not firmware')
    monkeypatch.setattr(build, 'STOCK_MD5', {hashlib.md5(stock.read_bytes()).hexdigest(): unit})
    for k in ('HX_GR', 'HX_CLICK'):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(build.os, 'replace', lambda *a: None)
    monkeypatch.setattr(build.os, 'remove', lambda *a: None)
    monkeypatch.setattr(sys, 'argv', ['build.py', str(stock), '-o', str(tmp_path / 'out.hxf'), '--no-check'])
    ran = []
    monkeypatch.setattr(build, 'run', lambda *a: ran.append(a[1:]) or 'ALL OK')
    build.main()
    return ran


@pytest.mark.parametrize('unit', ['HX_Stomp_XL', 'HX_Effects'])
def test_gr_is_for_the_hx_stomp_only(tmp_path, monkeypatch, unit):
    ran = build_steps(tmp_path, monkeypatch, unit, {'HX_GR': '1'})
    assert '--slots' not in next(a for a in ran if a[0] == 'tools/sharc/nam_multi.py')
    assert not any(a[0] == 'tools/patch_comp.py' for a in ran)


@pytest.mark.parametrize('env', [{}, {'HX_CLICK': '1'}])
def test_gr_keeps_nam_on_two_slots_and_patches_last(tmp_path, monkeypatch, env):
    ran = build_steps(tmp_path, monkeypatch, 'HX_Stomp', {'HX_GR': '1'} | env)
    kernel = next(a for a in ran if a[0] == 'tools/sharc/nam_multi.py')
    assert kernel[kernel.index('--slots') + 1] == '2'
    patch = next(a for a in ran if a[:2] == ('tools/patch_amp.py', 'patch'))
    assert '--wrap-prim' not in patch and patch[patch.index('--asm') + 1].endswith('nam_lite.asm')
    assert [a[0] for a in ran][-3:] == ['tools/patch_comp.py', 'tools/l6ia_verify.py', 'tools/hxf.py']


def test_without_gr_nam_keeps_three_slots(tmp_path, monkeypatch):
    ran = build_steps(tmp_path, monkeypatch, 'HX_Stomp', {})
    assert '--slots' not in next(a for a in ran if a[0] == 'tools/sharc/nam_multi.py')


# ---- the feature: its hooks on the stock firmware

@pytest.mark.firmware
def test_gr_feature_chains_its_three_hooks():
    import features.gr as gr
    e0 = pa.get_entry_swapped(stock_l6ia(), 0)
    mods = features.load()
    others = lambda n: pa.get_entry_swapped(stock_l6ia(), n)     # the boot picture reads Entry 8
    plain, _ = pm.menu_entry0(e0, mods, {}, others=others)
    new, on = pm.menu_entry0(e0, mods, {'HX_GR': '1'}, others=others)
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
LOCK, UNLOCK = 0x28e24970, 0x28e24ae8
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
        m.stub(LOCK)
        m.stub(UNLOCK)

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
        self.call('layout')                             # the paint that the frame's redraw request brings

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


@pytest.mark.parametrize('pos', range(5))
def test_m4_widgets_change_only_in_the_paint_under_the_widget_lock(m4emu, pos):
    """The frame runs on the DSP stream's thread: it only records the layout, and the paint applies it inside one lock and unlock."""
    m = Meter(m4emu)
    widget_calls = (LOCK, UNLOCK) + SETTERS
    for window, b in ((1, 10 ** (-8.5 / 20)), (2, 10 ** (-20 / 20)), (3, 1.0)):
        m.frame(1.0, b, window=window, pos=pos)
        seq = [at for at, _ in m.m.log if at in widget_calls]
        assert seq[0] == LOCK and seq[-1] == UNLOCK and seq.count(LOCK) == seq.count(UNLOCK) == 1
        assert [at for at, _ in m.m.log if at in (GET_VALUE, LOCK)] == [GET_VALUE, LOCK], 'the setting is read outside the lock'
    m.m.log.clear()
    w = [0] * 256
    w[200], w[218], w[216], w[217], w[250] = 0xf00d600d, rot16(0x6B000000 | pos << 16 | 20), swapped(1.0), swapped(0.1), 9
    m.m.write(FRAME_VA, struct.pack('<256I', *w))
    m.call('frame', 0, FRAME_VA)
    assert not [at for at, _ in m.m.log if at in widget_calls], 'the frame calls no setter and takes no lock'
    assert m.word('data', 4) == 1 or m.m.calls(REDRAW), 'a changed layout asks for a repaint'


def test_m4_shown_word_says_whether_the_meter_shows(m4emu):
    """The breathing line reads data + gr.SHOWN (tools/features/breathing_line.py): nonzero while the meter shows."""
    import features.gr as gr
    m = Meter(m4emu)
    m.frame(1.0, 0.5, window=1, pos=1)
    assert m.word('data', gr.SHOWN // 4) == 1
    m.frame(1.0, 0.5, window=2, pos=1, thk=0)
    assert m.word('data', gr.SHOWN // 4) == 0
    m.frame(1.0, 0.5, window=3, pos=0)
    assert m.word('data', gr.SHOWN // 4) == 1
    m.frame(1.0, 0.5, window=4, knobs=False)
    assert m.word('data', gr.SHOWN // 4) == 0


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
