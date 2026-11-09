#!/usr/bin/env python3
"""patch_comp.py - the gain-reduction meter's knobs (Mtr Pos, Mtr Dir, Mtr Thk) on compressor blocks, HX Stomp or XL 3.80.0.

Each model in COMP_MODELS gets three more parameters after its own, in the three places that must agree:
  Entry 3: the parameter records, their state records and the strings they name (the string section grows in place).
  Entry 4: the model's blob gets one parameter-map input node per knob, a default for each on the root, and a writer
           handing it to the compressor core as pid 100, 101, 102, which the DSP wrapper's control function keeps;
           and for each core an init record, pid 103, saying whether its output overwrites its first input or its second.
  Entry 0: the model's row in the UI Model Info Table counts the new parameters.
Run it after every step that adds models (add-model, add-fx-model, patch_click.py): those rebuild Entry 3's and Entry 4's tails
from the models they added and would drop what this writes there.
"""
import argparse
import struct
import zlib

import patch_amp as pa

COMP_MODELS = (   # (model, its compressor core's primitive: src/sharc/frame_probe.asm wraps each of these)
    ('HD2_CompressorDeluxeCompMono', 0x271a), ('HD2_CompressorDeluxeCompStereo', 0x271a),
    ('HD2_CompressorLAStudioCompMono', 0x2719), ('HD2_CompressorLAStudioCompStereo', 0x2719),
    ('HD2_CompressorKinkyCompMono', 0x2710), ('HD2_CompressorKinkyCompStereo', 0x2710),
    ('HD2_CompressorOptoCompMono', 0x2710), ('HD2_CompressorOptoCompStereo', 0x2710),
    ('HD2_CompressorRochesterCompMono', 0x271a), ('HD2_CompressorRochesterCompStereo', 0x271a),
)
GR_KNOBS = (   # (name, displayName, displayNameShort, value labels, default): integer lists, as Ratio
    ('GRPosition', 'Mtr Position', 'Mtr Pos', ('Middle', 'Top', 'Left', 'Bottom', 'Right'), 0),
    ('GRDirection', 'Mtr Direction', 'Mtr Dir', ('Normal', 'Reverse'), 0),
    ('GRThickness', 'Mtr Thickness', 'Mtr Thk', tuple(str(k) for k in range(21)), 0),    # 0 is off: the meter is opt-in
)
INT_INPUT_OP = 0x0b
GR_PID = 100                    # src/sharc/frame_probe.asm's GR_PID: past every core's own pids (the LA Studio Comp's go to 14)
STOCK_E3_END = 0xcadb4


def e3_strings(e3):
    """(section offset, records, data, {string: index}) of Entry 3's string section."""
    str_off = struct.unpack_from('<I', e3, 12)[0]
    nstr, slen = struct.unpack_from('<2I', e3, str_off)
    recs = bytes(e3[str_off + 8: str_off + 8 + 12 * nstr])
    data = bytes(e3[str_off + 8 + 12 * nstr: str_off + slen])
    index = {}
    for i in range(nstr):
        roff, _, ln = struct.unpack_from('<3I', recs, 12 * i)
        index.setdefault(data[roff:roff + ln].decode('latin1'), i)
    return str_off, recs, data, index


