#!/usr/bin/env python3
"""patch_click.py - the Metronome block: a click on every beat of the preset's tempo.

usage: patch_click.py <in .hxf | L6IA> <out .hxf | L6IA> [--donor stock.hxf]

Run after tools/patch_amp.py patch (build.py does it for HX_CLICK=1 builds). It adds:
  - the model Looper > Metronome > Metronome (Entries 0, 3, 4; preset ID 181): a copy
    of the mono effect host whose one member is the primitive 0x0128, with the knobs Time,
    Level, Accent and Thru, and Time's tempo sync (Time's note list SyncSelect1 and its
    switch TempoSync1, hidden as on every stock delay);
  - the kernel src/sharc/click.asm (Entry 2), in Block 3 between NAM A2 Lite's slots and
    its cold code, as the primitive's process function.

Time reaches the kernel as stock Simple Delay's Time reaches its delay line: its parameter
map's sync node (op 0x2a) turns the note and the tempo into seconds, a clamp node (op 0x54)
picks that or the free Time, and a writer gives it to the primitive as pid 5. The kit's
add_model has no tempo sync (kit_patch_amp.SYNC_PARAMS), so this tool lays out the
parameter map itself (click_blob) and uses the kit's Entry 0, 3 and 4 steps around it.
"""
import argparse
import importlib.util
import os
import struct
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, os.path.join(SCRIPT_DIR, 'sharc'))

import kit_patch_amp as kit
import l6ia
import nam_multi

ASM = os.path.join(SCRIPT_DIR, '..', 'src', 'sharc', 'click.asm')
NAME, DISPLAY, FOLDER = 'HD2_ClickMetronomeMono', 'Metronome', 'Metronome'
PRESET_ID = 181                     # fixed for ever: presets store it
DSP_COST = 50
CLONE = 'HD2_Tremolo60sBiasTremMono'   # a mono modulation with four knobs and a synced pair: no trails, as delays have
CATEGORY = 5                        # Modulation: the source's, so the block stays a plain effect
BROWSER = 18                        # Looper: where the browser lists it, a folder beside Mono and Stereo
HOST = 'HD2_VolPanVolMono'
PRIM = (0x0128, 0x200050)           # kit_patch_amp.UNUSED_SHARC_PRIMS' second: NAM has the first
INSTANCE = {'dm_words': 0x91, 'pm_words': 0x0d, 'sdram_words': 0}
SYNC_SRC = 'HD2_DelaySimpleDelayMono'
CLAMP = (0.00035, 8.0)              # Simple Delay's 0x54 node: Time's range
# (slot, name, source parameter or None, pid or None, type, min, max, default, meta) by
# display order. Time's meta keeps Simple Delay's coupledIndex 10 and toggleSelectIndex 11,
# so SyncSelect1 and TempoSync1 keep its slots too. Types: 3 float, 2 int, 1 bool.
ACCENT_LABELS = [('displayType', 'list'), ('1', 'Off')] + [(str(k), str(k)) for k in range(2, 13)]
PARAMS = ((1, 'Time', 'Time', 5, 3, None, None, 0.5, None),
          (2, 'Level', 'Level', 6, 3, None, None, -14.0, None),
          (3, 'Accent', None, 7, 2, 1, 12, 1, ACCENT_LABELS),
          (4, 'Thru', None, 8, 1, 0, 0, 1, [('false', 'Off'), ('true', 'On')]),
          (10, 'SyncSelect1', 'SyncSelect1', None, 2, None, None, 6, None),
          (11, 'TempoSync1', 'TempoSync1', None, 1, None, None, 1, None))
N_SHOWN = 4                         # the knobs before the synced pair (Table 2's first count)


def word(ty, v):
    return kit.f2u(v) if ty == 3 else int(v) & 0xffffffff


