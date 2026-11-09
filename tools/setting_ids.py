#!/usr/bin/env python3
"""setting_ids.py - the Global Settings IDs CustomOS uses, one line per ID, and `free <stock .hxf>` to list candidate spare IDs.

An ID is the setting's place in the firmware's settings store, and the HX Stomp keeps each setting's value under its ID across builds:
so an ID never moves once a build has used it, and an ID that held another setting before may come with that setting's value.
A feature claims an ID by putting its setting's '<feature>.<key>' on the ID's line. Two branches claiming the same ID edit the same
line, so the merge conflicts; tests/test_customos.py fails on a duplicate, on a setting with no ID and on an ID claimed by no setting.

A new setting takes a virtual ID instead (VIRTUAL): an ID in 0xcc..0xf9, which no stock settings function knows, served by
tools/patch_menu.py's engine (src/m4/virtual_settings.s) from a bit field of the record of a dead float ID 105..116 (CONTAINERS),
which the stock Globals file saves. A virtual setting's line names its ID, its container, its first bit and its width; like an ID,
a field never moves once a build has used it, so a removed setting's line stays, with None, to keep its bits.
"""
import struct
import sys

IDS = (   # (ID, the '<feature>.<key>' using it or None, what is known: its stock state, and the settings it held in earlier builds)
    (29, None, 'tuner.activate until it moved to virtual ID 0xcc; stock limits are not the 0..1 enum; GR Size (0..10) and GR Position (0..3) in early GR images'),
    (63, None, 'long_press.fs1 until it moved to virtual ID 0xd2; empty label, no stock read or write found; units hold 100 (its stock limits value), seen on a unit'),
    (74, None, 'long_press.fs4 until it moved to virtual ID 0xd5; empty label, no stock read or write found; units hold 1 (its stock limits value); a value set on it survived a power-cycle and a stock boot, seen on a unit; FS2 Hold (0..3) in long-press image 2fe68426'),
    (78, None, 'long_press.fs2 until it moved to virtual ID 0xd3; empty label, no stock read or write found; units hold 0 (its stock limits value), seen on a unit; stock type-1 (bool) limits: its record keeps type 1, so the menu offers two values until long_press rewrites it as an int at boot'),
    (101, None, 'dsp_meter.disp until it moved to virtual ID 0xd1; empty label, no stock read or write found; units hold 0 (its stock limits value), seen on a unit'),
    (102, None, 'bpm.dot until it moved to virtual ID 0xd0; GR Position in the Own-IDs GR image (0..4); BPM Position (0..6) in early BPM images; '
                     'DSP Disp (0..3) in dsp-meter test images'),
    (104, None, 'tuner.lock until it moved to virtual ID 0xcd; GR Direction in the Edge-meter GR image (0..1)'),
    (105, None, 'avoid for an int setting, a container of VIRTUAL fields: a float (type-3 limits, default 1.0f, which units hold), skipped with the Variax IDs by the bulk loop at 0x28de9e5c, and refused by the store write (-21); given int limits, ID 105 would not change by its knob, seen on a unit'),
    (106, None, 'avoid for an int setting, a container of VIRTUAL fields: a float (type-3 limits, default 1.0f, which units hold), skipped with the Variax IDs by the bulk loop at 0x28de9e5c, and refused by the store write (-21); given int limits, ID 105 would not change by its knob, seen on a unit'),
    (107, None, 'avoid for an int setting, a container of VIRTUAL fields: a float (type-3 limits, default 1.0f, which units hold), skipped with the Variax IDs by the bulk loop at 0x28de9e5c, and refused by the store write (-21); given int limits, ID 105 would not change by its knob, seen on a unit'),
    (108, None, 'avoid for an int setting, a container of VIRTUAL fields: a float (type-3 limits, default 1.0f, which units hold), skipped with the Variax IDs by the bulk loop at 0x28de9e5c, and refused by the store write (-21); given int limits, ID 105 would not change by its knob, seen on a unit'),
    (109, None, 'avoid for an int setting, a container of VIRTUAL fields: a float (type-3 limits, default 1.0f, which units hold), skipped with the Variax IDs by the bulk loop at 0x28de9e5c, and refused by the store write (-21); given int limits, ID 105 would not change by its knob, seen on a unit'),
    (110, None, 'avoid for an int setting, a container of VIRTUAL fields: a float (type-3 limits, default 1.0f, which units hold), skipped with the Variax IDs by the bulk loop at 0x28de9e5c, and refused by the store write (-21); given int limits, ID 105 would not change by its knob, seen on a unit'),
    (111, None, 'avoid for an int setting, a container of VIRTUAL fields: a float (type-3 limits, default 1.0f, which units hold), skipped with the Variax IDs by the bulk loop at 0x28de9e5c, and refused by the store write (-21); given int limits, ID 105 would not change by its knob, seen on a unit'),
    (112, None, 'avoid for an int setting, a container of VIRTUAL fields: a float (type-3 limits, default 1.0f, which units hold), skipped with the Variax IDs by the bulk loop at 0x28de9e5c, and refused by the store write (-21); given int limits, ID 105 would not change by its knob, seen on a unit'),
    (113, None, 'avoid for an int setting, a container of VIRTUAL fields: a float (type-3 limits, default 1.0f, which units hold), skipped with the Variax IDs by the bulk loop at 0x28de9e5c, and refused by the store write (-21); given int limits, ID 105 would not change by its knob, seen on a unit'),
    (114, None, 'avoid for an int setting, a container of VIRTUAL fields: a float (type-3 limits, default 1.0f, which units hold), skipped with the Variax IDs by the bulk loop at 0x28de9e5c, and refused by the store write (-21); given int limits, ID 105 would not change by its knob, seen on a unit'),
    (115, None, 'avoid for an int setting, a container of VIRTUAL fields: a float (type-3 limits, default 1.0f, which units hold), skipped with the Variax IDs by the bulk loop at 0x28de9e5c, and refused by the store write (-21); given int limits, ID 105 would not change by its knob, seen on a unit'),
    (116, None, 'avoid for an int setting, a container of VIRTUAL fields: a float (type-3 limits, default 1.0f, which units hold), skipped with the Variax IDs by the bulk loop at 0x28de9e5c, and refused by the store write (-21); given int limits, ID 105 would not change by its knob, seen on a unit'),
    (120, None, "long_press.fs5 until it moved to virtual ID 0xd6; empty label, no stock read or write found; units hold 1 (its stock limits value), seen on a unit; BPM Beat (0..4) in bpm-display images up to a72c76a, no longer used"),
    (126, None, 'bpm.color until it moved to virtual ID 0xcf; GR Thickness in the Edge-meter and Own-IDs GR images (0..20)'),
    (128, None, 'bpm.font until it moved to virtual ID 0xce; GR Direction in the Own-IDs GR image (0..1); BPM Font in an older order in early BPM images'),
    (132, None, 'long_press.fs3 until it moved to virtual ID 0xd4; empty label, no stock read or write found; units hold 0 (its stock limits value), seen on a unit; stock type-1 (bool) limits, as 78; '
                'BPM Downbeat (0..10) in bpm-display images up to a72c76a'),
)