def e3_add_strings(e3, wanted):
    """Entry 3 with the strings of `wanted` it lacks appended to its section, and {string: index} for them all.
    Indices never change. A stock section (at 0x200) is copied past the end; the tail one add-model writes at
    0xcae00 grows in place, the model table and everything after it moving down, their offsets with them."""
    e3 = bytearray(e3)
    h = list(struct.unpack_from('<10I', e3, 0))
    str_off, recs, data, index = e3_strings(e3)
    nstr = len(recs) // 12
    added = b''
    for s in wanted:
        if s not in index:
            raw = s.encode('latin1')
            added += struct.pack('<3I', len(data), zlib.crc32(raw) & 0xffffffff, len(raw))
            data += raw + b'\x00'
            index[s] = nstr + len(added) // 12 - 1
    if not added:
        return bytes(e3), index
    n = nstr + len(added) // 12
    section = struct.pack('<2I', n, 8 + 12 * n + len(data)) + recs + added + data
    if str_off < STOCK_E3_END:
        out = e3 + bytes(pa._align(len(e3), 0x200) - len(e3))
        h[3] = len(out)
        out += section
    else:
        old_mtab = h[6]
        assert old_mtab > str_off, 'the model table is not after the string section'
        new_mtab = pa._align(str_off + len(section), 0x200)
        delta = new_mtab - old_mtab
        out = e3[:str_off] + section + bytes(new_mtab - str_off - len(section)) + e3[old_mtab:]
        mv = lambda v: v + delta if v >= old_mtab else v
        h[6] = new_mtab
        for i in range(h[7]):
            d = new_mtab + 56 * i
            w = list(struct.unpack_from('<14I', out, d))
            for j in (1, 10, 11, 12):
                w[j] = mv(w[j])
            struct.pack_into('<14I', out, d, *w)
            for p in range(w[7]):
                po = w[11] + 32 * p + 4
                struct.pack_into('<I', out, po, mv(struct.unpack_from('<I', out, po)[0]))
        for k in range(h[9]):
            lo = h[8] + 32 * k + 24
            struct.pack_into('<I', out, lo, mv(struct.unpack_from('<I', out, lo)[0]))
    out += bytes(pa._align(len(out), 4) - len(out))
    h[2], h[5] = len(out), len(section)
    h[4] = zlib.crc32(out[h[3]:h[3] + len(section)]) & 0xffffffff
    struct.pack_into('<10I', out, 0, *h)
    return bytes(out), index


def models_view(info):
    """Every model's names, metadata and parameters, as text (raw words of int parameters can be NaN as floats)."""
    return repr([(m['name'], m['meta'], [(p['name'], p['type'], p['slot'], p['meta'], p['min'], p['max'], p['default'])
                                         for p in m['params']]) for m in info['models']])


def slot_lists(e3):
    h = struct.unpack_from('<10I', e3, 0)
    out = []
    for k in range(h[9]):
        lc, lo = struct.unpack_from('<2I', e3, h[8] + 32 * k + 20)
        out.append(struct.unpack_from(f'<{lc}I', e3, lo))
    return out


def knob_strings():
    out = []
    for name, disp, short, labels, _ in GR_KNOBS:
        out += [name, name + 'State', disp, short, 'displayName', 'displayNameShort', 'displayType', 'list']
        out += [str(k) for k in range(len(labels))] + list(labels)
    return out


def e3_add_knobs(e3, model_name, S):
    """Entry 3 with GR_KNOBS appended to the model's parameters and states (slots and state indices after its own);
    the new records go past the end. Returns (Entry 3, the model's first new slot, its old parameter count)."""
    e3 = bytearray(e3)
    info = pa.parse_entry3_full(bytes(e3))
    m = pa.find_model(info, model_name)
    assert m['name'] == model_name
    d = list(m['words'])
    n_par, n_st = d[7], d[6]
    assert n_par == n_st and all(p['slot'] == k + 1 for k, p in enumerate(m['params'])), \
        f'{model_name}: parameters and states are not one per slot 1..{n_par}'
    assert all(p['name'] not in [k[0] for k in GR_KNOBS] for p in m['params']), f'{model_name} has the knobs already'
    tail = bytearray()
    base = pa._align(len(e3), 4)
    e3 += bytes(base - len(e3))
    params, states = [], []
    for k, (name, disp, short, labels, dflt) in enumerate(GR_KNOBS):
        meta = [('displayName', disp), ('displayNameShort', short)]
        meta += [(str(j), lab) for j, lab in enumerate(labels)] + [('displayType', 'list')]
        pm_off = base + len(tail)
        tail += b''.join(struct.pack('<3I', S[key], 7, S[val]) for key, val in meta)
        params.append(struct.pack('<5I3i', len(meta), pm_off, S[name], 2, n_par + 1 + k, 0, len(labels) - 1, dflt))
        states.append(struct.pack('<5I', 0, 0x80b98, S[name + 'State'], 2, n_st + k))
    d[10] = base + len(tail)
    tail += bytes(e3[m['words'][10]: m['words'][10] + 20 * n_st]) + b''.join(states)
    d[11] = base + len(tail)
    tail += bytes(e3[m['words'][11]: m['words'][11] + 32 * n_par]) + b''.join(params)
    d[6], d[7] = n_st + len(GR_KNOBS), n_par + len(GR_KNOBS)
    e3 += tail
    struct.pack_into('<14I', e3, m['off'], *d)
    struct.pack_into('<I', e3, 8, len(e3))
    if len(e3) > pa.E3_MAX:
        raise SystemExit(f'Entry 3 would be {len(e3):#x} bytes; its partition holds {pa.E3_MAX:#x}')
    return bytes(e3), n_par + 1, n_par


