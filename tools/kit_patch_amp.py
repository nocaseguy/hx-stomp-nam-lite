#!/usr/bin/env python3
# kit_patch_amp.py - a verbatim copy of hx-stomp-kit's hxkit/patch_amp.py (kit commit e7d1b9a), for
# its effect-host add_model (patch_amp.py add-fx-model uses it). Edit it in the kit, then copy it here.
"""patch_amp.py - add NAM A2 Lite as a new amp to the stock HX Stomp (or XL) v3.80.0 firmware.

Works on the stock .hxf (or the L6IA archive inside it) and writes a .hxf
for Line 6 Updater, or an L6IA; every integrity field (L6IA Fletcher-32 and
CRC-32, image CRCs, the .hxf's MD5) is recomputed.

Commands:
  inspect <in> [model]
      List the amps, or show one: Entry 3 parameters, its Entry 4 blob and
      composite, and the per-member initial values.

  add-model <in> <out> --name HD2_AmpNAMLite --display-name "NAM A2 Lite" [--folder NAM]
      Add the NAM host amp: a copy of HD2_AmpLine6Clarity's composite whose amp
      stage is primitive 0x9c75, with its own eight parameters (Model, Drive,
      Bass, Mid, Treble, Presence, Ch Vol, Polarity), listed in the amp browser (Entry 0),
      the model table (Entry 3) and the DSP graph library (Entry 4); the SHARC's
      graph buffer is enlarged to fit (Entry 2).

  patch <in> <out> --asm nam_lite.asm
      Assemble the kernel (tools/sharc/sasm.py), add it to the SHARC boot
      stream (Entry 2) and point primitive 0x9c75 at it.
"""
import argparse
import collections
import os
import re
import struct
import sys
import types
import zlib

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SHARC_DIR = os.path.join(SCRIPT_DIR, 'sharc')
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, SHARC_DIR)

import hxf
import l6ia
import entry4_blob
import sasm
import ssim


def u32(b, o):
    return struct.unpack_from('<I', b, o)[0]


def asf(x):
    return struct.unpack('<f', struct.pack('<I', x & 0xffffffff))[0]


def f2u(f):
    return struct.unpack('<I', struct.pack('<f', float(f)))[0]


def load_l6ia_from_any(path):
    """Return (l6ia_bytes, is_hxf) from either an .hxf container or raw L6IA file."""
    raw = open(path, 'rb').read()
    if raw[:4] == b'FORM' and raw[8:12] == b'L6FF':
        data_chunk = [b for c, p, s, b in hxf._chunks(raw) if c == b'data'][0]
        return zlib.decompress(data_chunk), True
    assert raw[:4] == b'L6IA', f'{path}: neither FORM/L6FF (.hxf) nor L6IA archive'
    return raw, False


def save_l6ia_to_any(l6ia_bytes, out_path, donor_hxf=None):
    """Write l6ia_bytes to out_path: a .hxf (packed by hxf.pack with the stock
    .hxf of the same unit as donor, which gives HEAD its product) or raw L6IA."""
    if out_path.endswith('.hxf'):
        if not donor_hxf or open(donor_hxf, 'rb').read(4) != b'FORM':
            raise SystemExit('writing a .hxf needs --donor: the stock .hxf of the same unit')
        tmp = out_path + '.l6ia.tmp'
        open(tmp, 'wb').write(l6ia_bytes)
        try:
            hxf.pack(tmp, out_path, donor_hxf)
        finally:
            os.remove(tmp)
    else:
        open(out_path, 'wb').write(l6ia_bytes)


def get_entry_swapped(l6ia_bytes, idx):
    entries = l6ia.parse(l6ia_bytes)
    e = entries[idx]
    p = l6ia_bytes[e['payload_off']: e['payload_off'] + e['payload_len']]
    return l6ia.swap32(p)


def parse_entry3_full(e3_bytes):
    magic, ver, tsize, str_off, scrc, str_len, mtab_off, mcnt, gtab_off, gcnt = struct.unpack_from('<10I', e3_bytes, 0)
    assert magic == 0x4023245e, f'bad Entry 3 magic {magic:#x}'
    nstr, slen = struct.unpack_from('<2I', e3_bytes, str_off)
    sdata_base = str_off + 8 + 12 * nstr
    strings = []
    str_recs = []
    for i in range(nstr):
        roff, crc, ln = struct.unpack_from('<3I', e3_bytes, str_off + 8 + 12 * i)
        s = e3_bytes[sdata_base + roff: sdata_base + roff + ln].decode('latin1')
        strings.append(s)
        str_recs.append((roff, crc, ln))

    models = []
    for i in range(mcnt):
        m = list(struct.unpack_from('<14I', e3_bytes, mtab_off + i * 56))
        meta = {}
        meta_recs = []
        for k in range(m[0]):
            ks, kt, kv = struct.unpack_from('<3I', e3_bytes, m[1] + k * 12)
            key = strings[ks]
            val = strings[kv] if (kt == 7 and kv < len(strings)) else kv
            meta[key] = val
            meta_recs.append((m[1] + k * 12, key, kt, kv, val))
        params = []
        for p in range(m[7]):
            poff = m[11] + p * 32
            pm_cnt, pm_off, p_name_idx, p_type, p_slot, p_min, p_max, p_def = struct.unpack_from('<5I3f', e3_bytes, poff)
            pmeta = {}
            for k in range(pm_cnt):
                ks, kt, kv = struct.unpack_from('<3I', e3_bytes, pm_off + k * 12)
                pmeta[strings[ks]] = strings[kv] if (kt == 7 and kv < len(strings)) else kv
            params.append({
                'off': poff,
                'name': strings[p_name_idx],
                'type': p_type,
                'slot': p_slot,
                'min': p_min,
                'max': p_max,
                'default': p_def,
                'displayName': pmeta.get('displayName', ''),
                'displayNameShort': pmeta.get('displayNameShort', ''),
                'meta': pmeta,
            })
        models.append({
            'idx': i,
            'off': mtab_off + i * 56,
            'words': m,
            'model_id': m[3],
            'name': strings[m[2]],
            'displayName': meta.get('displayName', ''),
            'meta': meta,
            'meta_recs': meta_recs,
            'params': params,
            'blob_index': m[13],
        })
    return {
        'header': (magic, ver, tsize, str_off, scrc, str_len, mtab_off, mcnt, gtab_off, gcnt),
        'strings': strings,
        'str_recs': str_recs,
        'sdata_base': sdata_base,
        'models': models,
    }


def find_model(e3_info, query):
    for m in e3_info['models']:
        if m['name'].lower() == query.lower() or m['displayName'].lower() == query.lower():
            return m
    if query.isdigit():
        mid = int(query)
        for m in e3_info['models']:
            if m['model_id'] == mid or m['blob_index'] == mid:
                return m
    for m in e3_info['models']:
        if query.lower() in m['name'].lower() or query.lower() in m['displayName'].lower():
            return m
    raise SystemExit(f"Model '{query}' not found in Entry 3")