VIRTUAL_IDS = range(0xcc, 0xfa)     # every stock settings function returns -3 or does nothing for these
CONTAINERS = range(105, 117)        # the main-store records whose bits hold the virtual settings' values

VIRTUAL = (   # (virtual ID, container ID, first bit, bits, the '<feature>.<key>' using it or None, notes)
    # a container per feature, bits 0..23 only; a two-value setting takes 2 bits and a longer one 4, so either can grow
    (0xcc, 105, 0, 2, 'tuner.activate', ''),
    (0xcd, 105, 2, 2, 'tuner.lock', ''),
    (0xce, 106, 0, 4, 'bpm.font', ''),
    (0xcf, 106, 4, 4, 'bpm.color', ''),
    (0xd0, 106, 8, 4, 'bpm.dot', ''),
    (0xd1, 107, 0, 4, 'dsp_meter.disp', ''),
    (0xd2, 108, 0, 4, 'long_press.fs1', ''),
    (0xd3, 108, 4, 4, 'long_press.fs2', ''),
    (0xd4, 108, 8, 4, 'long_press.fs3', ''),
    (0xd5, 108, 12, 4, 'long_press.fs4', ''),
    (0xd6, 108, 16, 4, 'long_press.fs5', ''),
    (0xd7, 109, 0, 4, 'breathing_line.color', ''),
    (0xd8, 109, 4, 4, 'breathing_line.motion', ''),
    (0xd9, 109, 8, 4, 'breathing_line.speed', ''),
)


def by_name():
    """'<feature>.<key>' -> ID, real or virtual."""
    return {**{name: pid for pid, name, _ in IDS if name}, **{name: vid for vid, _, _, _, name, _ in VIRTUAL if name}}


def packing(entries=VIRTUAL):
    """Virtual ID -> (container ID, first bit, bits) of the settings in use."""
    return {vid: (cid, bit, bits) for vid, cid, bit, bits, name, _ in entries if name}


def virtual_problems(entries=VIRTUAL):
    """What is wrong with a VIRTUAL table: an ID out of range or listed twice, a field outside a container or over another."""
    out, used = [], {}
    for vid, cid, bit, bits, name, _ in entries:
        if vid not in VIRTUAL_IDS:
            out.append(f'{vid:#x} is not a virtual ID ({VIRTUAL_IDS.start:#x}..{VIRTUAL_IDS.stop - 1:#x})')
        if cid not in CONTAINERS:
            out.append(f'{vid:#x}: {cid} is not a container ({CONTAINERS.start}..{CONTAINERS.stop - 1})')
        if not (bits >= 1 and bit >= 0 and bit + bits <= 32):
            out.append(f'{vid:#x}: bits {bit}..{bit + bits - 1} are not in a 32-bit record')
        for b in range(bit, bit + bits):
            if (cid, b) in used:
                out.append(f'{vid:#x}: bit {b} of {cid} is also {used[cid, b]:#x}\'s')
                break
            used[cid, b] = vid
    vids = [e[0] for e in entries]
    out += [f'{vid:#x} is listed twice' for vid in sorted(set(vids)) if vids.count(vid) > 1]
    return out


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