def pmap_sizes(pm):
    """The parameter map's size words (header words 12..17) as its tables give them."""
    a, c, d = pm[0], pm[4], pm[6]
    nA, _, nC, nD, nE, _ = pm[18:24]
    nodes = [pm[a + 10 * k: a + 10 * k + 10] for k in range(nA)]
    inputs = sum(n[8] for n in nodes)
    return [sum(n[5] for n in nodes), nA, nD + sum(n[4] for n in nodes) + inputs, nC + nD + inputs, nD, nE]


def core_paths(b, pm, nodes, b0, prim):
    """(path word, output-is-first-input) of each member running primitive `prim`, the compressor cores, by the path
    words of the writers to them; the first is the GR knobs' target. The blob's node tree may override a member's
    primitive (the Kinky Comp's core is 0x2710 there, 0x2719 in the composite) [verified on unit]."""
    members = pa.entry4_blob.parse_composite(b0, pa.entry4_blob.top_type(b))['members']
    types = [m['type_id'] for m in members]
    for slot, t, _, _ in list(pa.entry4_blob.nodes(b))[1:]:
        if t != 0xffffffff:
            types[slot - 1] = t
    out = {}
    for nd in nodes:
        path = pm[nd[0]] if nd[3] == 1 else None
        if path is not None and b[path] == 1 and types[b[path + 1] - 1] == prim:
            m = members[b[path + 1] - 1]
            out.setdefault(b[path + 1], (path, int(b0[m['out_off']] == b0[m['in_off']])))
    if len(out) != types.count(prim):
        raise SystemExit(f'{types.count(prim)} members run primitive {prim:#x}, {len(out)} have a writer')
    return list(out.values())