def click_params(e3, info):
    """PARAMS as the kit's add_model_entry3 takes them (kit.nam_params' form): a source's
    record and meta (sync meta kept), or a new one."""
    S = info['strings']
    src = kit.find_model(info, SYNC_SRC)
    out = []
    for slot, name, pname, pid, ty, mn, mx, dflt, meta in PARAMS:
        if pname:
            p = next(q for q in src['params'] if q['name'] == pname)
            assert p['type'] == ty, (pname, p['type'])
            raw = list(struct.unpack_from('<5I3I', e3, p['off']))
            pm_cnt, pm_off = raw[:2]
            meta = [(S[ks], kt, S[kv] if kt == 7 else kv)
                    for ks, kt, kv in (struct.unpack_from('<3I', e3, pm_off + 12 * k) for k in range(pm_cnt))]
        else:
            raw = [0, 0, 0, ty, 0, word(ty, mn), word(ty, mx), 0]
            meta = [('displayName', 7, name)] + [(k, 7, v) for k, v in meta]
        raw[3], raw[4], raw[7] = ty, slot, word(ty, dflt)
        out.append({'slot': slot, 'pid': pid, 'name': name, 'type': ty, 'op': kit.NAM_INPUT_OP[ty],
                    'raw': raw, 'meta': meta, 'state': name + 'State', 'default_word': raw[7]})
    return out


def click_blob(comp_id, params):
    """The model blob: kit.nam_host_blob's layout (its docstring has the format) with
    Simple Delay's sync chain for Time: TempoSync1 -> 0x2a port 0, SyncSelect1 -> 0x2a
    port 2, Time -> 0x54 port 0, 0x2a -> 0x54 port 1, 0x54 -> the writer of pid 5. The
    other knobs go straight to a writer of their pid. Edges are {src, dst, src port, dst port}."""
    n = len(params)
    by = {p['name']: k for k, p in enumerate(params)}
    writers = [p for p in params if p['pid'] is not None]
    w = len(writers)
    SYNC, CLAMPN = n, n + 1
    wn = {p['pid']: n + 2 + j for j, p in enumerate(writers)}
    nodes = n + 2 + w
    a_off = 0x18
    data_off = a_off + 10 * nodes
    sync_d, clamp_d, wr_d = data_off, data_off + 2, data_off + 4
    edges = [(by['TempoSync1'], SYNC, 0, 0), (by['SyncSelect1'], SYNC, 0, 2),
             (by['Time'], CLAMPN, 0, 0), (SYNC, CLAMPN, 0, 1), (CLAMPN, wn[5], 0, 0)]
    edges += [(by[p['name']], wn[p['pid']], 0, 0) for p in writers if p['name'] != 'Time']
    edges.sort()
    c_off = wr_d + 3 * w
    d_off = c_off + 4 * len(edges)
    e_off = d_off + 4 * n
    end = e_off + 4 * n
    sw = 2 * n + 4 + 9 + 3 * w
    n_out = n + 2
    pm = [a_off, 0, c_off, 0, c_off, 0, d_off, 0, e_off, 0, end, 0]
    pm += [sw, nodes, n + n_out + n, len(edges) + n + n, n, n]
    pm += [nodes, 0, len(edges), n, n, 0]
    for k, p in enumerate(params):
        pm += [data_off, 0, k, p['op'], 1, 2, 0, 0, 1, 0]
    pm += [sync_d, 0, SYNC, 0x2a, 1, 4, 2, 2, 0, 0]
    pm += [clamp_d, 0, CLAMPN, 0x54, 1, 9, 2, 2, 0, 0]
    for j in range(w):
        pm += [wr_d + 3 * j, 0, n + 2 + j, 1, 0, 3, 3, 3, 0, 0]
    pm += [0, 0, kit.f2u(CLAMP[0]), kit.f2u(CLAMP[1])]
    for p in writers:
        pm += [0x0e, p['pid'], 1]
    for e in edges:
        pm += list(e)
    for k, p in sorted(enumerate(params), key=lambda kp: kp[1]['slot']):
        pm += [k, k, p['slot'], 0]
    for k in range(n):
        pm += [k, k, k, 0]
    assert len(pm) == end

    v0 = 0x10
    tree = v0 + 2 * (n + w)
    pmo = tree + 4
    pin = pmo + len(pm)
    ini = pin + 4 * (n + w)
    sub = ini + 2 * (w + n + w)
    b = [3, 2, tree, 1, ini, w + n + w, pmo, len(pm), sub, 0, pin, n + w]
    b += [1, 0, 1, 2]                               # paths [0] (the root) and [2] (member 1)
    for p in params + writers:
        b += [1, p['default_word']]
    b += [0, comp_id, 0, 0]
    b += pm
    for k, p in enumerate(params):
        b += [0x0c, p['slot'], v0 + 2 * k, 1]
    for j, p in enumerate(writers):
        b += [0x0e, p['pid'], v0 + 2 * (n + j), 2]
    for j in range(w):
        b += [1, pmo + wr_d + 3 * j]
    for k in range(n + w):
        b += [1, pin + 4 * k]
    assert len(b) == sub
    return b


