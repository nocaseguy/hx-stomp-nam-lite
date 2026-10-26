#!/usr/bin/env python3
"""L6IA entry-4 blob parser (model & composite library).

Solved:
  - Directory: 6-word header [0x28267e5e, 4, 864, 6, 0x6c6, total_words] then
    864 {len_words, offset_words} pairs at word 6.
  - Blob 0 (at word 0x6c6, len 0x77aac): global composite library, relocated by
    the SHARC at boot. Composite table (454 x 7-word entries for 0x600000..0x6001c5)
    starts at b0[b0[0x10]] = b0[0x1175]. Each 7-word entry is:
      {n_in, n_out, n_members, members_off, n_buffers, buffers_off, flags}
    pointing to n_members x 20-word member records at b0[members_off], where
    rec[4] = flags (0=primitive/sub-composite, 1=tap, 4=in_port, 8=out_port),
    rec[6] = type_id, rec[11] = n_init_params, rec[12] = init_params_off,
    rec[13] = dm_words, rec[14] = pm_words.
  - Model blobs (1..863):
    12-word header:
      b[0] = 3 (magic), b[1] = 2 (flags),
      b[2] = node_tree_off, b[3] = node_cnt,
      b[4] = init_list_off, b[5] = init_list_cnt,
      b[6] = param_map_off, b[7] = param_map_len,
      b[8] = sub_bind_off,  b[9] = sub_bind_cnt,
      b[10]= post_init_off, b[11]= post_init_cnt.
    Each node at b[node_tree_off + 4*k] is {slot_idx, type_id, child_off, child_cnt}.
  - Entry 3 model descriptor m[13] (byte +52) gives the exact Entry-4 blob index.

Usage: python3 tools/sharc/entry4_blob.py <entry4.bin> [blob_index_or_0x600xxx]
  (entry4.bin: Entry 4 of the L6IA archive, words byte-swapped to little-endian)
"""
import sys, struct, collections

def load(path):
    d = open(path, 'rb').read()
    return struct.unpack('<%dI' % (len(d)//4), d)

def directory(w):
    assert w[0] == 0x28267e5e, f'bad entry4 magic {w[0]:#x} (expected 0x28267e5e)'
    n = w[2]
    dir_off = w[3]
    return [(w[dir_off+2*k], w[dir_off+2*k+1]) for k in range(n)]  # (len, off)

def blob(w, i):
    ln, off = directory(w)[i]
    return list(w[off:off+ln])

def top_type(b):
    """Return the model blob's top-level type id (composite 0x6000xx or registry id)."""
    if len(b) < 4 or b[0] != 3:
        return None
    tl = b[2]
    return b[tl + 1] if 0 < tl + 1 < len(b) else None

def nodes(b):
    """Yield 4-word nodes {slot_idx, type_id, child_off, child_cnt} from the node tree."""
    if len(b) < 4 or b[0] != 3:
        return
    tl, cnt = b[2], b[3]
    for k in range(cnt):
        o = tl + 4*k
        if o+4 <= len(b):
            yield (b[o], b[o+1], b[o+2], b[o+3])

def parse_composite(b0, comp_id):
    """Parse a 0x600xxx composite from Blob 0 into header + 20-word member records."""
    idx = comp_id - 0x600000
    n_comp = b0[0xf]
    ctab = b0[0x10]
    if not (0 <= idx < n_comp):
        return None
    hdr = b0[ctab + idx*7 : ctab + (idx+1)*7]
    n_in, n_out, n_mem, mem_off, n_buf, buf_off, flags = hdr
    members = []
    for m in range(n_mem):
        rec = b0[mem_off + m*20 : mem_off + (m+1)*20]
        n_ip, ip_off = rec[11], rec[12]
        init_params = [(b0[ip_off + 2*k], b0[ip_off + 2*k + 1]) for k in range(n_ip)] if n_ip else []
        members.append({
            'idx': rec[0], 'n_conn': rec[1], 'conn_off': rec[2],
            'flags': rec[4], 'parent': rec[5], 'type_id': rec[6],
            'n_in': rec[7], 'in_off': rec[8], 'n_out': rec[9], 'out_off': rec[10],
            'n_init': n_ip, 'init_off': ip_off, 'init_params': init_params,
            'dm_words': rec[13], 'pm_words': rec[14],
            'audio_bufs': rec[16], 'sub_insts': rec[17], 'ports': rec[18],
        })
    return {
        'comp_id': comp_id, 'n_in': n_in, 'n_out': n_out,
        'n_members': n_mem, 'members_off': mem_off,
        'n_buffers': n_buf, 'buffers_off': buf_off, 'flags': flags,
        'members': members,
    }

def expand_composite_primitives(b0, comp_id):
    """Recursively expand a composite ID into a list of leaf primitive IDs."""
    info = parse_composite(b0, comp_id)
    if not info:
        return []
    prims = []
    for m in info['members']:
        if m['flags'] == 0:
            tid = m['type_id']
            if 0x600000 <= tid < 0x601000:
                prims.extend(expand_composite_primitives(b0, tid))
            else:
                prims.append(tid)
    return prims

if __name__ == '__main__':
    path = sys.argv[1]
    w = load(path)
    dirs = directory(w)
    b0 = blob(w, 0)
    print('entry4: %d blobs, header=%s' % (len(dirs), [hex(w[i]) for i in range(6)]))
    if len(sys.argv) > 2:
        arg = sys.argv[2]
        if arg.startswith('0x600'):
            cid = int(arg, 16)
            c = parse_composite(b0, cid)
            prims = expand_composite_primitives(b0, cid)
            counts = collections.Counter(hex(p) for p in prims)
            print(f"composite {cid:#x}: in={c['n_in']} out={c['n_out']} members={c['n_members']} bufs={c['n_buffers']} leaf_prims={dict(counts)}")
            for m in c['members']:
                if m['flags'] == 0:
                    print(f"  m[{m['idx']:3d}] type={m['type_id']:#08x} dm={m['dm_words']:3d} pm={m['pm_words']:2d} n_init={m['n_init']:3d}@0x{m['init_off']:x}")
        else:
            i = int(arg, 0)
            b = blob(w, i)
            tt = top_type(b)
            print('blob %d: len=%d magic=%#x flags=%#x nodetree@%#x count=%d init@%#x(%d) pmap@%#x(%d) top_type=%s'
                  % (i, len(b), b[0], b[1] if len(b) > 1 else 0,
                     b[2] if len(b) > 2 else 0, b[3] if len(b) > 3 else 0,
                     b[4] if len(b) > 4 else 0, b[5] if len(b) > 5 else 0,
                     b[6] if len(b) > 6 else 0, b[7] if len(b) > 7 else 0,
                     ('0x%x' % tt) if tt else None))
            for j, (slot, t, co, cc) in enumerate(nodes(b)):
                extra = ''
                if 0x600000 <= t < 0x601000:
                    prims = expand_composite_primitives(b0, t)
                    counts = collections.Counter(hex(p) for p in prims)
                    extra = f' -> {len(prims)} leaf prims {dict(counts)}'
                print(f'  node{j:2d} {{slot={slot:#x} type={t:#x} child_off={co:#x} child_cnt={cc}}}{extra}')

