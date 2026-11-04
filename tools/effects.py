"""NAM A2 Lite for the HX Effects 3.80.0: the ten-knob block with its tone stack, as Distortion > Mono.

Used through tools/patch_amp.py: `effects-eq IN OUT` (everything but the kernel) and `patch`, which
hooks the kernel with this unit's primitive record (kernel_hook). The kernel is
`nam_multi.py --mid-sweep --effects`: the HX Stomp's but for where the User IR store is.

The HX Effects application refuses a model it does not already know, so NAM takes a stock model's
identity in place: Xenomorph Fuzz Mono's name index, Entry 3 model and preset ID (555), the knobs
type for type on its own (as on the HX Stomp, so HX Edit keeps NAM blocks and their values). No
table in the application grows or changes its count, with one exception below.

  Entry 4  a copy of the mono effect host's composite (Volume Pedal's) with the NAM primitive
           (DM 0x303, PM 0x147, SDRAM 0x5000 words: the mono effect slot allows 0x38b/0x14e/0x60400)
  Entry 2  the SHARC's Blob 0 buffer 0x76a2c -> 0x78000 words and Heap 6 moved to free DDR2 (the
           same steps as the HX Stomp's, at this image's word indices)
  Entry 3  NAM's model built as a new model, its descriptor's meta, states, parameters and blob
           copied onto Xenomorph's model; that model listed once, in the mono effect slot list
  Entry 0  Table 1: 555's DSP cost; Table 2: Xenomorph's row as a distortion row of NAM's
           (short name, counts); the browser: Xenomorph replaced in place in Distortion > Mono;
           the IR name title on Model with sibling knob suppression
  Title    this application shows a User IR's name on the IR Select knob's own line ("Model: name")
           in the knob page's pop-up, for blocks of the IR category. Two category loads (where a
           knob is turned, and where the page is drawn) become calls to helpers that also answer
           "IR" for a block with preset ID 555 at knob 6 (Model), and one value load converts the
           float Model to a slot number (outside 1..128: the stock "<EMPTY>"). The helpers (142
           bytes, below as bytes: the in-browser build has no assembler) need room inside the
           application: its zero-initialised memory starts right after its code segment, so
           nothing can be appended. Table 2 (777 rows) is read only by one linear search by name;
           its last 16 rows move over 16 cab rows that no Table 1 row lists (no preset can name
           those models) and its count drops to 761, freeing 704 bytes for the helpers. The
           scribble strips and the one-parameter view show Model as a number.

Ran on an HX Effects (an owner, who also wrote the browser and knob pop-up fixes).
"""
import struct

import kit_patch_amp as kp
import l6ia

STOCK_MD5 = '7c2ebdf1bffb6bcc5f89dda97f91e40c'          # HX_Effects_v3.80.0_0xd97239907.hxf
N_STOCK = 815                                            # models in Entry 3, blobs in Entry 4
DONOR, DONOR_NI, DONOR_ID, DONOR_PID = 'HD2_DistXenomorphFuzzMono', 1516, 167, 555
CLONE = 'HD2_DistMinotaurMono'                           # meta, Table 2 row, browser item
HOST, HOST_COMP = 'HD2_VolPanVolMono', 0x6000dc          # the mono effect host composite
NAME, DISPLAY, FOLDER = 'HD2_DistNAMLite', 'NAM A2 Lite', 'NAM'
DSP_COST = 2275
INSTANCE = {'dm_words': 0x303, 'pm_words': 0x147, 'sdram_words': 0x5000}

# Entry 0 (its code segment at 0x28000000)
SEG_BASE = 0x28000000
TAB1_BASE, TAB1_CNT = 0x28101084, 465
TAB1_BASE_PTRS = (0x28100b1c, 0x28100b58, 0x28100b70, 0x28100c64, 0x28100df0)
TAB2_BASE, TAB2_CNT, TAB2_BASE_PTR, TAB2_CNT_INSN = 0x280bd8fc, 777, 0x280bd8f8, 0x280bd85c
BLIST_PTR_TAB, BLIST_CNT_TAB, BLIST_SLOTS = 0x2810021c, 0x2810030c, 52   # 13 categories x 4 folders
SUBCAT_CNT, SUBCAT_NAMES = 0x281003e4, 0x281004e8
CAT_DIST = 0                                             # Distortion: Mono, Stereo, Legacy

