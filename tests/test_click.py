"""The Metronome block: its kernel (src/sharc/click.asm) in ssim, and the model and kernel
tools/patch_click.py adds to the stock firmware."""
import ast
import math
import os
import random
import struct
from pathlib import Path

import pytest

import kit_patch_amp as kit
import nam_multi
import patch_click
import sasm
import ssim

ROOT = Path(__file__).resolve().parent.parent
I0, BI, BO = 0xB3000, 0xB8000, 0xB8100
FS = 48000


def assemble(base=0xE5000):
    return sasm.assemble(open(patch_click.ASM).read().replace('KIT_PM_BASE', f'{base:#x}'), 'click.asm')


N_CODE = len(assemble()[0][0].words)
BASE = patch_click.pm_base(N_CODE)


class Click:
    """The kernel and one instance; each call() runs one 16-sample block."""

    def __init__(self, time=0.5, db=0.0, accent=1, thru=1, in_place=False, seed=1):
        secs, self.syms = assemble(BASE)
        self.sim = ssim.Sim()
        self.sim.strict_cbufen = True
        self.sim.load(secs)
        self.rnd = random.Random(seed)
        self.out_buf = BI if in_place else BO
        self.knobs(time, db, accent, thru)

    def knobs(self, time=None, db=None, accent=None, thru=None):
        for pid, v in ((5, None if time is None else ssim.f2b(time)), (6, None if db is None else ssim.f2b(db)),
                       (7, accent), (8, thru)):
            if v is not None:
                self.sim.wr(I0 + pid, v)

    def call(self, block=None):
        sim = self.sim
        for k in range(16):
            sim.wr(BI + k, ssim.f2b(block[k] if block else 0.0))
        for r in range(16):
            sim.setR(r, self.rnd.getrandbits(32))
            sim.alt[r] = self.rnd.getrandbits(32)
        keep = [c for c in range(0x10, 0x50) if c not in (0x10, 0x11, 0x12, 0x40, 0x41, 0x42)]
        for c in keep:
            sim.set(c, self.rnd.getrandbits(8) or 1 if 0x30 <= c < 0x40 else self.rnd.getrandbits(32) & 0xFFFFF)
        for c, v in ((0x10, I0), (0x11, BI), (0x12, self.out_buf)):
            sim.set(c, v)
        sim.u[ssim.U_MODE1] |= 0x1000000
        before = [sim.R(r) for r in range(16)], list(sim.alt[:16]), {c: sim.get(c) for c in keep}, sim.u[ssim.U_MODE1]
        sim.call(self.syms['CUSTOM_AMP_ENTRY'], limit=20_000)
        after = [sim.R(r) for r in range(16)], list(sim.alt[:16]), {c: sim.get(c) for c in keep}, sim.u[ssim.U_MODE1]
        assert after == before, 'registers changed'
        assert not sim.loops and not sim.pcstk
        return [ssim.b2f(sim.rd(self.out_buf + k)) for k in range(16)]

    def run(self, samples, block=None):
        out = []
        while len(out) < samples:
            out += self.call(block)
        return out


def onsets(out, quiet=200):
    """The samples where a burst starts: non-zero after `quiet` silent samples."""
    return [i for i, x in enumerate(out) if abs(x) > 1e-6 and all(abs(y) < 1e-6 for y in out[max(0, i - quiet):i])]


def test_kernel_is_code_alone():
    assert [s.kind for s in assemble()[0]] == ['pm']


def build_py_flags():
    tree = ast.parse((ROOT / 'build.py').read_text())
    kernel = next(ast.literal_eval(n.value) for n in tree.body
                  if isinstance(n, ast.Assign) and getattr(n.targets[0], 'id', None) == 'KERNEL')
    return kernel['HX_Stomp'][1:]