def cmd_inspect(args):
    l6ia_bytes, _ = load_l6ia_from_any(args.input)
    e3_bytes = get_entry_swapped(l6ia_bytes, 3)
    e4_bytes = get_entry_swapped(l6ia_bytes, 4)
    e3_info = parse_entry3_full(e3_bytes)

    if not args.model:
        amps = [m for m in e3_info['models'] if m['name'].startswith('HD2_Amp')]
        print(f"Found {len(amps)} HD2_Amp* models in Entry 3 (out of {len(e3_info['models'])} total models):")
        w4 = entry4_blob.load_bytes(e4_bytes) if hasattr(entry4_blob, 'load_bytes') else struct.unpack('<%dI' % (len(e4_bytes) // 4), e4_bytes)
        for m in amps:
            bi = m['blob_index']
            b = entry4_blob.blob(w4, bi)
            tt = entry4_blob.top_type(b)
            print(f"  id={m['model_id']:3d} blob={bi:3d} comp={tt:#08x}  {m['name']:32s} ({m['displayName']})")
        return

    m = find_model(e3_info, args.model)
    w4 = struct.unpack('<%dI' % (len(e4_bytes) // 4), e4_bytes)
    b0 = entry4_blob.blob(w4, 0)
    bi = m['blob_index']
    b = entry4_blob.blob(w4, bi)
    tt = entry4_blob.top_type(b)

    print(f"=== Model: {m['name']} ({m['displayName']}) ===")
    print(f"  Entry 3 Model ID : {m['model_id']} (descriptor @ {m['off']:#x})")
    print(f"  Metadata         : {m['meta']}")
    print(f"  Entry 4 Blob ID  : {bi} (m[13] = {bi}, len = {len(b)} words)")
    print(f"  Top-Level Type   : {tt:#08x}" if tt else "  Top-Level Type   : None")
    print(f"\n--- Entry 3 Parameters ({len(m['params'])}) ---")
    for p in m['params']:
        disp = p['displayName'] or p['name']
        print(f"  slot={p['slot']:2d} type={p['type']} {p['name']:14s} ({disp:12s}) "
              f"min={p['min']:8.3f} max={p['max']:8.3f} default={p['default']:8.3f}  meta={p['meta']}")

    if tt and 0x600000 <= tt < 0x601000:
        comp = entry4_blob.parse_composite(b0, tt)
        prims = entry4_blob.expand_composite_primitives(b0, tt)
        counts = collections.Counter(f"0x{p:x}" for p in prims)
        print(f"\n--- Entry 4 Blob 0 Composite {tt:#x} ---")
        print(f"  ports: in={comp['n_in']} out={comp['n_out']} | members={comp['n_members']} | audio_bufs={comp['n_buffers']}")
        print(f"  leaf primitives ({len(prims)}): {dict(counts)}")

        pinit_off, pinit_cnt = b[10], b[11]
        by_member = collections.defaultdict(list)
        for k in range(pinit_cnt):
            soff, pid, voff, cnt = b[pinit_off + 4 * k: pinit_off + 4 * (k + 1)]
            raw_midx = b[soff + 1]
            midx = raw_midx - 1
            val = b[voff + 1]
            by_member[midx].append((k, pid, voff + 1, val, asf(val)))

        print(f"\n--- Entry 4 Blob {bi} Per-Member Initializations ({pinit_cnt} records @ word {pinit_off:#x}) ---")
        for midx, plist in sorted(by_member.items()):
            if midx < 0:
                tid_str = "ROOT_COMPOSITE"
            elif midx < len(comp['members']):
                tid_str = f"type={comp['members'][midx]['type_id']:#06x}"
            else:
                tid_str = "type=?"
            preview = []
            for _, pid, _, val, fval in plist[:10]:
                if 1e-4 <= abs(fval) < 1e7:
                    preview.append(f"p{pid}={fval:.4g}")
                else:
                    preview.append(f"p{pid}={val:#x}")
            more = f" ... (+{len(plist) - 10} more)" if len(plist) > 10 else ""
            print(f"  member[{midx:3d}] ({tid_str:14s}, {len(plist):3d} params): {', '.join(preview)}{more}")


def pack_init_l48(addr48, insn_words):
    """Build an ADSP-21469 LDR INIT_L48 (tag=5) block as little-endian 32-bit words."""
    ins = list(insn_words)
    if len(ins) & 1:
        ins.append(0)  # pad to even instruction count with NOP
    raw = b''.join(int(w).to_bytes(6, 'little') for w in ins)
    w32 = list(struct.unpack('<%dI' % (len(raw) // 4), raw))
    return [5, len(ins), addr48] + w32


def pack_init_l32(addr32, data_words):
    """Build an ADSP-21469 LDR INIT_L32 (tag=4) block as little-endian 32-bit words."""
    dw = [int(x) & 0xffffffff for x in data_words]
    return [4, len(dw), addr32] + dw


def inject_sharc_ldr_blocks(e2_raw_bytes, new_blocks_words):
    """Insert LDR blocks right before the FINAL_INIT (tag=0) block in Entry 2."""
    w = list(struct.unpack('<%dI' % (len(e2_raw_bytes) // 4), e2_raw_bytes))
    TAGS = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}

    def nwords(tag, cnt):
        return {5: ((cnt + 1) & ~1) * 3 // 2, 4: cnt, 3: (cnt + 1) // 2,
                6: cnt * 2, 0: 384, 10: cnt, 9: cnt}.get(tag, 0)

    i = 384
    final_init_idx = None
    while i + 3 <= len(w):
        tag, cnt, addr = w[i:i + 3]
        assert tag in TAGS, f'Entry 2 LDR desync at word {i}: tag={tag:#x}'
        if tag == 0:
            final_init_idx = i
            break
        i += 3 + nwords(tag, cnt)

    assert final_init_idx is not None, 'Entry 2 FINAL_INIT (tag=0) not found'
    patched_w = w[:final_init_idx] + list(new_blocks_words) + w[final_init_idx:]
    assert len(patched_w) * 4 <= 0x80000, f'Entry 2 size {len(patched_w)*4} exceeds 512 KiB eMMC partition'
    return struct.pack('<%dI' % len(patched_w), *patched_w)


# Registered primitives in Entry 2 (0x200000..0x20060f) that no stock model, composite or
# root graph references. 0x2aa8, 0x2aaa, 0x2aab and 0x261a (members of Blob 0's root graph)
# and 0x238f (Entry 6's root graph) were in this list and are not free
# (research/KIT_REMOVE_MODELS.md); stock_prims_in_use() checks Blob 0 at build time.
UNUSED_SHARC_PRIMS = (
    (0x9c75, 0x200590),
    (0x0128, 0x200050),
    (0x012e, 0x200058),
    (0x0100, 0x2000a0),
    (0x0838, 0x2000b0),
    (0x2392, 0x200120),
    (0x000e, 0x2001b0),
    (0x0205, 0x2001b8),
    (0x045e, 0x2001d0),
    (0x0207, 0x2002a8),
    (0x2ab6, 0x2002c8),
    (0x021f, 0x200318),
    (0x012c, 0x200348),
    (0x012d, 0x2003d0),
    (0x0130, 0x2003d8),
    (0x0087, 0x2004b8),
    (0x020d, 0x200540),
    (0x0105, 0x200550),
    (0x0104, 0x200558),
)


def stock_prims_in_use(l6ia_bytes):
    """Primitive ids that Blob 0's root graph or any of its composites has as a member."""
    e4 = get_entry_swapped(l6ia_bytes, 4)
    w = struct.unpack('<%dI' % (len(e4) // 4), e4)
    ln, off = w[w[3]], w[w[3] + 1]
    b0 = w[off: off + ln]
    used = {b0[b0[0xb] + 20 * k + 6] for k in range(b0[0xa])}
    ct = b0[0x10]
    for c in range(b0[0xf]):
        hdr = b0[ct + 7 * c: ct + 7 * c + 7]
        used |= {b0[hdr[3] + 20 * k + 6] for k in range(hdr[2])}
    return used


def _scan_e2_injected(e2_raw_bytes):
    """Return (used_pm_end_in_block2, hooked_prim_addrs) from already-injected LDR blocks in Entry 2."""
    w = struct.unpack('<%dI' % (len(e2_raw_bytes) // 4), e2_raw_bytes)
    TAGS = {5: lambda c: ((c + 1) & ~1) * 3 // 2, 4: lambda c: c, 3: lambda c: (c + 1) // 2,
            6: lambda c: c * 2, 0: lambda c: 384, 10: lambda c: c, 9: lambda c: c}
    pm_end = 0x0c4ef8
    hooked_addrs = set()
    i = 384
    while i + 3 <= len(w):
        tag, cnt, addr = w[i:i + 3]
        if tag == 0:
            break
        nw = TAGS.get(tag, lambda c: 0)(cnt)
        if tag == 5 and 0x0c4ef8 <= addr < 0x0c5554:
            pm_end = max(pm_end, (addr + cnt + 1) & ~1)
        elif tag == 4 and cnt == 8 and 0x200000 <= addr < 0x200610:
            hooked_addrs.add(addr)
        i += 3 + nw
    return pm_end, hooked_addrs


SHARC_BLOB0_MAX_WORDS = 0x0008ee00  # Expanded Blob 0 buffer @ 0x21c400..0x2ab200 (585,216 words)
HEAP6_MOVED = (0x0030d100, 0x00324497)  # where expand_sharc_blob0_buffer puts SHARC Heap 6


# Heap 6 is set up as [start, end, current] and cleared from its start; all three
# loads are patched. Its new place, 0x30d100..0x324497, lies between the 0x800-word
# block pool (0x2ab5ee..0x2eb5ee) and Heap 4 (from 0x328000); no SHARC code names
# any address there. The enlarged buffer ends at 0x2ab200, before Heap 7 (0x2ab244).
def expand_sharc_blob0_buffer(e2_raw_bytes):
    """Expand the SHARC DSP's Blob 0 buffer in Entry 2 from 0x77aac (490,156 words) to 0x8ee00
    (585,216 words, covering 0x0021c400..0x002ab200) so the SHARC accepts an expanded
    Blob 0 at boot, and move SHARC Heap 6 (0x17397 words), which the enlarged buffer
    would overlap, from 0x00293eac..0x002ab243 to free DDR2 at 0x0030d100..0x00324497."""
    w = list(struct.unpack('<%dI' % (len(e2_raw_bytes) // 4), e2_raw_bytes))

    # 1. the buffer size: R0 = 0x00077aac -> R0 = 0x0008ee00
    pair_6384 = (w[37192], w[37193])
    assert pair_6384 in ((0x0f000007, 0x7aac1901), (0x0f000008, 0xee001901)), \
        f'unexpected buffer size words at w[37192..37193]: {pair_6384[0]:#010x}, {pair_6384[1]:#010x}'
    changed = (pair_6384 == (0x0f000007, 0x7aac1901) or w[41966] == 0x00293eac)
    w[37192] = 0x0f000008
    w[37193] = 0xee001901

    # 2. Heap 6 0x293eac..0x2ab243 -> 0x30d100..0x324497
    #    w[41966]: R23 = 0x00293eac (its start and current pointer)
    #    w[41971]: R19 = 0x002ab243 (its end)
    #    w[41975..41976]: R4 = 0x00293eac (the start of the clear)
    tup_87c1 = (w[41966], w[41971], w[41975], w[41976])
    assert tup_87c1 in (
        (0x00293eac, 0x002ab243, 0x0f040029, 0x3eac727e),
        (0x00293eac, 0x002c3397, 0x0f04002a, 0xc000727e),
        (0x0030d100, 0x00324497, 0x0f040030, 0xd100727e),
    ), f'unexpected Heap 6 words at w[41966,41971,41975..41976]: {[hex(x) for x in tup_87c1]}'
    w[41966] = 0x0030d100
    w[41971] = 0x00324497
    w[41975] = 0x0f040030
    w[41976] = 0xd100727e

    return struct.pack('<%dI' % len(w), *w), changed


def patch_kernel(l6ia_bytes, asm_src, asm_name='kernel.asm', prim=None, pm_base=None, relocate=True, log=print):
    """Entry 2: the kernel assembled from asm_src (its .section pm and dm as LDR
    INIT blocks, booted before the stock FINAL_INIT) and an unused primitive slot
    pointed at its entry, the primitive add_model's host calls. `prim` is the
    (id, descriptor address) pair from UNUSED_SHARC_PRIMS (default: the first not
    yet hooked, 0x9c75 on a stock image). `pm_base` replaces the token KIT_PM_BASE
    in the source (default: the first free instruction of the Block 2 tail).
    With relocate (the old command line's way) a `.section pm 0xc4ef8` moves to
    the first free instruction; the kit places code itself and turns it off.
    Returns (new l6ia bytes, info dict)."""
    entries = l6ia.parse(l6ia_bytes)
    e2_raw = l6ia_bytes[entries[2]['payload_off']: entries[2]['payload_off'] + entries[2]['payload_len']]
    used_pm_end, hooked_addrs = _scan_e2_injected(e2_raw)
    ldr_words = []

    if 'KIT_PM_BASE' in asm_src:
        asm_src = re.sub(r'\bKIT_PM_BASE\b', f'{pm_base if pm_base is not None else used_pm_end:#08x}', asm_src)
    elif relocate and used_pm_end > 0x0c4ef8:
        asm_src = re.sub(r'(\.section\s+pm\s+)0x0*c4ef8\b', f'\\g<1>{used_pm_end:#08x}', asm_src, flags=re.I)
    secs, syms = sasm.assemble(asm_src, asm_name)
    pm_secs = [s for s in secs if s.kind == 'pm']
    entry_addr = syms.get('CUSTOM_AMP_ENTRY', pm_secs[0].addr if pm_secs else secs[0].addr)
    for s in secs:
        if s.kind == 'pm':
            assert any(lo <= s.addr and s.addr + len(s.words) <= hi
                       for lo, hi in ((0x0c4ef8, 0x0c5554), (0x0e302c, 0x0e5555))), \
                f'PM kernel at {s.addr:#x}: neither in Block 2\'s tail nor in Block 3\'s free region'
            ldr_words += pack_init_l48(s.addr, s.words)
            log(f"[+] Entry 2: assembled {len(s.words)} 48-bit instructions from {asm_name} @ PM {s.addr:#x}")
        elif s.kind == 'dm':
            ldr_words += pack_init_l32(s.addr, s.words)
            log(f"[+] Entry 2: assembled {len(s.words)} 32-bit DM words @ DM {s.addr:#x}")

    if prim is None:
        prim = next(((pid, paddr) for pid, paddr in UNUSED_SHARC_PRIMS if paddr not in hooked_addrs), None)
        if prim is None:
            raise SystemExit('All 24 unused SHARC primitive slots in Entry 2 are already hooked')
    elif prim[1] in hooked_addrs:
        raise SystemExit(f'primitive {prim[0]:#06x} @ {prim[1]:#x} is already hooked')
    prim_id, prim_addr = prim
    ldr_words += pack_init_l32(prim_addr, [prim_id, 0x611e90, 0x0, 0x611ef4, 0x611ddd, entry_addr, 0x91, 0x0d])
    log(f"[+] Entry 2: hooked unused primitive {prim_id:#06x} @ {prim_addr:#x} -> kernel {entry_addr:#x} (dm=145, pm=13)")

    replaced = {2: l6ia.swap32(inject_sharc_ldr_blocks(e2_raw, ldr_words))}
    new_l6ia, old_end, new_end = l6ia.rebuild_archive(l6ia_bytes, replaced)
    log(f"[+] L6IA {old_end:#x} -> {new_end:#x} bytes, delta {new_end - old_end:+d} B")
    return new_l6ia, {'prim': prim_id, 'prim_desc': prim_addr, 'entry': entry_addr,
                      'sections': [(s.kind, s.addr, len(s.words)) for s in secs], 'ldr_words': len(ldr_words)}


def cmd_patch(args):
    l6ia_bytes, is_hxf = load_l6ia_from_any(args.input)
    new_l6ia, _ = patch_kernel(l6ia_bytes, open(args.asm).read(), os.path.basename(args.asm))
    donor = args.input if is_hxf else args.donor
    save_l6ia_to_any(new_l6ia, args.output, donor_hxf=donor)
    print(f"[+] Wrote patched firmware to {args.output}")


E0_MAX = 0x8000 * 512 - 512         # Entry 0's partition, less the sub-header sector
E3_MAX = 0x800 * 512 - 512          # Entry 3's partition, less the sub-header sector
E4_MAX = (0x11005 - 0x940d) * 512   # Entry 4's partition (15.5 MiB)

# Entry 0 (the Cortex-M4 application) addresses for each unit's v3.80.0, keyed by
# where its code segment seg[6] loads. Every entry the build changes (2, 3, 4) is
# byte-identical between the HX Stomp and the HX Stomp XL; Entry 0 is a different
# build of the same code. The
# XL's were found by matching 80 bytes around each Stomp address; every one is
# checked again below by the table it points to.
E0_DEVICES = {
    0x28d8fa80: types.SimpleNamespace(
        NAME='HX Stomp',
        TAB1_BASE_PTRS=(0x28e01c08, 0x28e01c6c, 0x28e01c88, 0x28e01d2c, 0x28e01e80),
        TAB1_END_PTR=0x28e01c70,
        TAB1_CNT_M1_INSNS=(0x28e01c52, 0x28e01ca2, 0x28e01d78, 0x28e01e02),
        TAB1_CNT_INSN=0x28e01c74,
        TAB2_BASE_PTR=0x28de8fd4, TAB2_P5_PTR=0x28de8fd8, TAB2_CNT_INSN=0x28de8f30,
        BLIST_PTR_TAB=0x28e3e00c, BLIST_CNT_TAB=0x28e3e13c,
        SUBCAT_CNT=0x28e3e26c,      # u32[19]: subcategories (browser folders) a category has
        SUBCAT_NAMES=0x28e3e2b8),   # char[19][4][26]: their names (getter 0x28e011d0)
    0x28d92230: types.SimpleNamespace(
        NAME='HX Stomp XL',
        TAB1_BASE_PTRS=(0x28e07d28, 0x28e07d8c, 0x28e07da8, 0x28e07e4c, 0x28e07fa0),
        TAB1_END_PTR=0x28e07d90,
        TAB1_CNT_M1_INSNS=(0x28e07d72, 0x28e07dc2, 0x28e07e98, 0x28e07f22),
        TAB1_CNT_INSN=0x28e07d94,
        TAB2_BASE_PTR=0x28def014, TAB2_P5_PTR=0x28def018, TAB2_CNT_INSN=0x28deef70,
        BLIST_PTR_TAB=0x28e44774, BLIST_CNT_TAB=0x28e448a4,
        SUBCAT_CNT=0x28e449d4, SUBCAT_NAMES=0x28e44a20),
}
E0_BLIST_SLOTS = 76


def e0_device(segs):
    """The E0_DEVICES entry of an Entry 0 (stock, or already changed by add-model)."""
    dev = E0_DEVICES.get(segs[6][3])
    if dev is None:
        raise SystemExit(f'Entry 0 code segment at {segs[6][3]:#x} is neither the HX Stomp\'s nor the XL\'s '
                         f'v3.80.0; use HX_Stomp_v3.80.0_0x103966115.hxf or HX_Stomp_XL_v3.80.0_0x103966115.hxf')
    return dev


def _align(n, a):
    return (n + a - 1) & ~(a - 1)


def _decode_thumb_movw(b4):
    """Decode a 32-bit Thumb-2 `movw Rd, #imm16` instruction into (rd, imm16)."""
    hw1, hw2 = struct.unpack_from('<2H', b4, 0)
    assert (hw1 & 0xfbf0) == 0xf240 and (hw2 & 0x8000) == 0, f'not a Thumb-2 movw instruction: {hw1:#06x} {hw2:#06x}'
    imm4 = hw1 & 0xf
    i_bit = (hw1 >> 10) & 1
    imm3 = (hw2 >> 12) & 0x7
    rd = (hw2 >> 8) & 0xf
    imm8 = hw2 & 0xff
    imm16 = (imm4 << 12) | (i_bit << 11) | (imm3 << 8) | imm8
    return rd, imm16


def _encode_thumb_movw(rd, imm16):
    """Encode a 32-bit Thumb-2 `movw Rd, #imm16` instruction as 4 bytes."""
    assert 0 <= rd <= 15 and 0 <= imm16 <= 0xffff
    hw1 = 0xf240 | (((imm16 >> 11) & 1) << 10) | ((imm16 >> 12) & 0xf)
    hw2 = (((imm16 >> 8) & 0x7) << 12) | ((rd & 0xf) << 8) | (imm16 & 0xff)
    return struct.pack('<2H', hw1, hw2)


def _parse_e0_segments(e0_buf):
    """Return list of (hdr_off, payload_off, slen, dst, next_off) for Entry 0."""
    magic, size, icrc, ver, nsegs = struct.unpack_from('<5I', e0_buf, 0)
    assert magic == 0x230b0c5e and ver == 2 and nsegs == 7, f'unexpected Entry 0 header: magic={magic:#x} ver={ver} nsegs={nsegs}'
    assert size == len(e0_buf), f'Entry 0 header size {size:#x} != len {len(e0_buf):#x}'
    segs = []
    off = 0x34
    for _ in range(nsegs):
        slen, dst, next_off = struct.unpack_from('<3I', e0_buf, off)
        assert next_off == off + 12 + slen, f'Entry 0 segment desync at {off:#x}'
        segs.append((off, off + 12, slen, dst, next_off))
        off = next_off
    return segs


def _e0_vaddr_to_foff(segs, vaddr, length=4):
    for _, poff, slen, dst, _ in segs:
        if dst <= vaddr and vaddr + length <= dst + slen:
            return poff + (vaddr - dst)
    raise SystemExit(
        f'Entry 0 address {vaddr:#x} (+{length}) not mapped in the Entry 0 segments; '
        f'make sure input is HX Stomp or XL v3.80.0'
    )


def add_model_entry0(e0, src_name_idx, new_name_idx, display_name, short_name=None, preset_id=None, dsp_cost=None,
                     n_params=None, folder=None, fx=False):
    """Update the Cortex-M4 main application (Entry 0, HX Stomp or XL v3.80.0; addresses below are the Stomp's) for a new model:
      1. Static Model Table (823 x 12 B @ 0x28017994 -> 824 x 12 B):
         appends {new_name_idx, preset_id, 0, src_dsp_cost}, choosing a free
         preset_id <= 832 (default 147), and patches all 6 table pointers
         (including quicksort @ 0x28e01c08) and 5 movw count immediates.
      2. UI Model Info Table (825 x 44 B @ 0x280023bc -> 826 x 44 B):
         searched linearly when a block or preset loads; clones
         src's 44-byte row with new_name_idx and 16-byte shortDisplayName, and
         patches the 2 literal pointers (0x28de8fd4/d8) and movw count (0x28de8f30).
      3. UI Browser Lists (48-byte items via 0x28e3e00c ptrs and 0x28e3e13c counts):
         for every browser list containing src_name_idx (e.g. (11,0), (11,2), (12,0)),
         relocates the list with a cloned 48-byte entry appended and increments its count.
         With `folder` (category, name), the model goes not into that category's
         lists but into a new browser folder (subcategory) of its own there, as
         Preamp's one-item "Mic": the category's subcategory count + 1, the name,
         a one-item list (data only, no code changes).
      All relocated tables are appended to the end of seg[6] (at 0x28e3fadc+), which is
      unused SDRAM well below the bootloader's 0x29f00000 ceiling."""
    e0 = bytearray(e0)
    segs = _parse_e0_segments(e0)
    A = e0_device(segs)

    def vread(va, ln):
        fo = _e0_vaddr_to_foff(segs, va, ln)
        return bytes(e0[fo: fo + ln])

    def vwrite(va, data):
        fo = _e0_vaddr_to_foff(segs, va, len(data))
        e0[fo: fo + len(data)] = data

    def vu32(va):
        return struct.unpack_from('<I', e0, _e0_vaddr_to_foff(segs, va, 4))[0]

    def vu16(va):
        return struct.unpack_from('<H', e0, _e0_vaddr_to_foff(segs, va, 2))[0]

    # --- 1. Static Model Table (12-byte rows: <IHHI = {name_idx, preset_id, 0, dsp_cost}) ---
    tab1_addr = vu32(A.TAB1_BASE_PTRS[0])
    for pva in A.TAB1_BASE_PTRS[1:]:
        assert vu32(pva) == tab1_addr, f'Entry 0 Table 1 pointer mismatch at {pva:#x}: {vu32(pva):#x} != {tab1_addr:#x}'
    rd_cnt, tab1_cnt = _decode_thumb_movw(vread(A.TAB1_CNT_INSN, 4))
    assert vu32(A.TAB1_END_PTR) == tab1_addr + 12 * tab1_cnt, 'Entry 0 Table 1 end pointer mismatch'
    for iva in A.TAB1_CNT_M1_INSNS:
        _, c_m1 = _decode_thumb_movw(vread(iva, 4))
        assert c_m1 == tab1_cnt - 1, f'Entry 0 Table 1 count-1 mismatch at {iva:#x}: {c_m1} != {tab1_cnt - 1}'

    tab1_raw = bytearray(vread(tab1_addr, 12 * tab1_cnt))
    used_pids = set()
    src_tab1_row = None
    for i in range(tab1_cnt):
        m_idx, pid, z, cost = struct.unpack_from('<IHHI', tab1_raw, 12 * i)
        used_pids.add(pid)
        if m_idx == new_name_idx:
            raise SystemExit(f'Entry 0 Table 1 already has string index {new_name_idx}')
        if m_idx == src_name_idx:
            src_tab1_row = (m_idx, pid, z, cost)
    if src_tab1_row is None:
        raise SystemExit(f'Source model (name_idx={src_name_idx}) not found in Entry 0 Table 1')

    free_pids = sorted(set(range(1, 833)) - used_pids)
    if not free_pids:
        raise SystemExit('No free preset model IDs <= 832 left in Entry 0 Table 1')
    new_pid = preset_id if preset_id is not None else free_pids[0]
    if new_pid <= 0 or new_pid > 832 or new_pid in used_pids:
        raise SystemExit(f'Invalid or already-used --preset-id {new_pid}; free IDs <= 832: {free_pids}')

    src_dsp_cost = src_tab1_row[3] if dsp_cost is None else dsp_cost
    tab1_raw += struct.pack('<IHHI', new_name_idx, new_pid, 0, src_dsp_cost)
    new_tab1_cnt = tab1_cnt + 1

    # --- 2. UI Model Info Table (44-byte rows, searched linearly) ---
    tab2_addr = vu32(A.TAB2_BASE_PTR)
    assert vu32(A.TAB2_P5_PTR) == tab2_addr + 5, 'Entry 0 Table 2 +5 pointer mismatch'
    rd_t2, tab2_cnt = _decode_thumb_movw(vread(A.TAB2_CNT_INSN, 4))
    tab2_raw = bytearray(vread(tab2_addr, 44 * tab2_cnt))
    src_tab2_row = None
    for i in range(tab2_cnt):
        row = tab2_raw[44 * i: 44 * (i + 1)]
        m_idx = struct.unpack_from('<I', row, 0)[0]
        if m_idx == src_name_idx:
            src_tab2_row = bytearray(row)
            break
    if src_tab2_row is None:
        raise SystemExit(f'Source model (name_idx={src_name_idx}) not found in Entry 0 44-byte UI table')

    sname_bytes = (short_name if short_name is not None else display_name).encode('latin1')[:16].ljust(16, b'\x00')  # 16 as stock ('Transient Shaper'): byte 20 is a 0
    struct.pack_into('<I', src_tab2_row, 0, new_name_idx)
    src_tab2_row[4:20] = sname_bytes
    if n_params is not None:
        # bytes 24..35: three parameter counts (Entry 3's count for every stock row
        # but a few with hidden ones, e.g. HD2_ChorusMono 7, 9, 9 of 9)
        # (displayParamCount, presetParamCount, n, followEnable, gainReductionMeterCount):
        # an effect's source may hide sync parameters (HD2_ChorusMono 7, 9, 9) or have a
        # meter; the copy shows every one of its own and has neither (FX_MODEL_META_DROP)
        counts = struct.unpack_from('<3I', src_tab2_row, 24)
        assert fx or len(set(counts)) == 1, f'the source row has counts {counts}'
        struct.pack_into('<3I', src_tab2_row, 24, n_params, n_params, n_params)
        if fx:
            struct.pack_into('<2I', src_tab2_row, 36, 0, 0)
    tab2_raw += src_tab2_row
    new_tab2_cnt = tab2_cnt + 1

    # --- 3. UI Browser Lists (19 x 4 = 76 lists of 48-byte items) ---
    dname_bytes = display_name.encode('latin1')[:25].ljust(26, b'\x00')
    reloc_lists = []  # (slot_idx, cat, sub, new_cnt, new_bytes)
    btype_folder = None
    for idx in range(E0_BLIST_SLOTS):
        lptr = vu32(A.BLIST_PTR_TAB + 4 * idx)
        lcnt = vu32(A.BLIST_CNT_TAB + 4 * idx)
        if not lptr or not lcnt:
            continue
        lraw = bytearray(vread(lptr, 48 * lcnt))
        matched_item = None
        for k in range(lcnt):
            item = lraw[48 * k: 48 * (k + 1)]
            btype, m_idx, c_idx, u12 = struct.unpack_from('<IIiH', item, 0)
            if m_idx == src_name_idx:
                matched_item = bytearray(item)
                # When c_idx == -1, u12 is the amp's preset_model_id; when c_idx != -1, u12 is the companion cab's preset_model_id
                new_u12 = new_pid if c_idx == -1 else u12
                struct.pack_into('<IIiH', matched_item, 0, btype, new_name_idx, c_idx, new_u12)
                matched_item[14:40] = dname_bytes
                struct.pack_into('<2I', matched_item, 40, 1, 0)
                break
        if matched_item is not None and folder and idx // 4 == folder[0]:
            if btype_folder is None and c_idx == -1:
                btype_folder = bytes(matched_item)
        elif matched_item is not None:
            lraw += matched_item
            reloc_lists.append((idx, idx // 4, idx % 4, lcnt + 1, bytes(lraw)))
    if folder:
        cat, fname = folder
        assert btype_folder is not None, f'the source model is in no list of category {cat}'
        nsub = vu32(A.SUBCAT_CNT + 4 * cat)
        fbytes = fname.encode('latin1')[:25].ljust(26, b'\x00')
        have = [s for s in range(nsub) if vread(A.SUBCAT_NAMES + 104 * cat + 26 * s, 26) == fbytes]
        if have:                                    # the folder exists (an earlier add-model): append
            sub = have[0]
            lptr = vu32(A.BLIST_PTR_TAB + 4 * (4 * cat + sub))
            lcnt = vu32(A.BLIST_CNT_TAB + 4 * (4 * cat + sub))
            reloc_lists.append((4 * cat + sub, cat, sub, lcnt + 1, vread(lptr, 48 * lcnt) + btype_folder))
        else:
            sub = nsub
            assert sub < 4 and not vu32(A.BLIST_PTR_TAB + 4 * (4 * cat + sub)), f'category {cat} has no free folder'
            # past the count, a name slot may still hold a stale name (EQ, cat 4: "Legacy"); it is overwritten
            assert fx or not any(vread(A.SUBCAT_NAMES + 104 * cat + 26 * sub, 26)), 'the folder name slot is not empty'
            vwrite(A.SUBCAT_CNT + 4 * cat, struct.pack('<I', sub + 1))
            vwrite(A.SUBCAT_NAMES + 104 * cat + 26 * sub, fbytes)
            reloc_lists.append((4 * cat + sub, cat, sub, 1, btype_folder))

    if not reloc_lists:
        raise SystemExit(f'Source model (name_idx={src_name_idx}) not found in any Entry 0 UI browser list')

    # --- 4. Append relocated tables to the end of seg[6] and patch references ---
    s6_hdr_off, s6_poff, s6_slen, s6_dst, s6_next_off = segs[6]
    assert s6_slen % 4 == 0, f'Entry 0 seg[6] length {s6_slen:#x} is not 4-byte aligned'
    cur_va = s6_dst + s6_slen
    appended = bytearray()

    new_tab1_addr = cur_va + len(appended)
    appended += tab1_raw

    new_tab2_addr = cur_va + len(appended)
    appended += tab2_raw

    blist_addrs = []
    for idx, cat, sub, new_cnt, lbytes in reloc_lists:
        l_va = cur_va + len(appended)
        appended += lbytes
        blist_addrs.append((idx, cat, sub, new_cnt, l_va))

    assert len(appended) % 4 == 0

    # Patch Table 1 pointers & counts
    for pva in A.TAB1_BASE_PTRS:
        vwrite(pva, struct.pack('<I', new_tab1_addr))
    vwrite(A.TAB1_END_PTR, struct.pack('<I', new_tab1_addr + len(tab1_raw)))
    vwrite(A.TAB1_CNT_INSN, _encode_thumb_movw(rd_cnt, new_tab1_cnt))
    for iva in A.TAB1_CNT_M1_INSNS:
        rd_i, _ = _decode_thumb_movw(vread(iva, 4))
        vwrite(iva, _encode_thumb_movw(rd_i, new_tab1_cnt - 1))

    # Patch Table 2 pointers & count
    vwrite(A.TAB2_BASE_PTR, struct.pack('<I', new_tab2_addr))
    vwrite(A.TAB2_P5_PTR, struct.pack('<I', new_tab2_addr + 5))
    vwrite(A.TAB2_CNT_INSN, _encode_thumb_movw(rd_t2, new_tab2_cnt))

    # Patch UI Browser List pointers & counts
    for idx, cat, sub, new_cnt, l_va in blist_addrs:
        vwrite(A.BLIST_PTR_TAB + 4 * idx, struct.pack('<I', l_va))
        vwrite(A.BLIST_CNT_TAB + 4 * idx, struct.pack('<I', new_cnt))

    # Splice `appended` at the end of seg[6], update seg[6] header and Entry 0 size + CRC32
    new_s6_slen = s6_slen + len(appended)
    new_s6_next_off = s6_poff + new_s6_slen
    out_e0 = bytearray(e0[:s6_next_off]) + appended
    pad_len = (-len(out_e0)) & 3
    out_e0 += b'\x00' * pad_len
    struct.pack_into('<3I', out_e0, s6_hdr_off, new_s6_slen, s6_dst, new_s6_next_off)
    struct.pack_into('<I', out_e0, 4, len(out_e0))
    out_e0 = bytearray(l6ia.fix_internal_crcs(out_e0))
    if len(out_e0) > E0_MAX:
        raise SystemExit(f'Entry 0 would be {len(out_e0):#x} bytes; its partition holds {E0_MAX:#x}')
    return bytes(out_e0), new_pid, src_dsp_cost, blist_addrs


# --- IR-name title (opt-in: kit.py build --ir-title) -------------------------------------
# The stock edit screen shows a User IR's name only in the block title, and only for a
# block whose browser category is 15 (IR). Two 6-byte sites in Entry 0 (HX Stomp 3.80.0)
# test that category; each becomes a B.W to a small Thumb cave appended to seg[6] that
# also takes the IR path for the listed preset_ids. UI only: the parameter, its DSP value
# and presets are unchanged (research/KIT_IR_NAME_KNOB.md).
#   site A 0x28dbebea (block title):  ldrb r3,[r4,#12]; cmp r3,#15; bne 0x28dbebfe
#   site B 0x28dbf72e (knob drawing): ldrb r3,[r5,#12]; cmp r3,#15; beq 0x28dbf7d8
# The source parameter a module's first knob (knob 0, the one the IR path reads) must copy.
IR_TITLE_SOURCES = ('HD2_ImpulseResponse2048Mono.Index', 'HD2_ImpulseResponse1024Mono.Index')
# The XL build keeps the IR subcategory in r6 on site A's path (ldrb r6,[r4,#13]); the same
# frame (sub sp,#0x60 / #0x9c, half selector at sp+11) and the same B side. Never run on an XL.
IR_TITLE = {    # by seg[6]'s load address
    0x28d8fa80: types.SimpleNamespace(       # HX Stomp
        SUBCAT_REG=5,
        SITE_A=0x28dbebea, SITE_A_STOCK=bytes.fromhex('237b0f2b06d1'),
        IR_CONT=0x28dbebf0,      # stock IR path: ldrb r5,[r4,#13] ...
        IR_NAME=0x28dbeddc,      # the IR Single name branch (r5 = 0); returns to 0x28dbebf8
        NON_IR=0x28dbebfe,       # stock continuation for any other category
        SITE_B=0x28dbf72e, SITE_B_STOCK=bytes.fromhex('2b7b0f2b51d0'),
        B_RET=0x28dbf734,        # stock: return
        B_IR=0x28dbf7d8,         # stock IR: knob 0 redraws the title
        TARGET_STOCK={0x28dbebf0: bytes.fromhex('657b002d'), 0x28dbeddc: bytes.fromhex('6ff00102'),
                      0x28dbebfe: bytes.fromhex('16f083f9'), 0x28dbf734: bytes.fromhex('27b0bde8'),
                      0x28dbf7d8: bytes.fromhex('1b9b23b1')}),
    0x28d92230: types.SimpleNamespace(       # HX Stomp XL
        SUBCAT_REG=6,
        SITE_A=0x28dc1cd8, SITE_A_STOCK=bytes.fromhex('237b0f2b06d1'),
        IR_CONT=0x28dc1cde,      # stock IR path: ldrb r6,[r4,#13] ...
        IR_NAME=0x28dc1f04,      # the IR Single name branch (r6 = 0); returns to 0x28dc1ce6
        NON_IR=0x28dc1cec,
        SITE_B=0x28dc281e, SITE_B_STOCK=bytes.fromhex('2b7b0f2b51d0'),
        B_RET=0x28dc2824,
        B_IR=0x28dc28c8,
        TARGET_STOCK={0x28dc1cde: bytes.fromhex('667b002e'), 0x28dc1f04: bytes.fromhex('6ff00102'),
                      0x28dc1cec: bytes.fromhex('1bf030fe'), 0x28dc2824: bytes.fromhex('27b0bde8'),
                      0x28dc28c8: bytes.fromhex('1b9b23b1')}),
}


def thumb_bw(src, dst):
    """Thumb-2 B.W (T4) at src to dst."""
    off = dst - (src + 4)
    assert off % 2 == 0 and -(1 << 24) <= off < (1 << 24), f'B.W {src:#x} -> {dst:#x} out of range'
    s, i1, i2 = (off >> 24) & 1, (off >> 23) & 1, (off >> 22) & 1
    j1, j2 = (~(i1 ^ s)) & 1, (~(i2 ^ s)) & 1
    return struct.pack('<2H', 0xf000 | (s << 10) | ((off >> 12) & 0x3ff),
                       0x9000 | (j1 << 13) | (j2 << 11) | ((off >> 1) & 0x7ff))


def _thumb_modimm(v):
    """Thumb-2 modified immediate (i:imm3:imm8) for v, or None."""
    if v < 256:
        return v
    for rot in range(8, 32):
        x = ((v << rot) | (v >> (32 - rot))) & 0xffffffff     # rotate left by rot = undo ROR rot
        if 0x80 <= x <= 0xff:
            return (rot << 7) | (x & 0x7f)
    return None


def _cmp_r3(v):
    """cmp r3, #v (16-bit for v < 256, else cmp.w)."""
    if v < 256:
        return struct.pack('<H', 0x2b00 | v)
    m = _thumb_modimm(v)
    if m is None:
        raise SystemExit(f'--ir-title: preset_id {v} is no Thumb-2 immediate (cmp r3, #{v})')
    return struct.pack('<2H', 0xf1b3 | ((m >> 11) << 10), 0x0f00 | (((m >> 8) & 7) << 12) | (m & 0xff))


def ir_title_cave(cave_va, pids, X):
    """The cave at cave_va: (bytes, caveA address, caveB address). Only r3 is used, and the
    subcategory register X.SUBCAT_REG (r5 Stomp, r6 XL) on the IR path (as the stock code there); every exit leaves r3 as the stock code would have
    or goes where r3 is written before it is read.
      caveA: ldrb r3,[r4,#12]; cmp r3,#15; bne 1f; b.w IR_CONT
          1: ldrb.w r3,[sp,#11]; cbnz r3,3f      @ the cab half of an Amp+Cab block: no
             ldr.w r3,[r4,#1]                    @ the block's preset_id (half 0)
             {cmp r3,#pid; beq 2f}...; b 3f
          2: movs r5|r6,#0; b.w IR_NAME          @ as an IR Single block, knob 0
          3: ldrb r3,[r4,#12]; b.w NON_IR
      caveB: ldrb r3,[r5,#12]; cmp r3,#15; beq 4f
             ldr.w r3,[r5,#1]; {cmp r3,#pid; beq 4f}...
             b.w B_RET
          4: b.w B_IR"""
    out = bytearray()
    fix = []                                     # (offset, kind, label)
    labels = {}

    def emit(b):
        out.extend(b)

    def bcc(cond, label):                        # 16-bit conditional branch (T1)
        fix.append((len(out), 'bcc', cond, label)); emit(b'\0\0')

    def bw(dst):
        emit(thumb_bw(cave_va + len(out), dst))

    labels['caveA'] = 0
    emit(bytes.fromhex('237b0f2b')); bcc(1, '1'); bw(X.IR_CONT)
    labels['1'] = len(out)
    emit(bytes.fromhex('9df80b30'))
    fix.append((len(out), 'cbnz', None, '3')); emit(b'\0\0')
    emit(bytes.fromhex('d4f80130'))
    for p in pids:
        emit(_cmp_r3(p)); bcc(0, '2')
    fix.append((len(out), 'b', None, '3')); emit(b'\0\0')
    labels['2'] = len(out)
    emit(struct.pack('<H', 0x2000 | (X.SUBCAT_REG << 8))); bw(X.IR_NAME)
    labels['3'] = len(out)
    emit(bytes.fromhex('237b')); bw(X.NON_IR)
    labels['caveB'] = len(out)
    emit(bytes.fromhex('2b7b0f2b')); bcc(0, '4')
    emit(bytes.fromhex('d5f80130'))
    for p in pids:
        emit(_cmp_r3(p)); bcc(0, '4')
    bw(X.B_RET)
    labels['4'] = len(out)
    bw(X.B_IR)
    for at, kind, cond, label in fix:
        off = labels[label] - (at + 4)
        assert off % 2 == 0
        if kind == 'bcc':
            assert -256 <= off < 256, 'cave branch out of range'
            struct.pack_into('<H', out, at, 0xd000 | (cond << 8) | ((off >> 1) & 0xff))
        elif kind == 'b':
            assert -2048 <= off < 2048
            struct.pack_into('<H', out, at, 0xe000 | ((off >> 1) & 0x7ff))
        else:                                    # cbnz r3 (forward only, 0..126)
            assert 0 <= off <= 126, 'cbnz out of range: too many preset_ids'
            struct.pack_into('<H', out, at, 0xb900 | ((off >> 6) << 9) | (((off >> 1) & 0x1f) << 3) | 3)
    while len(out) % 4:
        out += b'\x00\xbf'                       # nop
    return bytes(out), cave_va + labels['caveA'], cave_va + labels['caveB']


def ir_title_entry0(e0, pids):
    """Entry 0 with the IR-name title for blocks of these preset_ids. Returns (e0, info)."""
    pids = sorted(set(pids))
    if not pids:
        raise SystemExit('--ir-title: no preset_ids')
    e0 = bytearray(e0)
    segs = _parse_e0_segments(e0)
    A = e0_device(segs)
    X = IR_TITLE.get(segs[6][3])
    if X is None:
        raise SystemExit(f'--ir-title: no sites known for the {A.NAME}')

    def vread(va, ln):
        fo = _e0_vaddr_to_foff(segs, va, ln)
        return bytes(e0[fo: fo + ln])

    def vwrite(va, data):
        fo = _e0_vaddr_to_foff(segs, va, len(data))
        e0[fo: fo + len(data)] = data

    for va, want in ((X.SITE_A, X.SITE_A_STOCK), (X.SITE_B, X.SITE_B_STOCK)):
        got = vread(va, 6)
        if got != want:
            already = (struct.unpack_from('<H', got)[0] & 0xf800) == 0xf000 and got[4:] == b'\x00\xbf'
            raise SystemExit(f'--ir-title: Entry 0 at {va:#x} is {got.hex()}, not the stock {want.hex()}'
                             + (' (the patch is already applied)' if already else ''))
    for va, want in X.TARGET_STOCK.items():
        assert vread(va, len(want)) == want, f'Entry 0 at {va:#x}: not the stock code'
    # Each block must be in a non-IR browser list, not subcategory 1: after the IR name the
    # stock code tests r5 = subcategory == 1 (IR Dual) again.
    where = collections.defaultdict(list)
    for idx in range(E0_BLIST_SLOTS):
        lptr, lcnt = (struct.unpack('<I', vread(t + 4 * idx, 4))[0] for t in (A.BLIST_PTR_TAB, A.BLIST_CNT_TAB))
        for k in range(lcnt if lptr else 0):
            _, _, c_idx, u12 = struct.unpack('<IIiH', vread(lptr + 48 * k, 14))
            if c_idx == -1 and u12 in pids:
                where[u12].append((idx // 4, idx % 4))
    for p in pids:
        if not where[p]:
            raise SystemExit(f'--ir-title: preset_id {p} is in no browser list')
        bad = [cs for cs in where[p] if cs[0] == 15 or cs[1] == 1]
        if bad:
            raise SystemExit(f'--ir-title: preset_id {p} is in browser list(s) {bad}: IR, or subcategory 1')

    s6_hdr_off, s6_poff, s6_slen, s6_dst, s6_next_off = segs[6]
    assert s6_slen % 4 == 0 and s6_next_off <= len(e0)
    cave_va = s6_dst + s6_slen
    cave, ca, cb = ir_title_cave(cave_va, pids, X)
    vwrite(X.SITE_A, thumb_bw(X.SITE_A, ca) + b'\x00\xbf')
    vwrite(X.SITE_B, thumb_bw(X.SITE_B, cb) + b'\x00\xbf')
    new_s6_slen = s6_slen + len(cave)
    out_e0 = bytearray(e0[:s6_next_off]) + cave
    out_e0 += b'\x00' * ((-len(out_e0)) & 3)
    struct.pack_into('<3I', out_e0, s6_hdr_off, new_s6_slen, s6_dst, s6_poff + new_s6_slen)
    struct.pack_into('<I', out_e0, 4, len(out_e0))
    out_e0 = bytes(l6ia.fix_internal_crcs(out_e0))
    if len(out_e0) > E0_MAX:
        raise SystemExit(f'Entry 0 would be {len(out_e0):#x} bytes; its partition holds {E0_MAX:#x}')
    return out_e0, {'pids': pids, 'cave': cave_va, 'caveA': ca, 'caveB': cb, 'cave_len': len(cave)}


def ir_title(l6ia_bytes, pids, log=print):
    """ir_title_entry0 on an image's Entry 0. Returns (new l6ia bytes, info)."""
    e0 = get_entry_swapped(l6ia_bytes, 0)
    new_e0, info = ir_title_entry0(e0, pids)
    new_l6ia, _, _ = l6ia.rebuild_archive(l6ia_bytes, {0: new_e0})
    log(f"[+] Entry 0: IR-name title for preset_id {', '.join(map(str, info['pids']))}: "
        f"cave {info['cave_len']} B at {info['cave']:#x}; {len(e0):#x} -> {len(new_e0):#x} bytes")
    return new_l6ia, info


# Blob 0 must keep its stock length: the SHARC loads it into a buffer of exactly
# 0x77aac words at 0x21c400 (the stock Blob 0 ends at 0x77aac, its last composite's
# end) unless expand_sharc_blob0_buffer enlarges it. A longer Blob 0 stops the unit
# at the splash once the loading bar is full.
SHARC_BLOB0_WORDS = 0x77aac
# Blob 0 has no unused composite to clone over: 0x6001ba..0x6001be, once thought unused,
# are the Line 6 Aristocrat, Clarity, Voltage, Kinetic and Oblivion amps, referenced from
# inside blobs 802..813 (overwriting them froze the UI on the unit). So a
# clone is appended and Blob 0 grows (clone_composite_in_blob0, expand_sharc_blob0_buffer).
SHARC_BLOB0_BASE = 0x21c400


def sharc_blob0_check(b0, max_words=SHARC_BLOB0_WORDS):
    """None if the SHARC would take this Blob 0, else why not. Models the SHARC's
    relocation of Blob 0 at boot: every offset is checked (offset + length <= size) and then turned into a pointer
    in place, for the header, the root member table, and every composite header with
    its member records and their connection records. A failed check returns -42 and
    the unit stops at the splash (as with members shared by two composite
    headers: the second header finds pointers where offsets were)."""
    if len(b0) > max_words:
        return f'{len(b0):#x} words, the SHARC buffer holds {max_words:#x}'
    w, size, base = list(b0), len(b0), SHARC_BLOB0_BASE
    rel = lambda a: a - base                    # a relocated pointer back to an offset

    def members(tab, n, where):
        for m in range(n):
            r = rel(tab) + 20 * m
            for ln, off in ((w[r + 7], 8), (w[r + 9], 10), (2 * w[r + 11], 12)):
                if w[r + off] + ln > size:
                    return f'{where} member {m}: field {off} {w[r + off]:#x} + {ln:#x} past the end'
                w[r + off] += base
            k = w[r + 1] >> 1
            if 3 * k + w[r + 2] > size:
                return f'{where} member {m}: connection list {w[r + 2]:#x} past the end'
            w[r + 2] += base
            for j in range(k):
                c = rel(w[r + 2]) + 3 * j
                if (w[c] & ~1) + w[c + 1] > size:
                    return f'{where} member {m} connection {j}: {w[c + 1]:#x} past the end'
                w[c + 1] += base
        return None

    if w[1] + w[2] > size:
        return 'header field 2 past the end'
    w[2] += base
    if 7 * w[0xf] + w[0x10] > size:
        return 'composite table past the end'
    w[0x10] += base
    if 20 * w[0xa] + w[0xb] > size:
        return 'root member table past the end'
    w[0xb] += base
    err = members(w[0xb], w[0xa], 'root')
    if err:
        return err
    if 4 * w[0xc] + w[0xd] > size:
        return 'table at field 0xd past the end'
    w[0xd] += base
    for i in range(w[0xf]):
        h = rel(w[0x10]) + 7 * i
        if 20 * w[h + 2] + w[h + 3] > size:
            return f'composite {0x600000 + i:#x}: members past the end (shared with another header?)'
        w[h + 3] += base
        err = members(w[h + 3], w[h + 2], f'composite {0x600000 + i:#x}')
        if err:
            return err + ' (shared with another header?)'
        if 4 * w[h + 4] + w[h + 5] > size:
            return f'composite {0x600000 + i:#x}: ports past the end'
        w[h + 5] += base
    return None


def clone_composite_in_blob0(b0, src_comp_id):
    """Append a relocated copy of composite `src_comp_id` (e.g. 0x600189) to Blob 0 as a
    new composite (0x600000 + n_comp: 0x6001c6, 0x6001c7, ...), with a copy of the
    composite table one entry longer after it; no existing composite changes. Blob 0
    grows past the stock SHARC buffer, so this needs Entry 2 patched by
    expand_sharc_blob0_buffer (add-model does both); the result must pass
    sharc_blob0_check with the enlarged size."""
    b0 = list(b0)
    n_comp = b0[0xf]
    ctab = b0[0x10]
    src_idx = src_comp_id - 0x600000
    assert 0 <= src_idx < n_comp, f'invalid source composite {src_comp_id:#x}'

    src_hdr = b0[ctab + 7 * src_idx: ctab + 7 * (src_idx + 1)]
    src_start = src_hdr[3]
    src_end = src_hdr[5] + 4 * src_hdr[4]

    dst_idx = n_comp
    new_ctab = len(b0)
    dst_start = new_ctab + 7 * (n_comp + 1)
    delta = dst_start - src_start

    slice_w = list(b0[src_start: src_end])
    for m in range(src_hdr[2]):
        rbase = 20 * m
        c_rel = slice_w[rbase + 2] - src_start
        for j in range(slice_w[rbase + 1] >> 1):     # as many connection records as the SHARC walks
            assert src_start <= slice_w[c_rel + 3 * j + 1] <= src_end
            slice_w[c_rel + 3 * j + 1] += delta
        for col in (2, 8, 10, 12):
            assert src_start <= slice_w[rbase + col] <= src_end
            slice_w[rbase + col] += delta

    new_hdr = [src_hdr[0], src_hdr[1], src_hdr[2], src_hdr[3] + delta, src_hdr[4], src_hdr[5] + delta, src_hdr[6]]
    b0.extend(b0[ctab: ctab + 7 * n_comp])
    b0.extend(new_hdr)
    b0.extend(slice_w)
    b0[0xf] = n_comp + 1
    b0[0x10] = new_ctab
    err = sharc_blob0_check(b0, SHARC_BLOB0_MAX_WORDS)
    assert err is None, f'the SHARC (with its Blob 0 buffer enlarged) would refuse this Blob 0: {err}'
    return b0, 0x600000 + dst_idx


# NAM Lite (tools/sharc/nam_lite_kernel.asm): an amp whose whole audio path is
# graph input -> primitive 0x9c75 -> graph output, on a clone of the source amp's
# composite (HD2_AmpLine6Clarity's). Its parameters are its own, consistent in
# all three places that count them: Entry 3 (parameters and states), the blob's
# parameter map (one input node per slot) and Entry 0 Table 2 (three counts).
# A parameter map with slots Entry 3 had no parameter for showed the wrong
# model name on the unit, and Table 2's counts changed alone crashed the
# browser; all three must change together.
NAM_HOST_COMPOSITE = 0x6001a9   # Line 6 Clarity & co.: in port, the amp (one sub-composite), out port
# (slot, source model, source parameter, pid, displayName or None, default or None):
# 0x611ddd puts pid p (5..144) in DM(p, I0). Model, the first knob, is the IR block's
# IR Select (an integer 1..128; on an amp the unit shows the number, not the IR's
# name); Bass..Presence are a tone stack, flat at 0.5; Drive 0 dB and Ch Vol +12 dB at 0.5;
# Polarity (a switch, Normal by default) at pid 15: DM(12..14) are the kernel's.
NAM_PARAMS = ((1, 'HD2_ImpulseResponse2048Mono', 'Index', 7, 'Model', None),
              (2, 'HD2_AmpLine6Clarity', 'Drive', 5, 'Input', 0.5),   # shown as Input: the input level
              (3, 'HD2_AmpLine6Clarity', 'Bass', 8, None, 0.5),
              (4, 'HD2_AmpLine6Clarity', 'Mid', 9, None, 0.5),
              (5, 'HD2_AmpLine6Clarity', 'Treble', 10, None, 0.5),
              (6, 'HD2_AmpLine6Clarity', 'Presence', 11, None, 0.5),
              (7, 'HD2_AmpLine6Clarity', 'ChVol', 6, None, 0.5),
              (8, 'HD2_PreampVintagePre', 'Polarity', 15, None, None))   # Normal / Inverted (nam_multi's P_PHASE)
NAM_INPUT_OP = {3: 0x0a, 2: 0x0b, 1: 0x0d}   # parameter type (float, int, bool) -> pmap input node op
# Tempo sync is three coupled parameters (a float, a note list SyncSelectN and a bool
# TempoSyncN) that the stock pmap combines before one float reaches the primitive
# (research/KIT_EFFECT_HOSTS.md 5.2). nam_host_blob has no such chain, so the kit refuses
# the list and the bool as sources and drops the float's sync meta: the knob is free-running.
SYNC_PARAMS = ('SyncSelect', 'TempoSync')
PARAM_META_DROP = ('sync', 'coupledIndex', 'toggleSelectIndex')


def nam_params(e3, info, spec=None):
    """NAM_PARAMS resolved against Entry 3: per slot a dict with the source
    parameter's record, its meta bytes (displayName replaced when asked) and
    its state record's name, the pid and the input op. States are one per
    input node of a model's parameter map, in node order (every stock model)."""
    S = info['strings']
    out = []
    for slot, mname, pname, pid, disp, dflt in (spec or NAM_PARAMS):
        m = find_model(info, mname)
        p = next((p for p in m['params'] if p['name'] == pname), None)
        if p is None:
            raise SystemExit(f'{mname} has no parameter {pname!r} '
                             f'(it has {", ".join(q["name"] for q in m["params"])})')
        if pname.startswith(SYNC_PARAMS) or p['meta'].get('persistent') == 'note':
            raise SystemExit(f'{mname}.{pname} is half of a tempo-sync pair, which the kit does not build yet: '
                             f'use the float knob it is coupled to (its sync is left out)')
        d = m['words']
        st = None
        for k in range(d[6]):
            _, _, ni, _, _ = struct.unpack_from('<5I', e3, d[10] + 20 * k)
            if S[ni].split('.')[0] == pname + 'State':
                st = S[ni]
        assert st, f'{mname} has no state for {pname}'
        pm_cnt, pm_off = struct.unpack_from('<2I', e3, p['off'])
        meta = []                                   # (key, record type, value: a string when type 7)
        for k in range(pm_cnt):
            ks, kt, kv = struct.unpack_from('<3I', e3, pm_off + 12 * k)
            v = S[kv] if kt == 7 else kv
            if S[ks] in PARAM_META_DROP:
                continue
            if disp and S[ks] in ('displayName', 'displayNameShort'):
                v = disp
            meta.append((S[ks], kt, v))
        if disp and 'displayName' not in [k for k, _, _ in meta]:
            meta.append(('displayName', 7, disp))
        raw = list(struct.unpack_from('<5I3I', e3, p['off']))
        if dflt is not None:
            raw[7] = f2u(dflt)
        raw[4] = slot
        out.append({'slot': slot, 'pid': pid, 'name': pname, 'type': p['type'], 'op': NAM_INPUT_OP[p['type']],
                    'raw': raw, 'meta': meta, 'state': st, 'default_word': raw[7]})
    return out


def nam_host_member(b0, comp_id, prim_id=0x9c75, dm_words=0x91, pm_words=0x0d, sdram_words=0):
    """Make member 1 of composite `comp_id` (a clone of NAM_HOST_COMPOSITE) the
    primitive prim_id (dm 145, pm 13), keeping its ports (1 in, 1 out)."""
    ct = b0[0x10]
    hdr = b0[ct + 7 * (comp_id - 0x600000): ct + 7 * (comp_id - 0x600000) + 7]
    assert hdr[2] == 3, f'{comp_id:#x} has {hdr[2]} members, the NAM host wants 3'
    r = hdr[3] + 20
    assert 0x600000 <= b0[r + 6] < 0x601000 and b0[r + 7] == 1 and b0[r + 9] == 1, 'member 1 is not a 1-in 1-out composite'
    b0[r + 6] = prim_id
    b0[r + 11] = 0                  # no static init parameters
    for k in range(15, 20):         # sub-arena sizes: 0 for a primitive, as stock primitive members have
        b0[r + k] = 0
    b0[r + 13], b0[r + 14], b0[r + 15] = dm_words, pm_words, sdram_words   # the instance's DM, PM, SDRAM


# Effect hosts (research/KIT_EFFECT_HOSTS.md 2): the two stock composites of the form
# "input port -> one primitive -> output port", by port width. Member 1 is the primitive,
# on buffer 0 (mono) or buffers 0, 1 (stereo), in place. The composite carries no category:
# that comes from the metadata model's Entry 0 / Entry 3 records.
FX_HOST_COMPOSITES = {0x6000e0: 1,      # HD2_VolPanVolMono / HD2_VolPanGainMono: primitive 0x80 [0>0]
                      0x600096: 2}      # L6SPB_AcousGtrSimStereo: primitive 0x9c51 [0,1>0,1], rec[15] 0x400
# Browser categories (Entry 0 list index // 4) and their Entry 3 'category' meta.
FX_CATEGORIES = {2: 'distortion', 3: 'dynamics', 4: 'eq', 5: 'modulation', 6: 'delay', 7: 'reverb',
                 8: 'pitch', 9: 'filter', 10: 'wah', 16: 'volume'}
# Model meta an effect's copy drops: counts and flags that must agree with Table 2 and the
# new parameters (Table 2 gets n, n, n, 0, 0), and the source's type/legacy/mix options.
FX_MODEL_META_DROP = ('displayParamCount', 'presetParamCount', 'followEnable', 'gainReductionMeterCount',
                      'mix', 'mixDefault', 'legacy', 'type', 'deprecated')
# The slot's model placeholder in each FX harness: what a model's whole tree may take
# (research/KIT_DDR2_BUFFERS.md 1.1). The host's ports take nothing.
FX_BUDGET = {1: dict(dm=0x38b, pm=0x14e, sdram=0x60400),    # mono FX harness 0x600005, member 5
             2: dict(dm=0x3a2, pm=0x1e0, sdram=0x63000)}    # stereo FX harness 0x600004, member 5


def fx_host_member(b0, comp_id, prim_id, dm_words=0x91, pm_words=0x0d, sdram_words=0):
    """Make member 1 of composite `comp_id` (a clone of an FX_HOST_COMPOSITES entry) the
    primitive prim_id with the given instance sizes, keeping its port lists (1 or 2
    buffers each way). Returns the width."""
    ct = b0[0x10]
    hdr = b0[ct + 7 * (comp_id - 0x600000): ct + 7 * (comp_id - 0x600000) + 7]
    assert hdr[2] == 3, f'{comp_id:#x} has {hdr[2]} members, an effect host has 3'
    r = hdr[3] + 20
    width = b0[r + 7]
    assert b0[r + 6] < 0x600000 and width in (1, 2) and b0[r + 9] == width and b0[r + 1] == 0, \
        'member 1 is not a primitive with as many inputs as outputs (1 or 2) and no connections'
    assert [b0[b0[r + 8] + k] for k in range(width)] == list(range(width)) == \
        [b0[b0[r + 10] + k] for k in range(width)], 'member 1 is not in place on buffers 0..width-1'
    budget = FX_BUDGET[width]
    if dm_words > budget['dm'] or pm_words > budget['pm'] or sdram_words > budget['sdram']:
        raise SystemExit(f'instance DM {dm_words:#x} / PM {pm_words:#x} / SDRAM {sdram_words:#x} exceed the '
                         f'{"stereo" if width == 2 else "mono"} FX slot\'s {budget}')
    b0[r + 6] = prim_id
    b0[r + 11] = 0                  # no static init parameters (0x80 had 2, 0x9c51 5)
    for k in range(15, 20):         # SDRAM, sub-arenas, memory record: none (0x9c51 had rec[15] 0x400)
        b0[r + k] = 0
    b0[r + 13], b0[r + 14], b0[r + 15] = dm_words, pm_words, sdram_words
    return width


def nam_host_blob(comp_id, params):
    """A model blob for the NAM host composite `comp_id`: no node-tree changes,
    a parameter map of one input node per parameter (node k for params[k]: op
    0xa float, 0xb int, 0xd bool) and one node per parameter writing member [2]
    (path {1, 2}: the composite's member 1) as its pid.
    The layout, as every stock blob has it:
      pmap header: offsets of tables A (nodes, 10 words), B, C (edges), D (slot
      map), E, F (child graphs), then nA nB nC nD nE nF, then sizes H[12..17]:
      H12 = sum of state words, H13 = nA, H14 = nD + sum n_out + inputs,
      H15 = nC + nD + inputs, H16 = nD, H17 = nE.
      node {data_off, 0, id, op, n_out, state_words, data_len, data_len, is_input, 0};
      op 0xa/0xb/0xd inputs, op 1 write a member param, data {path_off, pid, mode 1 = child}.
      D {node, j, slot, 0} by slot; E {node, j, j, 0} by node (j: the state index).
      pinit {path_off, pid, value_off, kind}: kind 1 on the root feeds slot pid,
      kind 2 calls the member's fn_ctrl. init list {1, word_off}: every word that
      holds a path offset, so the loader turns it into a pointer."""
    n = len(params)
    a_off = 0x18
    data_off = a_off + 10 * 2 * n
    c_off = data_off + 3 * n
    d_off = c_off + 4 * n
    e_off = d_off + 4 * n
    end = e_off + 4 * n
    pm = [a_off, 0, c_off, 0, c_off, 0, d_off, 0, e_off, 0, end, 0]
    pm += [5 * n, 2 * n, 3 * n, 3 * n, n, n]
    pm += [2 * n, 0, n, n, n, 0]
    for k, p in enumerate(params):                  # inputs, nodes 0 .. n-1
        pm += [data_off, 0, k, p['op'], 1, 2, 0, 0, 1, 0]
    for k in range(n):                              # writers, nodes n .. 2n-1
        pm += [data_off + 3 * k, 0, n + k, 1, 0, 3, 3, 3, 0, 0]
    for p in params:
        pm += [0x0e, p['pid'], 1]
    for k in range(n):                              # C: input k -> writer k
        pm += [k, n + k, 0, 0]
    for k, p in sorted(enumerate(params), key=lambda kp: kp[1]['slot']):
        pm += [k, k, p['slot'], 0]
    for k in range(n):
        pm += [k, k, k, 0]
    assert len(pm) == end

    v0 = 0x10
    tree = v0 + 2 * 2 * n
    pmo = tree + 4
    pin = pmo + len(pm)
    ini = pin + 4 * 2 * n
    sub = ini + 2 * 3 * n
    b = [3, 2, tree, 1, ini, 3 * n, pmo, len(pm), sub, 0, pin, 2 * n]
    b += [1, 0, 1, 2]                               # paths [0] (the root) and [2] (member 1)
    for p in params + params:
        b += [1, p['default_word']]
    b += [0, comp_id, 0, 0]                         # node tree: the root only
    b += pm
    for k, p in enumerate(params):
        b += [0x0c, p['slot'], v0 + 2 * k, 1]
    for k, p in enumerate(params):
        b += [0x0e, p['pid'], v0 + 2 * (n + k), 2]
    for k in range(n):
        b += [1, pmo + data_off + 3 * k]
    for k in range(2 * n):
        b += [1, pin + 4 * k]
    assert len(b) == sub
    return b


def pmap_slots_without_param(e4, blob_index, params):
    """Slots in blob `blob_index`'s parameter map (pmap Table 3) with no parameter in
    `params` (parse_entry3_full records). Empty for every stock model."""
    w4 = struct.unpack('<%dI' % (len(e4) // 4), e4)
    d = w4[3]
    ln, off = w4[d + 2 * blob_index], w4[d + 2 * blob_index + 1]
    bw = w4[off: off + ln]
    if not bw or bw[0] != 3 or ln < 12:
        return []
    po = bw[6]
    t3, t4 = bw[po + 6], bw[po + 8]
    slots = {bw[po + t3 + 4 * j + 2] for j in range((t4 - t3) // 4)}
    return sorted(slots - {p['slot'] for p in params})


# The Amp harnesses a kit amp's model is instantiated in, and their model placeholder
# (member 3, composite 0x6000c8): DM 0x596, PM 0x1fa, SDRAM 0x800 in stock 3.80.0. A kit
# block's SDRAM block comes out of that placeholder's SDRAM (research/KIT_DDR2_BUFFERS.md):
# a request above 0x800 fails to bind (silent block) unless it is raised. The slot reserves
# 0x63000 SDRAM words for the whole harness.
AMP_HARNESSES = (0x60000c, 0x60000d, 0x60000f)
AMP_PLACEHOLDER, AMP_PLACEHOLDER_MEMBER, SLOT_SDRAM = 0x6000c8, 3, 0x63000


def raise_amp_harness_sdram(b0, words):
    """Raise the SDRAM of each Amp harness's model placeholder to hold `words` (aligned
    to 0x400, at least the stock 0x800); return the harnesses changed."""
    align = lambda n: (n + 0x3ff) & ~0x3ff
    need = align(max(words, 0x800))
    ct, changed = b0[0x10], []
    for cid in AMP_HARNESSES:
        hdr = b0[ct + 7 * (cid - 0x600000): ct + 7 * (cid - 0x600000) + 7]
        r = hdr[3] + 20 * AMP_PLACEHOLDER_MEMBER
        assert b0[r + 6] == AMP_PLACEHOLDER and b0[r + 13] == 0x596, f'{cid:#x}: member 3 is not the amp placeholder'
        others = sum(align(b0[hdr[3] + 20 * k + 15]) for k in range(hdr[2]) if k != AMP_PLACEHOLDER_MEMBER)
        if others + need > SLOT_SDRAM:
            raise SystemExit(f'{cid:#x}: {need:#x} SDRAM words for the model and {others:#x} for the rest '
                             f'exceed the slot\'s {SLOT_SDRAM:#x}')
        if need > b0[r + 15]:
            b0[r + 15] = need
            changed.append(cid)
    return changed


def add_model_entry4(e4, src_blob_index, nam, prim_id=0x9c75, instance=None, fx=False):
    """Entry 4 with one more blob, the NAM host: a copy of the model's composite
    (NAM_HOST_COMPOSITE) appended to Blob 0 (0x6001c6, 0x6001c7, ...;
    clone_composite_in_blob0) with its amp member made primitive 0x9c75
    (nam_host_member), and a new blob for it (nam_host_blob) at the end of Entry 4,
    the directory relocated. Blob 0 then moves to the tail; Entry 2 must be patched
    to match (expand_sharc_blob0_buffer; cmd_add_model does it).
    Rebuilds the tail region (directory and added blobs) when called repeatedly."""
    w4 = list(struct.unpack('<%dI' % (len(e4) // 4), e4))
    assert w4[0] == 0x28267e5e and w4[1] == 4, f'bad Entry 4 header: {w4[:6]}'
    nblobs, dir_off, b0_off, total_words = w4[2], w4[3], w4[4], w4[5]
    assert total_words == len(w4)
    assert 0 <= src_blob_index < nblobs
    dir_pairs = [(w4[dir_off + 2 * k], w4[dir_off + 2 * k + 1]) for k in range(nblobs)]
    src_ln, src_off = dir_pairs[src_blob_index]
    src_blob_words = list(w4[src_off: src_off + src_ln])

    b0_ln, b0_cur_off = dir_pairs[0]
    b0_words = list(w4[b0_cur_off: b0_cur_off + b0_ln])
    added_blobs = [list(w4[off: off + ln]) for (ln, off) in dir_pairs[864:]]

    tl = src_blob_words[2]
    src_comp_id = src_blob_words[tl + 1]
    if fx:                          # an effect: src is the host model (FX_HOST_COMPOSITES)
        assert src_comp_id in FX_HOST_COMPOSITES, \
            f'an effect host is a model on {", ".join(map(hex, FX_HOST_COMPOSITES))}, not {src_comp_id:#x}'
        b0_words, new_comp_id = clone_composite_in_blob0(b0_words, src_comp_id)
        fx_host_member(b0_words, new_comp_id, prim_id, **(instance or {}))
    else:
        assert src_comp_id == NAM_HOST_COMPOSITE, \
            f'the NAM host wants a model on composite {NAM_HOST_COMPOSITE:#x} (HD2_AmpLine6Clarity), not {src_comp_id:#x}'
        b0_words, new_comp_id = clone_composite_in_blob0(b0_words, src_comp_id)
        nam_host_member(b0_words, new_comp_id, prim_id, **(instance or {}))
        raise_amp_harness_sdram(b0_words, (instance or {}).get('sdram_words', 0))
    err = sharc_blob0_check(b0_words, SHARC_BLOB0_MAX_WORDS)
    assert err is None, err
    src_blob_words = nam_host_blob(new_comp_id, nam)

    added_blobs.append(src_blob_words)
    if dir_off > 6:
        w4 = w4[:dir_off]

    new_blob_idx = nblobs
    new_nblobs = nblobs + 1
    new_dir_off = len(w4)
    cur_end = new_dir_off + 2 * new_nblobs
    dir_pairs[0] = (len(b0_words), cur_end)
    w4[4] = cur_end
    cur_end += len(b0_words)

    dir_pairs = dir_pairs[:864]
    for ab in added_blobs:
        dir_pairs.append((len(ab), cur_end))
        cur_end += len(ab)

    for ln, off in dir_pairs:
        w4.extend((ln, off))
    w4.extend(b0_words)
    for ab in added_blobs:
        w4.extend(ab)

    w4[2] = new_nblobs
    w4[3] = new_dir_off
    w4[5] = len(w4)
    out = struct.pack('<%dI' % len(w4), *w4)
    if len(out) > E4_MAX:
        raise SystemExit(f'Entry 4 would be {len(out):#x} bytes; its partition holds {E4_MAX:#x}')
    return out, new_blob_idx, new_comp_id


def add_model_entry3(e3, src, new_name, display_name, blob_index, nam, drop_meta=()):
    """Entry 3 with one more model: a copy of `src` (a parse_entry3_full model)
    under a new internal name and displayName, with the next model ID and the
    parameters `nam` (nam_params).

    Nothing in stock Entry 3 (0..0xcadb4) moves. The string section and the
    descriptor table are written in the tail region from 0xcae00 (the stock
    size rounded up to 512), and when called repeatedly, the tail region is
    rebuilt in place so each additional model adds only ~680 bytes."""
    e3 = bytearray(e3)
    h = list(struct.unpack_from('<10I', e3, 0))
    magic, ver, tsize, str_off, scrc, str_len, mtab_off, mcnt, gtab_off, gcnt = h
    assert tsize == len(e3), 'Entry 3 size field does not match its length'

    # strings: [nstr][len] records(12 B) data; rel_off is from the data start
    nstr, slen = struct.unpack_from('<2I', e3, str_off)
    assert slen == str_len
    recs = e3[str_off + 8: str_off + 8 + 12 * nstr]
    data = bytes(e3[str_off + 8 + 12 * nstr: str_off + slen])
    names = {}
    for i in range(nstr):
        roff, crc, ln = struct.unpack_from('<3I', recs, 12 * i)
        names.setdefault(data[roff:roff + ln].decode('latin1'), i)
    if new_name in names:
        raise SystemExit(f'a string {new_name!r} already exists: pick another internal name')
    added = []

    def data_str(i):
        roff, _, ln = struct.unpack_from('<3I', recs, 12 * i)
        return data[roff:roff + ln].decode('latin1')

    def string(sv):
        nonlocal data
        if sv in names:
            return names[sv]
        raw = sv.encode('latin1')
        added.append(struct.pack('<3I', len(data), zlib.crc32(raw) & 0xffffffff, len(raw)))
        data += raw + b'\x00'
        names[sv] = nstr + len(added) - 1
        return names[sv]

    def extract_model_tail_items(dm):
        m_meta = bytes(e3[dm[1]: dm[1] + 12 * dm[0]])
        m_states = bytes(e3[dm[10]: dm[10] + 20 * dm[6]]) if (dm[6] and dm[10] >= base_end) else None
        p_items = []
        for p_i in range(dm[7]):
            poff = dm[11] + 32 * p_i
            pm_cnt, pm_off, p_name_idx, p_type, p_slot, p_min, p_max, p_def = struct.unpack_from('<5I3f', e3, poff)
            pmeta_b = bytes(e3[pm_off: pm_off + 12 * pm_cnt]) if (pm_cnt and pm_off >= base_end) else None
            p_items.append((pm_cnt, pm_off, p_name_idx, p_type, p_slot, p_min, p_max, p_def, pmeta_b))
        return (dm, m_meta, m_states, p_items)

    # Preserve any already-added models (864..mcnt-1) and slot lists before rebuilding the tail at 0xcae00+
    base_end = str_off if str_off > 0x200 else _align(len(e3), 0x200)
    extra_models = [extract_model_tail_items(list(struct.unpack_from('<14I', e3, mtab_off + 56 * m_i)))
                    for m_i in range(864, mcnt)]

    i_name = string(new_name)
    i_disp = string(display_name)
    i_key = names['displayName']

    new_id = mcnt
    d = list(struct.unpack_from('<14I', e3, src['off']))
    meta = bytearray()
    for k in range(d[0]):
        ks, kt, kv = struct.unpack_from('<3I', e3, d[1] + 12 * k)
        if ks == i_key:
            assert kt == 7, 'displayName is not a string record'
            kv = i_disp
        if ks < nstr and data_str(ks) in drop_meta:
            continue
        meta += struct.pack('<3I', ks, kt, kv)
    d[0] = len(meta) // 12

    # one state per parameter map input node (nam_host_blob: node k for nam[k])
    m_states = b''.join(struct.pack('<5I', 0, 0x80b98, string(p['state']), p['type'], k)
                        for k, p in enumerate(nam))
    d[6] = len(nam)
    p_items = []
    for p in nam:
        pmeta_b = b''.join(struct.pack('<3I', string(k), t, string(v) if t == 7 else v) for k, t, v in p['meta'])
        _, _, _, ty, sl, mn, mx, df = p['raw']
        p_items.append((len(p['meta']), 0, string(p['name']), ty, sl, mn, mx, df, pmeta_b))
    p_items = [(c, o, ni, t, sl, *struct.unpack('<3f', struct.pack('<3I', mn, mx, df)), mb)
               for c, o, ni, t, sl, mn, mx, df, mb in p_items]
    d[7] = len(nam)

    d[2] = i_name
    d[3] = new_id
    d[13] = blob_index
    extra_models.append((d, bytes(meta), m_states, p_items))

    n_new = nstr + len(added)
    section = struct.pack('<2I', n_new, 8 + 12 * n_new + len(data)) + bytes(recs) + b''.join(added) + data

    saved_slots = []
    for k in range(gcnt):
        rec = gtab_off + 32 * k
        lc, lo = struct.unpack_from('<2I', e3, rec + 20)
        lst = list(struct.unpack_from(f'<{lc}I', e3, lo)) if lc else []
        saved_slots.append((k, lc, lo, lst))

    new_str_off = base_end
    new_mtab = _align(new_str_off + len(section), 0x200)
    cur_off = new_mtab + 56 * (mcnt + 1)
    tail_blobs = bytearray()
    desc_tail = bytearray()
    for dm, m_meta, m_states, p_items in extra_models:
        dm[1] = cur_off + len(tail_blobs)
        tail_blobs += m_meta
        tail_blobs += bytes(_align(len(tail_blobs), 4) - len(tail_blobs))
        if m_states is not None:
            dm[10] = cur_off + len(tail_blobs)
            tail_blobs += m_states
            tail_blobs += bytes(_align(len(tail_blobs), 4) - len(tail_blobs))
        if p_items:
            resolved_p = []
            for pm_cnt, pm_off, p_name_idx, p_type, p_slot, p_min, p_max, p_def, pmeta_b in p_items:
                if pmeta_b is not None:
                    pm_off = cur_off + len(tail_blobs)
                    tail_blobs += pmeta_b
                    tail_blobs += bytes(_align(len(tail_blobs), 4) - len(tail_blobs))
                resolved_p.append(struct.pack('<5I3f', pm_cnt, pm_off, p_name_idx, p_type, p_slot, p_min, p_max, p_def))
            dm[11] = cur_off + len(tail_blobs)
            tail_blobs += b''.join(resolved_p)
            tail_blobs += bytes(_align(len(tail_blobs), 4) - len(tail_blobs))
        desc_tail += struct.pack('<14I', *dm)

    table = bytes(e3[mtab_off: mtab_off + 56 * 864]) + bytes(desc_tail)
    out = bytearray(e3[:base_end])
    if len(out) < base_end:
        out += bytes(base_end - len(out))
    out += section
    out += bytes(new_mtab - len(out)) + table + tail_blobs
    out += bytes(_align(len(out), 4) - len(out))

    slots = []
    for k, lc, lo, lst in saved_slots:
        rec = gtab_off + 32 * k
        if src['model_id'] in lst:
            lst = lst + [new_id]
            slots.append(k)
        if src['model_id'] in lst or lo >= base_end:
            struct.pack_into('<2I', out, rec + 20, len(lst), len(out))
            out += struct.pack(f'<{len(lst)}I', *lst)
    h[2], h[3], h[5], h[6], h[7] = len(out), new_str_off, len(section), new_mtab, mcnt + 1
    h[4] = zlib.crc32(out[new_str_off:new_str_off + len(section)]) & 0xffffffff
    struct.pack_into('<10I', out, 0, *h)
    if len(out) > E3_MAX:
        raise SystemExit(f'Entry 3 would be {len(out):#x} bytes; its partition holds {E3_MAX:#x}')
    return bytes(out), new_id, slots


def fx_source_check(e0, src, category, width):
    """Refuse an effect's metadata model `src` (parse_entry3_full) unless it is a plain
    effect of browser category `category` and port width `width`: Entry 3 meta category,
    Table 2 kind byte (0 mono, 1 stereo), and exactly one browser list, (category, width - 1),
    as a stand-alone item (no companion cab). Returns its browser btype (the preset's block
    kind: 1 for most effects, 8 for delays and reverbs)."""
    if category not in FX_CATEGORIES:
        raise SystemExit(f'category {category} is not an effect category ({FX_CATEGORIES})')
    want = FX_CATEGORIES[category]
    if src['meta'].get('category') != want:
        raise SystemExit(f"{src['name']} is in category {src['meta'].get('category')!r}, not {want!r}")
    segs = _parse_e0_segments(e0)
    A = e0_device(segs)
    rd = lambda va, n: e0[_e0_vaddr_to_foff(segs, va, n): _e0_vaddr_to_foff(segs, va, n) + n]
    vu32 = lambda va: struct.unpack('<I', rd(va, 4))[0]
    ni = src['words'][2]
    t2, (_, n2) = vu32(A.TAB2_BASE_PTR), _decode_thumb_movw(rd(A.TAB2_CNT_INSN, 4))
    row = next(rd(t2 + 44 * i, 44) for i in range(n2) if vu32(t2 + 44 * i) == ni)
    if row[22] != width - 1:
        raise SystemExit(f"{src['name']} is {'stereo' if row[22] else 'mono'} (Table 2), the host has {width} channel(s)")
    found = []
    for idx in range(E0_BLIST_SLOTS):
        lp, lc = vu32(A.BLIST_PTR_TAB + 4 * idx), vu32(A.BLIST_CNT_TAB + 4 * idx)
        for k in range(lc if lp else 0):
            bt, mi, ci = struct.unpack('<IIi', rd(lp + 48 * k, 12))
            if mi == ni:
                found.append((idx // 4, idx % 4, bt, ci))
    if len(found) != 1 or found[0][:2] != (category, width - 1) or found[0][3] != -1:
        raise SystemExit(f"{src['name']} is in browser lists {found}; an effect's source must be in "
                         f"({category}, {width - 1}) only, without a cab")
    return found[0][2]


def add_model(l6ia_bytes, clone, name, display_name, folder=None, short_name=None, preset_id=None,
              dsp_cost=None, params=None, prim_id=0x9c75, instance=None, host=None, category=12, log=print):
    """Add a model on primitive prim_id with the parameters `params` (NAM_PARAMS's form;
    default NAM_PARAMS), in Entries 0, 2, 3 and 4. Returns (new l6ia bytes, info dict).

    An amp (host None): a copy of `clone`'s composite (HD2_AmpLine6Clarity's) whose amp stage
    is the primitive; `folder` is a folder under Amp.
    An effect (host = a model on an FX_HOST_COMPOSITES composite): a copy of the host's
    composite whose one member is the primitive, with `clone`'s Entry 0 and Entry 3 records
    (a stock effect of browser `category`: fx_source_check); `folder` is a folder under that
    category, or None for the source's own Mono/Stereo list."""
    args = types.SimpleNamespace(clone=clone, name=name, display_name=display_name, folder=folder,
                                 short_name=short_name, preset_id=preset_id, dsp_cost=dsp_cost)
    fx = host is not None
    e0 = get_entry_swapped(l6ia_bytes, 0)
    e3 = get_entry_swapped(l6ia_bytes, 3)
    info = parse_entry3_full(e3)
    src = find_model(info, args.clone)
    src_name_idx = src['words'][2]

    nam = nam_params(e3, info, params)
    if len({p['name'] for p in nam}) != len(nam):
        raise SystemExit('two parameters have the same source name: a model\'s parameter names must differ')
    e4 = get_entry_swapped(l6ia_bytes, 4)
    if fx:
        hm = find_model(info, host)
        w4 = struct.unpack('<%dI' % (len(e4) // 4), e4)
        width = FX_HOST_COMPOSITES.get(entry4_blob.top_type(entry4_blob.blob(w4, hm['blob_index'])))
        if width is None:
            raise SystemExit(f"{host} is no effect host (a model on {', '.join(map(hex, FX_HOST_COMPOSITES))})")
        btype = fx_source_check(e0, src, category, width)
        new_e4, blob, new_comp_id = add_model_entry4(e4, hm['blob_index'], nam, prim_id, instance, fx=True)
    else:
        new_e4, blob, new_comp_id = add_model_entry4(e4, src['blob_index'], nam, prim_id, instance)
    replaced = {4: new_e4}
    log(f"[+] Entry 4: {'effect' if fx else 'NAM'} host blob {blob} on composite {new_comp_id:#x} "
          f"(a copy of {host if fx else src['name']}'s); {len(e4):#x} -> {len(new_e4):#x} bytes")
    entries = l6ia.parse(l6ia_bytes)                # Blob 0 grew: the SHARC's buffer must grow with it
    e2_raw = l6ia_bytes[entries[2]['payload_off']: entries[2]['payload_off'] + entries[2]['payload_len']]
    e2_exp_raw, e2_changed = expand_sharc_blob0_buffer(e2_raw)
    replaced[2] = l6ia.swap32(e2_exp_raw)
    if e2_changed:
        log(f"[+] Entry 2: SHARC Blob 0 buffer 0x77aac -> {SHARC_BLOB0_MAX_WORDS:#x} words, "
              f"Heap 6 moved to {HEAP6_MOVED[0]:#x}..{HEAP6_MOVED[1]:#x}")

    new_e3, new_id, slots = add_model_entry3(e3, src, args.name, args.display_name, blob, nam,
                                             drop_meta=FX_MODEL_META_DROP if fx else ())
    replaced[3] = new_e3
    orphans = pmap_slots_without_param(replaced.get(4, None) or get_entry_swapped(l6ia_bytes, 4), blob,
                                       parse_entry3_full(new_e3)['models'][new_id]['params'])
    if orphans:
        raise SystemExit(f'blob {blob} maps slots {orphans} that the new model has no parameter for '
                         f'(no stock model does that; the unit then shows the wrong model name)')

    # Check Entry 3 by parsing the result the way inspect does.
    chk = parse_entry3_full(new_e3)
    m = chk['models'][new_id]
    new_name_idx = m['words'][2]
    assert (m['name'], m['displayName'], m['model_id'], m['blob_index']) == (args.name, args.display_name, new_id, blob)
    assert [(p['name'], p['slot'], p['type']) for p in m['params']] == [(p['name'], p['slot'], p['type']) for p in nam]
    assert [struct.unpack_from('<5I3I', new_e3, p['off'])[3:] for p in m['params']] == [tuple(p['raw'][3:]) for p in nam]
    assert [list(p['meta'].items()) for p in m['params']] == \
           [[(k, v) for k, _, v in p['meta']] for p in nam]
    if fx:
        assert not set(m['meta']) & set(FX_MODEL_META_DROP), m['meta']
        assert all(not set(p['meta']) & set(PARAM_META_DROP) for p in m['params'])
    assert all(a['name'] == b['name'] and a['displayName'] == b['displayName'] and a['words'][1:] == b['words'][1:]
               for a, b in zip(info['models'][:864], chk['models'][:864])), 'a stock model changed'
    assert all((a['name'], a['displayName'], a['model_id'], a['blob_index'],
                [(p['name'], p['slot'], p['min'], p['max'], p['default']) for p in a['params']]) ==
               (b['name'], b['displayName'], b['model_id'], b['blob_index'],
                [(p['name'], p['slot'], p['min'], p['max'], p['default']) for p in b['params']])
               for a, b in zip(info['models'][864:], chk['models'][864:-1])), 'an existing added model changed'
    for k in slots:
        lc, lo = struct.unpack_from('<2I', new_e3, chk['header'][8] + 32 * k + 20)
        lst = struct.unpack_from(f'<{lc}I', new_e3, lo)
        old_lc, old_lo = struct.unpack_from('<2I', e3, chk['header'][8] + 32 * k + 20)
        assert lst[:-1] == struct.unpack_from(f'<{old_lc}I', e3, old_lo) and lst[-1] == new_id
    blob_note = f"blob {blob}"
    log(f"[+] Entry 3: {args.name} ({args.display_name}) = model {new_id} (str_idx={new_name_idx}), a copy of {src['name']} "
          f"({blob_note}), added to slots {slots}; {len(e3):#x} -> {len(new_e3):#x} bytes")

    new_e0, new_pid, dsp_cost, blist_addrs = add_model_entry0(
        e0, src_name_idx, new_name_idx, args.display_name,
        short_name=args.short_name, preset_id=args.preset_id, dsp_cost=args.dsp_cost,
        n_params=len(nam),
        folder=(category, args.folder) if args.folder else None, fx=fx
    )
    replaced[0] = new_e0

    # Verify Entry 0 tables, pointers, and instruction counts
    segs_chk = _parse_e0_segments(new_e0)
    A = e0_device(segs_chk)
    t1_addr = struct.unpack_from('<I', new_e0, _e0_vaddr_to_foff(segs_chk, A.TAB1_BASE_PTRS[0]))[0]
    _, t1_cnt = _decode_thumb_movw(new_e0[_e0_vaddr_to_foff(segs_chk, A.TAB1_CNT_INSN):][:4])
    last_t1 = struct.unpack_from('<IHHI', new_e0, _e0_vaddr_to_foff(segs_chk, t1_addr + 12 * (t1_cnt - 1), 12))
    assert last_t1 == (new_name_idx, new_pid, 0, dsp_cost)
    t2_addr = struct.unpack_from('<I', new_e0, _e0_vaddr_to_foff(segs_chk, A.TAB2_BASE_PTR))[0]
    _, t2_cnt = _decode_thumb_movw(new_e0[_e0_vaddr_to_foff(segs_chk, A.TAB2_CNT_INSN):][:4])
    last_t2_idx = struct.unpack_from('<I', new_e0, _e0_vaddr_to_foff(segs_chk, t2_addr + 44 * (t2_cnt - 1), 44))[0]
    assert last_t2_idx == new_name_idx
    menus_str = ', '.join(f'({cat},{sub})->{cnt}' for _, cat, sub, cnt, _ in blist_addrs)
    log(f"[+] Entry 0: preset_id={new_pid} (<= 832), dsp_cost={dsp_cost}, "
          f"Table 1 ({t1_cnt} rows @ {t1_addr:#x}), Table 2 ({t2_cnt} rows @ {t2_addr:#x}), "
          f"UI browser lists [{menus_str}]; {len(e0):#x} -> {len(new_e0):#x} bytes")

    new_l6ia, old_end, new_end = l6ia.rebuild_archive(l6ia_bytes, replaced)
    log(f"[+] L6IA {old_end:#x} -> {new_end:#x} bytes, delta {new_end - old_end:+d} B")
    out = {'model_id': new_id, 'blob': blob, 'composite': new_comp_id, 'preset_id': new_pid,
           'dsp_cost': dsp_cost, 'prim': prim_id, 'params': [p['name'] for p in nam]}
    if fx:
        out.update(category=category, channels=width, source=src['name'], kind=btype)
    return new_l6ia, out


def cmd_add_model(args):
    l6ia_bytes, is_hxf = load_l6ia_from_any(args.input)
    new_l6ia, _ = add_model(l6ia_bytes, args.clone, args.name, args.display_name, folder=args.folder,
                            short_name=args.short_name, preset_id=args.preset_id, dsp_cost=args.dsp_cost)
    donor = args.input if is_hxf else args.donor
    save_l6ia_to_any(new_l6ia, args.output, donor_hxf=donor)
    print(f"[+] Wrote {args.output}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)

    p_ins = sub.add_parser('inspect', help='List the amps, or show one amp across Entry 3 and Entry 4')
    p_ins.add_argument('input', help='Path to .hxf or L6IA')
    p_ins.add_argument('model', nargs='?', help='Model name (e.g. HD2_AmpNAMLite), displayName, or ID')

    p_add = sub.add_parser('add-model', help='Add the NAM host amp to Entry 0, 2, 3 and 4')
    p_add.add_argument('input', help='Input .hxf or L6IA (the stock HX Stomp or HX Stomp XL v3.80.0 firmware)')
    p_add.add_argument('output', help='Output .hxf or L6IA')
    p_add.add_argument('--clone', default='HD2_AmpLine6Clarity',
                       help='Model whose composite and list entries the new amp copies (default HD2_AmpLine6Clarity)')
    p_add.add_argument('--name', required=True, help='New internal name (e.g. HD2_AmpNAMLite)')
    p_add.add_argument('--display-name', required=True, help='Name shown on the unit (e.g. "NAM A2 Lite")')
    p_add.add_argument('--folder', help='list the model in a new folder of this name under Amp '
                       '(e.g. NAM) instead of Amp > Guitar')
    p_add.add_argument('--short-name', help='16-char short display name in Entry 0 Table 2 (defaults to --display-name)')
    p_add.add_argument('--preset-id', type=int, help='Preset model ID <= 832 in Entry 0 Table 1 (default: first free ID, 147)')
    p_add.add_argument('--donor', help='Stock .hxf of the unit, when input is a raw L6IA and output a .hxf')
    p_add.add_argument('--dsp-cost', type=int,
                       help="DSP cost for Entry 0 Table 1 (default: the source's; stock amps 775..3700, "
                            "apparently hundredths of a per cent of the SHARC)")

    p_pat = sub.add_parser('patch', help='Inject the SHARC kernel into Entry 2 and hook primitive 0x9c75 to it')
    p_pat.add_argument('input', help='Input .hxf or L6IA')
    p_pat.add_argument('output', help='Output .hxf or L6IA')
    p_pat.add_argument('--asm', required=True, help='SHARC assembly file (tools/sharc/nam_lite.py -o ...)')
    p_pat.add_argument('--donor', help='Stock .hxf of the unit, when input is a raw L6IA and output a .hxf')

    args = ap.parse_args()
    {'add-model': cmd_add_model, 'inspect': cmd_inspect, 'patch': cmd_patch}[args.cmd](args)


if __name__ == '__main__':
    main()