def replace_last_blob(e4, blob_index, words):
    """Entry 4 with blob `blob_index`, the last in the file, replaced by `words`."""
    w4 = list(struct.unpack('<%dI' % (len(e4) // 4), e4))
    d = w4[3]
    ln, off = w4[d + 2 * blob_index], w4[d + 2 * blob_index + 1]
    assert off + ln == len(w4), 'the new blob is not the last in Entry 4'
    w4 = w4[:off] + list(words)
    w4[d + 2 * blob_index] = len(words)
    w4[5] = len(w4)
    out = struct.pack('<%dI' % len(w4), *w4)
    if len(out) > kit.E4_MAX:
        raise SystemExit(f'Entry 4 would be {len(out):#x} bytes; its partition holds {kit.E4_MAX:#x}')
    return out


def nam_layout():
    """nam_multi's Layout of build.py's HX Stomp kernel, with its KERNEL['HX_Stomp'] flags."""
    spec = importlib.util.spec_from_file_location('customos_build', os.path.join(SCRIPT_DIR, '..', 'build.py'))
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    return nam_multi.layout(build.KERNEL['HX_Stomp'][1:])


def pm_base(n_insns):
    """Where the kernel goes: right under NAM A2 Lite's cold code, above its slots
    (nam_layout())."""
    lay = nam_layout()
    n = n_insns + (n_insns & 1)
    base = lay.cold_pm - n
    nw = nam_multi.NW3 + (base - nam_multi.NW3) * 3 // 2
    if nw < lay.b3_to:
        raise SystemExit(f'the click kernel ({n} instructions) does not fit between NAM\'s slots '
                         f'({lay.b3_to:#x}) and its cold code ({lay.cold_pm:#x})')
    return base


def add_click(l6ia_bytes, log=print):
    """The Metronome model and its kernel. Returns (new l6ia bytes, info dict)."""
    e0 = kit.get_entry_swapped(l6ia_bytes, 0)
    e3 = kit.get_entry_swapped(l6ia_bytes, 3)
    e4 = kit.get_entry_swapped(l6ia_bytes, 4)
    info = kit.parse_entry3_full(e3)
    if any(m['name'] == NAME for m in info['models']):
        raise SystemExit(f'{NAME} is already in this image')
    assert PRIM[0] not in kit.stock_prims_in_use(l6ia_bytes), f'primitive {PRIM[0]:#x} is in use'
    src = kit.find_model(info, CLONE)
    params = click_params(e3, info)

    hm = kit.find_model(info, HOST)
    w4 = struct.unpack('<%dI' % (len(e4) // 4), e4)
    width = kit.FX_HOST_COMPOSITES[kit.entry4_blob.top_type(kit.entry4_blob.blob(w4, hm['blob_index']))]
    assert width == 1
    kit.fx_source_check(e0, src, CATEGORY, width)
    # (the kit's own blob, replaced below, wants a pid on every parameter)
    stand_in = [dict(p, pid=p['pid'] or 0) for p in params]
    new_e4, blob, comp = kit.add_model_entry4(e4, hm['blob_index'], stand_in, PRIM[0], INSTANCE, fx=True)
    new_e4 = replace_last_blob(new_e4, blob, click_blob(comp, params))
    log(f"[+] Entry 4: Metronome blob {blob} on composite {comp:#x} (primitive {PRIM[0]:#06x})")

    # no category: block category 0x19, which tools/features/metronome.py makes Metronome, with Icon_Tempo
    drop = tuple(k for k in kit.FX_MODEL_META_DROP if k != 'displayParamCount') + ('category',)
    new_e3, model_id, _ = kit.add_model_entry3(e3, src, NAME, DISPLAY, blob, params, drop_meta=drop)
    chk = kit.parse_entry3_full(new_e3)
    m = chk['models'][model_id]
    assert m['meta'].get('displayParamCount') == str(N_SHOWN), m['meta']
    assert [(p['name'], p['slot'], p['type']) for p in m['params']] == [(p['name'], p['slot'], p['type']) for p in params]
    orphans = kit.pmap_slots_without_param(new_e4, blob, m['params'])
    assert not orphans, orphans
    log(f"[+] Entry 3: {NAME} ({DISPLAY}) = model {model_id}, blob {blob}")

    new_e0, pid, cost, _ = kit.add_model_entry0(
        e0, src['words'][2], m['words'][2], DISPLAY, preset_id=PRESET_ID, dsp_cost=DSP_COST,
        n_params=len(params), folder=(BROWSER, FOLDER), fx=True, src_category=CATEGORY)
    new_e0 = bytearray(new_e0)
    segs = kit._parse_e0_segments(new_e0)
    A = kit.e0_device(segs)
    t2 = struct.unpack_from('<I', new_e0, kit._e0_vaddr_to_foff(segs, A.TAB2_BASE_PTR))[0]
    _, n2 = kit._decode_thumb_movw(new_e0[kit._e0_vaddr_to_foff(segs, A.TAB2_CNT_INSN):][:4])
    row = kit._e0_vaddr_to_foff(segs, t2 + 44 * (n2 - 1), 44)
    assert struct.unpack_from('<I', new_e0, row)[0] == m['words'][2]
    struct.pack_into('<3I', new_e0, row + 24, N_SHOWN, len(params), len(params))   # the synced pair hidden
    log(f"[+] Entry 0: preset_id {pid}, dsp_cost {cost}, Looper > {FOLDER}")

    entries = l6ia.parse(l6ia_bytes)
    e2_raw = l6ia_bytes[entries[2]['payload_off']: entries[2]['payload_off'] + entries[2]['payload_len']]
    e2_raw, _ = kit.expand_sharc_blob0_buffer(e2_raw)
    out, _, _ = l6ia.rebuild_archive(l6ia_bytes, {0: bytes(new_e0), 2: l6ia.swap32(e2_raw), 3: new_e3, 4: new_e4})

    asm = open(ASM).read()
    secs, _ = kit.sasm.assemble(asm.replace('KIT_PM_BASE', '0xe0000'), 'click.asm')
    base = pm_base(sum(len(s.words) for s in secs if s.kind == 'pm'))
    out, kinfo = kit.patch_kernel(out, asm, 'click.asm', prim=PRIM, pm_base=base, relocate=False, log=log)
    return out, {'model_id': model_id, 'blob': blob, 'composite': comp, 'preset_id': pid, 'pm_base': base,
                 'entry': kinfo['entry'], 'params': params}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('input')
    ap.add_argument('output')
    ap.add_argument('--donor', help='Stock .hxf of the unit, when input is a raw L6IA and output a .hxf')
    args = ap.parse_args()
    l6ia_bytes, is_hxf = kit.load_l6ia_from_any(args.input)
    out, _ = add_click(l6ia_bytes)
    kit.save_l6ia_to_any(out, args.output, donor_hxf=args.input if is_hxf else args.donor)
    print(f"[+] Wrote {args.output}")


if __name__ == '__main__':
    main()