# Entry 2 (word indices in its payload)
BLOB0_SIZE_W, BLOB0_WORDS, BLOB0_MAX = 37370, 0x76a2c, 0x78000
HEAP6_START_W, HEAP6_END_W, HEAP6_CLR_W = 42147, 42152, 42156
HEAP6, HEAP6_MOVED = (0x292e2c, 0x2a8df6), (0x30d100, 0x3230ca)
PRIM, PRIM_DESC, PRIM_TEMPLATE = 0x9c75, 0x200588, 0x822     # the hook copies 0x822's record

# The title: Table 2's last 16 rows over rows 496.. (cabs no Table 1 row lists), count 761, and in
# the freed tail the helpers (assembled at CAVE), each site's 4-byte load becoming a BL to one.
MOVE_FROM, MOVE_TO, MOVE_N = 761, 496, 16
CAVE = TAB2_BASE + 44 * (TAB2_CNT - MOVE_N)
CAVE_CODE = bytes.fromhex(
    '13f8282c0b2a0bd003b4ddf82500062d18bf002040f22b21884208bf0b2203bc704713f8283c0b2b0cd003b4ddf8e50040f22b21'
    '884204d1abf10600022800d80b2303bc704707b4ddf8e90040f22b218842ddf83d0012d1c20d0dd07f3a0ad4172a09dcc0f3160141'
    'f40001c2f1170221fa02f000e00020411e7f2902d8054607bc704707bc4ff00005b5f722ba')
# (site, its stock 4 bytes, the helper's offset in CAVE_CODE): the turned knob's category,
# the drawn knob's category, the drawn knob's value
TITLE_SITES = ((0x2809ee64, '13f8282c', 0x00), (0x2807ac66, '13f8283c', 0x22), (0x2807aca8, 'ddf83150', 0x46))

# The ten knobs, resolved on the HX Stomp from patch_amp.py's EQ_FX_PARAMS (this application
# has no amps to copy them from): slot, pid, source name, type, state, min, max, default, meta
PARAMS = (
    (1, 5, 'Drive', 3, 'DriveState.1', 0x0, 0x3f800000, 0x3f000000, [('displayType', 7, 'knob'), ('displayName', 7, 'Input')]),
    (2, 10, 'Treble', 3, 'TrebleState', 0x0, 0x3f800000, 0x3f000000, [('displayType', 7, 'knob')]),
    (3, 6, 'ChVol', 3, 'ChVolState', 0x0, 0x3f800000, 0x3f000000, [('displayType', 7, 'knob'), ('displayName', 7, 'Output')]),
    (4, 15, 'Clipping', 2, 'ClippingState', 0x0, 0x1, 0x0,
     [('displayType', 7, 'list'), ('0', 7, 'Normal'), ('1', 7, 'Inverted'), ('displayName', 7, 'Polarity'), ('displayNameShort', 7, 'Polarity')]),
    (5, 8, 'Bass', 3, 'BassState', 0x0, 0x3f800000, 0x3f000000, [('displayType', 7, 'knob')]),
    (6, 9, 'Mid', 3, 'MidState', 0x0, 0x3f800000, 0x3f000000, [('displayType', 7, 'knob')]),
    (7, 7, 'Boost', 3, 'BoostState', 0x0, 0x447a0000, 0x3f800000,
     [('displayName', 7, 'Model'), ('displayType', 7, 'dynamicList'), ('displayNameShort', 7, 'Model')]),
    (8, 19, 'Ch1 Mid Freq', 3, 'Ch1 Mid FreqState', 0x43160000, 0x453b8000, 0x44228000,
     [('displayType', 7, 'hz'), ('displayName', 7, 'Mid Freq'), ('displayNameShort', 7, 'MidFreq')]),
    (9, 20, 'WaveShape', 2, 'WaveShapeState', 0x0, 0x2, 0x0,
     [('displayType', 7, 'list'), ('0', 7, '0.7'), ('1', 7, '1.4'), ('2', 7, '2.8'), ('displayName', 7, 'Q'), ('displayNameShort', 7, 'Q')]),
    (10, 11, 'Presence', 3, 'PresenceState', 0x0, 0x3f800000, 0x3f800000,
     [('displayType', 7, 'knob'), ('displayName', 7, 'High Cut'), ('displayNameShort', 7, 'HighCut')]),
)


