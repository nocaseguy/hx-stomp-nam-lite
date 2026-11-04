#!/usr/bin/env python3
"""setting_ids.py - the Global Settings IDs CustomOS uses, one line per ID, and `free <stock .hxf>` to list candidate spare IDs.

An ID is the setting's place in the firmware's settings store, and the HX Stomp keeps each setting's value under its ID across builds:
so an ID never moves once a build has used it, and an ID that held another setting before may come with that setting's value.
A feature claims an ID by putting its setting's '<feature>.<key>' on the ID's line. Two branches claiming the same ID edit the same
line, so the merge conflicts; tests/test_customos.py fails on a duplicate, on a setting with no ID and on an ID claimed by no setting.
"""
import struct
import sys

IDS = (   # (ID, the '<feature>.<key>' using it or None, what is known: its stock state, and the settings it held in earlier builds)
    (29, 'tuner.activate', 'stock limits are not the 0..1 enum; GR Size (0..10) and GR Position (0..3) in early GR images'),
    (63, None, 'empty label, no stock read or write found; units hold 100 (its stock limits value), seen on a unit'),
    (74, None, 'empty label, no stock read or write found; units hold 1 (its stock limits value), seen on a unit'),
    (78, None, 'empty label, no stock read or write found; units hold 0 (its stock limits value), seen on a unit'),
    (101, None, 'empty label, no stock read or write found; units hold 0 (its stock limits value), seen on a unit'),
    (102, None, 'GR Position in the Own-IDs GR image (0..4)'),
    (104, 'tuner.lock', 'GR Direction in the Edge-meter GR image (0..1)'),
    (105, None, 'avoid: type-3 stock limits shared by 105..116 (likely floats), and units hold a value outside 0..254'),
    (106, None, 'avoid: type-3 stock limits shared by 105..116 (likely floats), and units hold a value outside 0..254'),
    (107, None, 'avoid: type-3 stock limits shared by 105..116 (likely floats), and units hold a value outside 0..254'),
    (108, None, 'avoid: type-3 stock limits shared by 105..116 (likely floats), and units hold a value outside 0..254'),
    (109, None, 'avoid: type-3 stock limits shared by 105..116 (likely floats), and units hold a value outside 0..254'),
    (110, None, 'avoid: type-3 stock limits shared by 105..116 (likely floats), and units hold a value outside 0..254'),
    (111, None, 'avoid: type-3 stock limits shared by 105..116 (likely floats), and units hold a value outside 0..254'),
    (112, None, 'avoid: type-3 stock limits shared by 105..116 (likely floats), and units hold a value outside 0..254'),
    (113, None, 'avoid: type-3 stock limits shared by 105..116 (likely floats), and units hold a value outside 0..254'),
    (114, None, 'avoid: type-3 stock limits shared by 105..116 (likely floats), and units hold a value outside 0..254'),
    (115, None, 'avoid: type-3 stock limits shared by 105..116 (likely floats), and units hold a value outside 0..254'),
    (116, None, 'avoid: type-3 stock limits shared by 105..116 (likely floats), and units hold a value outside 0..254'),
    (120, None, "empty label, no stock read or write found; units hold 1 (its stock limits value), seen on a unit; bpm-display's BPM Beat uses it"),
    (126, None, 'GR Thickness in the Edge-meter and Own-IDs GR images (0..20)'),
    (128, None, 'GR Direction in the Own-IDs GR image (0..1)'),
    (132, None, 'empty label, no stock read or write found; units hold 0 (its stock limits value), seen on a unit'),
)


def by_name():
    """'<feature>.<key>' -> ID."""
    return {name: pid for pid, name, _ in IDS if name}


SETTERS = (0x28e1f458, 0x28e1f8f4, 0x28e1fb7c)     # the three functions that call the settings store's write


def bl_targets(hw, base):
    """{halfword index: target} of every BL in the halfwords hw at base."""
    out = {}
    for i in range(len(hw) - 1):
        h1, h2 = hw[i], hw[i + 1]
        if h1 & 0xf800 == 0xf000 and h2 & 0xd000 == 0xd000:
            s = (h1 >> 10) & 1
            off = (s << 24) | ((1 - (((h2 >> 13) & 1) ^ s)) << 23) | ((1 - (((h2 >> 11) & 1) ^ s)) << 22) | \
                ((h1 & 0x3ff) << 12) | ((h2 & 0x7ff) << 1)
            out[i] = base + 2 * i + 4 + off - (s << 25)
    return out


def stock_uses(hw, base, get_value):
    """ID -> Counter of stock 'read's, 'write's and 'loop's (an ID in a register within movs/cmp bounds): computed IDs go unseen."""
    import collections
    uses = collections.defaultdict(collections.Counter)
    for i, t in bl_targets(hw, base).items():
        if t != get_value and t not in SETTERS:
            continue
        kind, r = ('read', 0) if t == get_value else ('write', 1)     # GET_VALUE takes the ID in r0, the setters in r1
        for k in range(1, 6):
            h = hw[i - k]
            if h & 0xff00 == 0x2000 | r << 8:           # movs rR,#id
                uses[h & 0xff][kind] += 1
                break
            if h & 0xffc7 == 0x4600 | r and h & 0x38:   # mov rR,rN: the ID is in rN
                n, near = (h >> 3) & 7, hw[max(0, i - 40):i + 40]
                lows = [x & 0xff for x in near if x & 0xff00 == 0x2000 | n << 8]
                highs = [x & 0xff for x in near if x & 0xff00 == 0x2800 | n << 8]
                for lo in lows:
                    for hi in highs:
                        if lo < hi <= lo + 64:
                            for pid in range(lo, hi + 1):
                                uses[pid]['loop'] += 1
                break
    return uses


def free(l6ia_bytes):
    """[(ID, has the stock 0..1 limits, Counter of stock uses)] of empty-label main-store IDs not in IDS: candidates."""
    import patch_amp as pa
    import patch_menu as pm
    e0 = pa.get_entry_swapped(l6ia_bytes, 0)
    segs = pa._parse_e0_segments(e0)
    _, poff, slen, base, _ = segs[6]
    uses = stock_uses(struct.unpack_from(f'<{slen // 2}H', e0, poff), base, pm.GET_VALUE)

    def read(va, n):
        o = pa._e0_vaddr_to_foff(segs, va, n)
        return bytes(e0[o:o + n])

    used = {pid for pid, _, _ in IDS}
    out = []
    for pid in pm.MAIN_STORE_IDS:
        if pid in used or any(any(read(names + pm.NAME_LEN * pid, pm.NAME_LEN)) for names in (pm.NAMES_LONG, pm.NAMES_SHORT)):
            continue
        tab, entry = pm.limits_entry(pid)
        out.append((pid, tab + 2 * int.from_bytes(read(entry, 2), 'little') == pm.ENUM01_TARGET, uses[pid]))
    return out


def main():
    if len(sys.argv) != 3 or sys.argv[1] != 'free':
        sys.exit(__doc__)
    import patch_amp as pa
    data, _ = pa.load_l6ia_from_any(sys.argv[2])
    for pid, enum01, uses in free(data):
        seen = ', '.join(f'{k} {n}' for k, n in sorted(uses.items())) or 'no stock read or write found'
        print(f'{pid:3}  {"stock 0..1 limits" if enum01 else "other stock limits"}  {seen}')


if __name__ == '__main__':
    main()