def blob_add_knobs(b, first_slot, b0, prim):
    """A model blob with one int input node per GR_KNOBS entry (slots first_slot..) and a root default for each,
    each feeding a writer that hands its value to the compressor core as pid GR_PID + k (the DSP wrapper's).
    The parameter map, init records and relocation list are rebuilt after the node tree, in stock order; the old
    copies' space is dropped and nothing before the parameter map moves."""
    assert b[0] == 3 and b[6] < b[10] < b[4] < b[8] and b[8] + 2 * b[9] == len(b), 'unexpected blob layout'
    po, pl, pin, npin, ini, nini, sub, nsub = b[6], b[7], b[10], b[11], b[4], b[5], b[8], b[9]
    pm = list(b[po: po + pl])
    assert pmap_sizes(pm) == pm[12:18], 'the parameter map\'s sizes do not follow its tables'
    a, d, e = pm[0], pm[6], pm[8]
    nA, nD, nE = pm[18], pm[21], pm[22]
    nodes = [pm[a + 10 * k: a + 10 * k + 10] for k in range(nA)]
    dt = [pm[d + 4 * k: d + 4 * k + 4] for k in range(nD)]
    et = [pm[e + 4 * k: e + 4 * k + 4] for k in range(nE)]
    assert sorted(r[2] for r in dt) == list(range(1, first_slot)), 'slot map is not slots 1..n'
    pins = [b[pin + 4 * k: pin + 4 * k + 4] for k in range(npin)]
    root = {r[0] for r in pins if r[3] == 1 and b[r[0]: r[0] + 2] == [1, 0]}
    assert len(root) == 1, 'no single root path among the init records'
    root = root.pop()
    c, nC = pm[4], pm[20]
    ct = [pm[c + 4 * k: c + 4 * k + 4] for k in range(nC)]
    cores = core_paths(b, pm, nodes, b0, prim)
    path = cores[0][0]
    n = len(GR_KNOBS)
    data = len(pm)                                  # the writers' data {path, pid, 1}, after the old tables
    pm += [w for k in range(n) for w in (path, GR_PID + k, 1)]
    for k in range(n):
        nodes.append([nodes[0][0], 0, nA + k, INT_INPUT_OP, 1, 2, 0, 0, 1, 0])
        dt.append([nA + k, nE + k, first_slot + k, 0])
        et.append([nA + k, nE + k, nE + k, 0])
    for k in range(n):
        nodes.append([data + 3 * k, 0, nA + n + k, 1, 0, 3, 3, 3, 0, 0])
        ct.append([nA + k, nA + n + k, 0, 0])
    # the new tables go after the old ones; the old A, C, D and E stay unused in place
    pm[0] = len(pm)
    pm += [w for nd in nodes for w in nd]
    pm[4] = len(pm)
    pm += [w for r in ct for w in r]
    pm[6] = len(pm)
    pm += [w for r in dt for w in r]
    pm[8] = len(pm)
    pm += [w for r in et for w in r]
    pm[18], pm[20], pm[21], pm[22] = len(nodes), len(ct), len(dt), len(et)
    pm[12:18] = pmap_sizes(pm)

    out = list(b[:po])
    new_po = len(out)
    out += pm
    new_pin = len(out)
    nc = len(cores)                                 # one init record per core: which input its output overwrites
    vals = new_pin + 4 * (npin + n + nc) + 2 * (nini + 2 * n + nc) + 2 * nsub
    for r in pins:
        out += r
    for k, (_, _, _, _, dflt) in enumerate(GR_KNOBS):
        out += [root, first_slot + k, vals + 2 * k, 1]
    for k, (p, _) in enumerate(cores):
        out += [p, GR_PID + n, vals + 2 * (n + k), 1]
    new_ini = len(out)
    for k in range(nini):
        t, off = b[ini + 2 * k: ini + 2 * k + 2]
        if po <= off < po + pl:
            off += new_po - po
        elif pin <= off < pin + 4 * npin:
            off += new_pin - pin
        else:
            assert off < po, f'relocation at {off:#x} is in no table this moves'
        out += [t, off]
    for k in range(n):
        out += [1, new_po + data + 3 * k]
    for k in range(n + nc):
        out += [1, new_pin + 4 * (npin + k)]
    new_sub = len(out)
    out += b[sub: sub + 2 * nsub]
    assert all(w < po for w in b[sub: sub + 2 * nsub]), 'a sub-binding points past the node tree'
    assert len(out) == vals
    for _, _, _, _, dflt in GR_KNOBS:
        out += [1, dflt]
    for _, first_in in cores:
        out += [1, first_in]
    out[4], out[5], out[6], out[7] = new_ini, nini + 2 * n + nc, new_po, len(pm)
    out[8], out[10], out[11] = new_sub, new_pin, npin + n + nc
    return out