def is_effects(l6ia_bytes):
    """True for an HX Effects image: its Entry 0 has 4 segments, the third (its code) at 0x28000000
    (the HX Stomp's and XL's have 7, their code segment elsewhere)."""
    segs = _segs(kp.get_entry_swapped(l6ia_bytes, 0))
    return len(segs) == 4 and segs[2][3] == SEG_BASE


def _segs(e0):
    nsegs = struct.unpack_from('<I', e0, 16)[0]
    segs, off = [], 0x34
    for _ in range(nsegs):
        slen, dst, nxt = struct.unpack_from('<3I', e0, off)
        segs.append((off, off + 12, slen, dst, nxt))
        off = nxt
    return segs


def nam_params():
    return [{'slot': s, 'pid': pid, 'name': n, 'type': t, 'op': kp.NAM_INPUT_OP[t], 'state': st,
             'raw': [0, 0, 0, t, s, mn, mx, df], 'meta': meta, 'default_word': df}
            for s, pid, n, t, st, mn, mx, df, meta in PARAMS]


def _with_n_stock(fn):
    """kit_patch_amp's function with the HX Stomp's 864 stock models/blobs replaced by N_STOCK."""
    import inspect
    src = inspect.getsource(fn)
    assert src.count('864') >= 2, fn.__name__
    ns = dict(vars(kp))
    exec(src.replace('864', str(N_STOCK)), ns)
    return ns[fn.__name__]