def test_nam_layout_is_that_of_the_kernel_build_py_builds():
    with nam_multi.flags(build_py_flags()):
        _, built = nam_multi.build(3)
    lay = patch_click.nam_layout()
    assert (lay.n_code, lay.n_cold, lay.cold_pm, lay.b3_to) == (built.n_code, built.n_cold, built.cold_pm, built.b3_to)
    assert not nam_multi.MIDQ


def test_nam_layout_follows_build_py_flags():
    assert patch_click.nam_layout().cold_pm != nam_multi.layout([]).cold_pm


def test_kernel_sits_between_nam_slots_and_cold_code():
    lay = patch_click.nam_layout()
    assert nam_multi.NW3 + (BASE - nam_multi.NW3) * 3 // 2 >= lay.b3_to
    assert BASE + N_CODE + (N_CODE & 1) == lay.cold_pm


@pytest.mark.parametrize('time', [0.1, 0.125, 0.1234])
def test_a_beat_every_time_seconds_from_the_first_sample(time):
    beat = round(time * FS)
    out = Click(time=time).run(3 * beat + 16)
    assert onsets(out) == [0, beat, 2 * beat, 3 * beat]


def test_a_shorter_beat_applies_at_once():
    c = Click(time=1.0)
    out = c.run(FS // 2)                         # half a second into a 1 s beat
    c.knobs(time=0.25)
    out += c.run(FS)
    assert onsets(out) == [0, FS // 2, FS // 2 + FS // 4, FS // 2 + FS // 2, FS // 2 + 3 * FS // 4]


def test_a_longer_beat_counts_from_the_last_one():
    c = Click(time=0.25)
    out = c.run(FS // 8)                         # an eighth of a second into a quarter-second beat
    c.knobs(time=0.5)
    out += c.run(FS)
    assert onsets(out) == [0, FS // 2, FS]


@pytest.mark.parametrize('time', [0.0, 0.01])
def test_the_beat_is_at_least_100_ms(time):
    out = Click(time=time).run(2 * 4800 + 16)
    assert onsets(out) == [0, 4800, 9600]


@pytest.mark.parametrize('time', [8.0, 20.0])
def test_the_beat_is_at_most_8_s(time):
    c = Click(time=time)
    c.sim.wr(I0 + 20, 8 * FS - 32)               # (state: 8 s less 32 samples since the last beat)
    c.sim.wr(I0 + 26, 1)
    assert onsets(c.run(64), quiet=32) == [32]


def freq(burst):
    """The burst's frequency from its zero crossings."""
    z = [i for i in range(1, len(burst)) if (burst[i - 1] < 0) != (burst[i] < 0)]
    return FS / 2 / ((z[-1] - z[0]) / (len(z) - 1))


@pytest.mark.parametrize('accent, downbeats', [(1, []), (4, [0, 4, 8]), (3, [0, 3, 6, 9])])
def test_the_downbeat_of_each_bar_is_higher(accent, downbeats):
    out = Click(time=0.1, accent=accent).run(12 * 4800)
    f = [freq(out[i:i + 480]) for i in onsets(out)]
    assert len(f) == 12
    assert [k for k, x in enumerate(f) if x == pytest.approx(2000, rel=0.02)] == downbeats
    assert all(x == pytest.approx(1000, rel=0.02) for k, x in enumerate(f) if k not in downbeats)


def test_the_burst_is_a_half_scale_sine_with_a_6_ms_decay():
    out = Click(time=1.0).run(FS // 2)
    w = 2 * math.pi * 1000 / FS
    want = [0.5 * math.sin(w * (n + 2)) * math.exp(-n / 288) for n in range(2400)]
    assert out[:2400] == pytest.approx(want, abs=2e-4)
    assert max(abs(x) for x in out[FS // 4:]) < 1e-6


@pytest.mark.parametrize('db', [-60.0, -20.0, -6.0, 3.5, 6.0])
def test_level_is_in_db(db):
    peak = lambda o: max(abs(x) for x in o)
    assert peak(Click(time=1.0, db=db).run(64)) / peak(Click(time=1.0).run(64)) == pytest.approx(10 ** (db / 20), rel=1e-3)


@pytest.mark.parametrize('in_place', [False, True])
def test_thru_passes_the_input_under_the_click(in_place):
    blk = [0.1 * math.sin(k) for k in range(16)]
    on = Click(time=0.1, in_place=in_place).run(6000, blk)
    off = Click(time=0.1, thru=0, in_place=in_place).run(6000, blk)
    assert [a - b for a, b in zip(on, off)] == pytest.approx(blk * (6000 // 16), abs=1e-6)
    assert off[4000:4016] == pytest.approx([0.0] * 16, abs=1e-6)


# ---- the firmware tools/patch_click.py builds (from the stock file: the click needs nothing else)

def stock():
    path = os.environ.get('HX_STOMP_HXF')
    if not path:
        pytest.skip('HX_STOMP_HXF is not set')
    data, _ = kit.load_l6ia_from_any(path)
    return data


@pytest.fixture(scope='module')
def built():
    data = stock()
    out, info = patch_click.add_click(data, log=lambda *a: None)
    return data, out, info


def blob_words(l6ia_bytes, index):
    e4 = kit.get_entry_swapped(l6ia_bytes, 4)
    w4 = struct.unpack('<%dI' % (len(e4) // 4), e4)
    d = w4[3]
    ln, off = w4[d + 2 * index], w4[d + 2 * index + 1]
    return list(w4[off:off + ln])


def pmap(b):
    """A blob's parameter map: (nodes {id: (op, n_out, state words, data, is_input)}, edges, slot map)."""
    pm = b[b[6]:b[6] + b[7]]
    a, c, dd = pm[0], pm[4], pm[6]
    nodes = {}
    for k in range(pm[18]):
        n = pm[a + 10 * k:a + 10 * k + 10]
        nodes[n[2]] = (n[3], n[4], n[5], tuple(pm[n[0]:n[0] + n[6]]), n[8])
    edges = [tuple(pm[c + 4 * j:c + 4 * j + 4]) for j in range(pm[20])]
    slots = {pm[dd + 4 * j + 2]: pm[dd + 4 * j] for j in range(pm[21])}
    return pm, nodes, edges, slots


def check_counts(pm, nodes, edges):
    """The header's sums, as every stock map has them (kit.nam_host_blob)."""
    inputs = sum(n[4] for n in nodes.values())
    assert pm[12] == sum(n[2] for n in nodes.values())
    assert pm[13] == pm[18] == len(nodes)
    assert pm[14] == pm[21] + sum(n[1] for n in nodes.values()) + inputs
    assert pm[15] == len(edges) + pm[21] + inputs


def sync_chain(nodes, edges, slots):
    """From Time's slot: (op, state words, data) of the nodes its value passes, with the
    ports TempoSync1 (slot 11) and SyncSelect1 (slot 10) enter the sync node by."""
    into = lambda dst: {(e[0], e[3]) for e in edges if e[1] == dst}
    clamp = next(e[1] for e in edges if e[0] == slots[1])
    sync = next(s for s, p in into(clamp) if p == 1)
    return (nodes[sync][0], nodes[sync][2], nodes[sync][3], into(sync) == {(slots[11], 0), (slots[10], 2)},
            nodes[clamp][0], nodes[clamp][2], nodes[clamp][3], (slots[1], 0) in into(clamp))


@pytest.mark.firmware
def test_the_map_counts_add_up_as_stock_ones(built):
    data, out, info = built
    info3 = kit.parse_entry3_full(kit.get_entry_swapped(data, 3))
    stock_pm = pmap(blob_words(data, kit.find_model(info3, patch_click.SYNC_SRC)['blob_index']))
    check_counts(*stock_pm[:3])
    check_counts(*pmap(blob_words(out, info['blob']))[:3])


@pytest.mark.firmware
def test_time_is_synced_as_on_simple_delay(built):
    data, out, info = built
    info3 = kit.parse_entry3_full(kit.get_entry_swapped(data, 3))
    _, *delay = pmap(blob_words(data, kit.find_model(info3, patch_click.SYNC_SRC)['blob_index']))
    _, nodes, edges, slots = pmap(blob_words(out, info['blob']))
    assert sync_chain(nodes, edges, slots) == sync_chain(*delay)
    assert sync_chain(nodes, edges, slots)[3] and sync_chain(nodes, edges, slots)[7]


@pytest.mark.firmware
def test_each_knob_reaches_its_pid(built):
    _, out, info = built
    b = blob_words(out, info['blob'])
    pm, nodes, edges, slots = pmap(b)
    writer = {nodes[k][3][1]: k for k in nodes if nodes[k][0] == 1}
    assert set(writer) == {5, 6, 7, 8}
    assert all(nodes[writer[p]][3] == (0x0e, p, 1) for p in writer)
    assert b[0x0e:0x10] == [1, 2]                         # writers' path: member 1
    clamp = next(k for k in nodes if nodes[k][0] == 0x54)
    src = {e[1]: e[0] for e in edges}
    assert src[writer[5]] == clamp
    assert (src[writer[6]], src[writer[7]], src[writer[8]]) == (slots[2], slots[3], slots[4])


@pytest.mark.firmware
def test_the_model_and_its_knobs(built):
    _, out, info = built
    m = kit.parse_entry3_full(kit.get_entry_swapped(out, 3))['models'][info['model_id']]
    assert (m['name'], m['displayName']) == (patch_click.NAME, 'Metronome')
    assert 'category' not in m['meta'] and m['meta']['displayParamCount'] == '4'     # block category 0x19: features/metronome.py
    p = {q['name']: q for q in m['params']}
    assert [(q['name'], q['slot'], q['type']) for q in m['params']] == [
        ('Time', 1, 3), ('Level', 2, 3), ('Accent', 3, 2), ('Thru', 4, 1), ('SyncSelect1', 10, 2), ('TempoSync1', 11, 1)]
    assert (p['Time']['meta']['sync'], p['Time']['meta']['coupledIndex'], p['Time']['meta']['toggleSelectIndex']) == \
        ('1', '10', '11')
    assert p['SyncSelect1']['meta']['persistent'] == 'note' and p['SyncSelect1']['meta']['6'] == '1/4'
    word = lambda x: struct.unpack('<I', struct.pack('<f', x))[0]
    assert (word(p['SyncSelect1']['default']), word(p['TempoSync1']['default'])) == (6, 1)   # 1/4, synced
    assert p['Time']['default'] == 0.5 and (p['Level']['min'], p['Level']['max'], p['Level']['default']) == (-60.0, 6.0, -14.0)
    assert p['Accent']['meta']['1'] == 'Off' and p['Accent']['meta']['12'] == '12'
    assert word(p['Thru']['default']) == 1


@pytest.mark.firmware
def test_entry0_shows_four_knobs_and_names_preset_id_181(built):
    _, out, info = built
    e0 = kit.get_entry_swapped(out, 0)
    segs = kit._parse_e0_segments(e0)
    A = kit.e0_device(segs)
    rd = lambda va, n: e0[kit._e0_vaddr_to_foff(segs, va, n):kit._e0_vaddr_to_foff(segs, va, n) + n]
    u32 = lambda va: struct.unpack('<I', rd(va, 4))[0]
    t2, (_, n2) = u32(A.TAB2_BASE_PTR), kit._decode_thumb_movw(rd(A.TAB2_CNT_INSN, 4))
    assert struct.unpack('<5I', rd(t2 + 44 * (n2 - 1) + 24, 20)) == (4, 6, 6, 0, 0)
    t1, (_, n1) = u32(A.TAB1_BASE_PTRS[0]), kit._decode_thumb_movw(rd(A.TAB1_CNT_INSN, 4))
    assert struct.unpack('<IHHI', rd(t1 + 12 * (n1 - 1), 12))[1:] == (181, 0, patch_click.DSP_COST)


def browser(l6ia_bytes):
    """Entry 0's model browser: {category: [(folder name, [(btype, model name index, display name)])]}."""
    e0 = kit.get_entry_swapped(l6ia_bytes, 0)
    segs = kit._parse_e0_segments(e0)
    A = kit.e0_device(segs)
    rd = lambda va, n: e0[kit._e0_vaddr_to_foff(segs, va, n):kit._e0_vaddr_to_foff(segs, va, n) + n]
    u32 = lambda va: struct.unpack('<I', rd(va, 4))[0]
    out = {}
    for cat in range(kit.E0_BLIST_SLOTS // 4):
        folders = []
        for sub in range(u32(A.SUBCAT_CNT + 4 * cat)):
            lp, lc = u32(A.BLIST_PTR_TAB + 4 * (4 * cat + sub)), u32(A.BLIST_CNT_TAB + 4 * (4 * cat + sub))
            items = [rd(lp + 48 * k, 48) for k in range(lc if lp else 0)]
            folders.append((rd(A.SUBCAT_NAMES + 104 * cat + 26 * sub, 26).rstrip(b'\0').decode(),
                            [(*struct.unpack_from('<II', it), it[14:40].rstrip(b'\0').decode()) for it in items]))
        out[cat] = folders
    return out


@pytest.mark.firmware
def test_the_browser_lists_it_in_a_metronome_folder_under_looper(built):
    data, out, info = built
    before, after = browser(data), browser(out)
    name_idx = kit.parse_entry3_full(kit.get_entry_swapped(out, 3))['models'][info['model_id']]['words'][2]
    assert after[18] == before[18] + [('Metronome', [(1, name_idx, 'Metronome')])]   # a plain effect, not a looper
    assert {c: f for c, f in after.items() if c != 18} == {c: f for c, f in before.items() if c != 18}


def ldr_blocks(l6ia_bytes):
    """Entry 2's INIT blocks before FINAL_INIT: (tag, address, payload words)."""
    entries = kit.l6ia.parse(l6ia_bytes)
    raw = l6ia_bytes[entries[2]['payload_off']:entries[2]['payload_off'] + entries[2]['payload_len']]
    w = struct.unpack('<%dI' % (len(raw) // 4), raw)
    size = {5: lambda c: ((c + 1) & ~1) * 3 // 2, 4: lambda c: c, 3: lambda c: (c + 1) // 2,
            6: lambda c: c * 2, 10: lambda c: c, 9: lambda c: c}
    i, out = 384, []
    while w[i] != 0:
        tag, cnt, addr = w[i:i + 3]
        n = size.get(tag, lambda c: 0)(cnt)
        out.append((tag, addr, w[i + 3:i + 3 + n]))
        i += 3 + n
    return out


@pytest.mark.firmware
def test_the_primitive_runs_the_kernel(built):
    _, out, info = built
    blocks = ldr_blocks(out)
    assert info['pm_base'] == BASE
    assert (4, 0x200050, (0x0128, 0x611e90, 0, 0x611ef4, 0x611ddd, BASE, 0x91, 0x0d)) in blocks
    secs, _ = assemble(BASE)
    code = next(b for t, a, b in blocks if t == 5 and a == BASE)
    words = list(secs[0].words) + [0] * (len(secs[0].words) & 1)
    raw = b''.join(int(x).to_bytes(6, 'little') for x in words)
    assert tuple(code) == struct.unpack('<%dI' % (len(raw) // 4), raw)


@pytest.mark.firmware
def test_a_second_run_is_refused(built):
    _, out, _ = built
    with pytest.raises(SystemExit, match='already in this image'):
        patch_click.add_click(out, log=lambda *a: None)