def e4_replace_blob(e4, idx, words):
    """Entry 4 with blob `idx` replaced by `words`, written past the end (nothing else moves)."""
    w4 = list(struct.unpack('<%dI' % (len(e4) // 4), e4))
    assert w4[0] == 0x28267e5e and w4[5] == len(w4)
    w4[w4[3] + 2 * idx: w4[3] + 2 * idx + 2] = [len(words), len(w4)]
    w4 += words
    w4[5] = len(w4)
    out = struct.pack('<%dI' % len(w4), *w4)
    if len(out) > pa.E4_MAX:
        raise SystemExit(f'Entry 4 would be {len(out):#x} bytes; its partition holds {pa.E4_MAX:#x}')
    return out


def e0_set_param_counts(e0, name_idx, old, new):
    """Entry 0 with the model's UI Model Info Table row (bytes 24..35: three parameter counts) set to `new`."""
    e0 = bytearray(e0)
    segs = pa._parse_e0_segments(e0)
    A = pa.e0_device(segs)
    fo = lambda va, ln=4: pa._e0_vaddr_to_foff(segs, va, ln)
    tab = struct.unpack_from('<I', e0, fo(A.TAB2_BASE_PTR))[0]
    _, cnt = pa._decode_thumb_movw(e0[fo(A.TAB2_CNT_INSN): fo(A.TAB2_CNT_INSN) + 4])
    rows = [tab + 44 * i for i in range(cnt) if struct.unpack_from('<I', e0, fo(tab + 44 * i))[0] == name_idx]
    assert len(rows) == 1, f'{len(rows)} rows for string {name_idx} in the UI Model Info Table'
    r = fo(rows[0] + 24, 12)
    assert struct.unpack_from('<3I', e0, r) == (old,) * 3, f'row counts {struct.unpack_from("<3I", e0, r)}, not {old}'
    struct.pack_into('<3I', e0, r, new, new, new)
    return bytes(e0)


def patch_comp(l6ia_bytes, models=COMP_MODELS, log=print):
    e0 = pa.get_entry_swapped(l6ia_bytes, 0)
    e3 = pa.get_entry_swapped(l6ia_bytes, 3)
    e4 = pa.get_entry_swapped(l6ia_bytes, 4)
    before, before_e3 = pa.parse_entry3_full(e3), e3
    e3, S = e3_add_strings(e3, knob_strings())
    mid = pa.parse_entry3_full(e3)
    assert models_view(before) == models_view(mid), 'the string section move changed a model'
    assert slot_lists(before_e3) == slot_lists(e3), 'the string section move changed a slot list'
    for name, prim in models:
        m = pa.find_model(pa.parse_entry3_full(e3), name)
        e3, first, old = e3_add_knobs(e3, name, S)
        w4 = struct.unpack('<%dI' % (len(e4) // 4), e4)
        b = blob_add_knobs(pa.entry4_blob.blob(w4, m['blob_index']), first, pa.entry4_blob.blob(w4, 0), prim)
        e4 = e4_replace_blob(e4, m['blob_index'], b)
        e0 = e0_set_param_counts(e0, m['words'][2], old, old + len(GR_KNOBS))
        chk = pa.parse_entry3_full(e3)['models'][m['idx']]
        assert [p['slot'] for p in chk['params']] == list(range(1, old + 1 + len(GR_KNOBS)))
        assert not pa.pmap_slots_without_param(e4, m['blob_index'], chk['params'])
        log(f"[+] {name}: {', '.join(k[1] for k in GR_KNOBS)} on slots {first}..{first + len(GR_KNOBS) - 1} "
            f"(Entry 3 model {m['idx']}, Entry 4 blob {m['blob_index']}, Entry 0 row counts {old + len(GR_KNOBS)})")
    new, _, _ = pa.l6ia.rebuild_archive(l6ia_bytes, {0: e0, 3: e3, 4: e4})
    return new


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('input', help='.hxf or L6IA')
    ap.add_argument('output')
    ap.add_argument('--donor', help='Stock .hxf of the unit, when input is a raw L6IA and output a .hxf')
    a = ap.parse_args()
    data, is_hxf = pa.load_l6ia_from_any(a.input)
    pa.save_l6ia_to_any(patch_comp(data), a.output, donor_hxf=a.input if is_hxf else a.donor)
    print(f'[+] Wrote {a.output}')


if __name__ == '__main__':
    main()