def entry4(l6ia_bytes, nam):
    e4 = kp.get_entry_swapped(l6ia_bytes, 4)
    w4 = struct.unpack('<%dI' % (len(e4) // 4), e4)
    assert w4[2] == N_STOCK and w4[w4[3]] == BLOB0_WORDS, 'not the stock HX Effects 3.80.0 Entry 4'
    info = kp.parse_entry3_full(kp.get_entry_swapped(l6ia_bytes, 3))
    saved = kp.FX_HOST_COMPOSITES, kp.SHARC_BLOB0_MAX_WORDS
    kp.FX_HOST_COMPOSITES, kp.SHARC_BLOB0_MAX_WORDS = {HOST_COMP: 1}, BLOB0_MAX
    try:
        return _with_n_stock(kp.add_model_entry4)(e4, kp.find_model(info, HOST)['blob_index'], nam, PRIM, INSTANCE, fx=True)
    finally:
        kp.FX_HOST_COMPOSITES, kp.SHARC_BLOB0_MAX_WORDS = saved


def entry2(e2_raw):
    w = list(struct.unpack('<%dI' % (len(e2_raw) // 4), e2_raw))
    assert w[BLOB0_SIZE_W] == BLOB0_WORDS and w[BLOB0_SIZE_W + 1] == 0x19014dfe, 'Blob 0 size load'
    assert (w[HEAP6_START_W], w[HEAP6_END_W]) == HEAP6, 'Heap 6 loads'
    assert (w[HEAP6_CLR_W], w[HEAP6_CLR_W + 1]) == (0x0f040029, 0x2e2c727e), 'Heap 6 clear start'
    w[BLOB0_SIZE_W] = BLOB0_MAX
    w[HEAP6_START_W], w[HEAP6_END_W] = HEAP6_MOVED
    w[HEAP6_CLR_W], w[HEAP6_CLR_W + 1] = 0x0f040000 | HEAP6_MOVED[0] >> 16, (HEAP6_MOVED[0] & 0xffff) << 16 | 0x727e
    return struct.pack('<%dI' % len(w), *w)


def entry3(e3, blob, nam):
    info = kp.parse_entry3_full(e3)
    assert len(info['models']) == N_STOCK
    donor = kp.find_model(info, DONOR)
    assert (donor['model_id'], donor['words'][2]) == (DONOR_ID, DONOR_NI)
    out, new_id, slots = _with_n_stock(kp.add_model_entry3)(e3, kp.find_model(info, CLONE), NAME, DISPLAY, blob, nam,
                                                            drop_meta=kp.FX_MODEL_META_DROP)
    assert new_id == N_STOCK
    out = bytearray(out)
    h = struct.unpack_from('<10I', out, 0)
    mtab, gtab, gcnt = h[6], h[8], h[9]
    d_new = struct.unpack_from('<14I', out, mtab + 56 * new_id)
    d = list(struct.unpack_from('<14I', out, mtab + 56 * DONOR_ID))
    for k in (0, 1, 6, 7, 10, 11, 13):             # meta, states, parameters, blob; name and id stay
        d[k] = d_new[k]
    struct.pack_into('<14I', out, mtab + 56 * DONOR_ID, *d)
    for k in range(gcnt):                           # slot lists: the donor once, where the copy went
        lc, lo = struct.unpack_from('<2I', out, gtab + 32 * k + 20)
        lst = list(struct.unpack_from(f'<{lc}I', out, lo)) if lc else []
        new = [DONOR_ID if m == new_id else m for m in lst if m != DONOR_ID]
        if new != lst:
            struct.pack_into(f'<{len(new)}I', out, lo, *new)
            struct.pack_into('<I', out, gtab + 32 * k + 20, len(new))
    m = kp.parse_entry3_full(bytes(out))['models'][DONOR_ID]
    assert (m['name'], m['displayName'], m['blob_index'], len(m['params'])) == (DONOR, DISPLAY, blob, len(nam))
    return bytes(out)


def _bl(src, dst):
    off = dst - (src + 4)
    s, i1, i2 = (off >> 24) & 1, (off >> 23) & 1, (off >> 22) & 1
    j1, j2 = (~(i1 ^ s)) & 1, (~(i2 ^ s)) & 1
    return struct.pack('<2H', 0xf000 | (s << 10) | ((off >> 12) & 0x3ff), 0xd000 | (j1 << 13) | (j2 << 11) | ((off >> 1) & 0x7ff))


def _movw(rd, imm):
    return struct.pack('<2H', 0xf240 | (((imm >> 11) & 1) << 10) | ((imm >> 12) & 0xf),
                       (((imm >> 8) & 7) << 12) | (rd << 8) | (imm & 0xff))


def entry0(e0, info, nam):
    e0 = bytearray(e0)
    segs = _segs(e0)
    assert segs[2][3] == SEG_BASE, 'not the HX Effects 3.80.0 Entry 0'
    fo = lambda va, n=4: kp._e0_vaddr_to_foff(segs, va, n)
    rd = lambda va, n: bytes(e0[fo(va, n): fo(va, n) + n])
    u32 = lambda va: struct.unpack('<I', rd(va, 4))[0]

    def wr(va, b):
        e0[fo(va, len(b)): fo(va, len(b)) + len(b)] = b

    for p in TAB1_BASE_PTRS:
        assert u32(p) == TAB1_BASE, f'Table 1 pointer at {p:#x}'
    assert u32(TAB2_BASE_PTR) == TAB2_BASE
    # Table 1: 555's cost
    t1 = [struct.unpack('<IHHI', rd(TAB1_BASE + 12 * i, 12)) for i in range(TAB1_CNT)]
    i = next(i for i, r in enumerate(t1) if r[0] == DONOR_NI)
    assert t1[i][1] == DONOR_PID
    wr(TAB1_BASE + 12 * i, struct.pack('<IHHI', DONOR_NI, DONOR_PID, 0, DSP_COST))
    # Table 2: the clone's row (a mono distortion) as NAM's
    src_ni = kp.find_model(info, CLONE)['words'][2]
    rows = {struct.unpack('<I', rd(TAB2_BASE + 44 * k, 4))[0]: k for k in range(TAB2_CNT)}
    row = bytearray(rd(TAB2_BASE + 44 * rows[src_ni], 44))
    struct.pack_into('<I', row, 0, DONOR_NI)
    row[4:20] = DISPLAY.encode('latin1')[:16].ljust(16, b'\0')
    struct.pack_into('<3I', row, 24, len(nam), len(nam), len(nam))
    struct.pack_into('<2I', row, 36, 0, 0)
    wr(TAB2_BASE + 44 * rows[DONOR_NI], bytes(row))
    # the browser: the donor's item out of Distortion > Mono, NAM's (the clone's, renamed) in the freed slot
    lp, lc = u32(BLIST_PTR_TAB + 4 * CAT_DIST), u32(BLIST_CNT_TAB + 4 * CAT_DIST)
    its = [rd(lp + 48 * k, 48) for k in range(lc)]
    names = [struct.unpack_from('<I', it, 4)[0] for it in its]
    assert names.count(DONOR_NI) == 1 and names.count(src_ni) == 1
    item = bytearray(its[names.index(src_ni)])
    btype, _, c_idx, _ = struct.unpack_from('<IIiH', item, 0)
    assert c_idx == -1
    struct.pack_into('<IIiH', item, 0, btype, DONOR_NI, -1, DONOR_PID)
    item[14:40] = DISPLAY.encode('latin1')[:25].ljust(26, b'\0')
    struct.pack_into('<2I', item, 40, 1, 0)
    donor_idx = names.index(DONOR_NI)
    wr(lp + 48 * donor_idx, bytes(item))
    # the title: Table 2's tail moved, its count 761, the helpers in the freed bytes, the sites
    listed = {r[0] for r in t1}
    trows = [rd(TAB2_BASE + 44 * k, 44) for k in range(TAB2_CNT)]
    assert all(struct.unpack_from('<I', r)[0] not in listed for r in trows[MOVE_TO:MOVE_TO + MOVE_N])
    for k in range(MOVE_N):
        wr(TAB2_BASE + 44 * (MOVE_TO + k), trows[MOVE_FROM + k])
    insn = rd(TAB2_CNT_INSN, 4)
    assert insn == _movw(insn[3] & 0xf, TAB2_CNT), 'Table 2 count'
    wr(TAB2_CNT_INSN, _movw(insn[3] & 0xf, TAB2_CNT - MOVE_N))
    wr(CAVE, b'\0' * 44 * MOVE_N)
    wr(CAVE, CAVE_CODE)
    for site, stock, off in TITLE_SITES:
        assert rd(site, 4) == bytes.fromhex(stock), f'title site {site:#x}'
        wr(site, _bl(site, CAVE + off))
    return bytes(l6ia.fix_internal_crcs(bytes(e0)))


def build_base(l6ia_bytes):
    """The stock HX Effects image with NAM A2 Lite in every entry but the kernel (patch_amp.py patch)."""
    assert is_effects(l6ia_bytes), 'not an HX Effects image'
    nam = nam_params()
    e3 = kp.get_entry_swapped(l6ia_bytes, 3)
    info = kp.parse_entry3_full(e3)
    new_e4, blob, comp = entry4(l6ia_bytes, nam)
    print(f'[+] Entry 4: NAM host blob {blob} on composite {comp:#x}')
    new_e3 = entry3(e3, blob, nam)
    print(f'[+] Entry 3: model {DONOR_ID} ({DONOR}) carries {DISPLAY}: {len(nam)} parameters')
    new_e0 = entry0(kp.get_entry_swapped(l6ia_bytes, 0), info, nam)
    print(f'[+] Entry 0: preset ID {DONOR_PID}, DSP cost {DSP_COST}, Distortion > Mono, the IR-name title on Model')
    e = l6ia.parse(l6ia_bytes)[2]
    new_e2 = entry2(l6ia_bytes[e['payload_off']: e['payload_off'] + e['payload_len']])
    print(f'[+] Entry 2: Blob 0 buffer {BLOB0_WORDS:#x} -> {BLOB0_MAX:#x} words, Heap 6 moved')
    out, _, _ = l6ia.rebuild_archive(l6ia_bytes, {0: new_e0, 2: l6ia.swap32(new_e2), 3: new_e3, 4: new_e4})
    return out


def kernel_hook(e2_raw):
    """(the primitive's record address, its first five words): this image's primitive table."""
    w = struct.unpack('<%dI' % (len(e2_raw) // 4), e2_raw)
    i = 384
    n = {5: lambda c: ((c + 1) & ~1) * 3 // 2, 4: lambda c: c, 3: lambda c: (c + 1) // 2, 6: lambda c: c * 2,
         10: lambda c: c, 9: lambda c: c}
    while not (w[i] == 4 and w[i + 2] == 0x200000):
        i += 3 + n.get(w[i], lambda c: 0)(w[i + 1])
    tab = w[i + 3: i + 3 + w[i + 1]]
    recs = {tab[k]: (0x200000 + k, tab[k:k + 8]) for k in range(0, len(tab), 8)}
    assert recs[PRIM][0] == PRIM_DESC
    return PRIM_DESC, [PRIM] + list(recs[PRIM_TEMPLATE][1][1:5])
