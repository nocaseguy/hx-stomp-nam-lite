#!/usr/bin/env python3
"""setting_ids.py - the Global Settings IDs CustomOS uses, one line per ID, and `free <stock .hxf>` to list candidate spare IDs.

An ID is the setting's place in the firmware's settings store, and the HX Stomp keeps each setting's value under its ID across builds:
so an ID never moves once a build has used it, and an ID that held another setting before may come with that setting's value.
A feature claims an ID by putting its setting's '<feature>.<key>' on the ID's line. Two branches claiming the same ID edit the same
line, so the merge conflicts; tests/test_customos.py fails on a duplicate, on a setting with no ID and on an ID claimed by no setting.
"""
import sys

IDS = (   # (ID, the '<feature>.<key>' using it or None, what is known: its stock state, and the settings it held in earlier builds)
    (29, 'tuner.activate', 'stock limits are not the 0..1 enum; GR Size (0..10) and GR Position (0..3) in early GR images'),
    (102, None, 'GR Position in the Own-IDs GR image (0..4)'),
    (104, 'tuner.lock', 'GR Direction in the Edge-meter GR image (0..1)'),
    (126, None, 'GR Thickness in the Edge-meter and Own-IDs GR images (0..20)'),
    (128, None, 'GR Direction in the Own-IDs GR image (0..1)'),
)


def by_name():
    """'<feature>.<key>' -> ID."""
    return {name: pid for pid, name, _ in IDS if name}


def free(l6ia_bytes):
    """[(ID, has the stock 0..1 limits)] of empty-label main-store IDs not in IDS: candidates, until no stock reader is found."""
    import patch_amp as pa
    import patch_menu as pm
    e0 = pa.get_entry_swapped(l6ia_bytes, 0)
    segs = pa._parse_e0_segments(e0)

    def read(va, n):
        o = pa._e0_vaddr_to_foff(segs, va, n)
        return bytes(e0[o:o + n])

    used = {pid for pid, _, _ in IDS}
    out = []
    for pid in pm.MAIN_STORE_IDS:
        if pid in used or any(any(read(names + pm.NAME_LEN * pid, pm.NAME_LEN)) for names in (pm.NAMES_LONG, pm.NAMES_SHORT)):
            continue
        tab, entry = pm.limits_entry(pid)
        out.append((pid, tab + 2 * int.from_bytes(read(entry, 2), 'little') == pm.ENUM01_TARGET))
    return out


def main():
    if len(sys.argv) != 3 or sys.argv[1] != 'free':
        sys.exit(__doc__)
    import patch_amp as pa
    data, _ = pa.load_l6ia_from_any(sys.argv[2])
    for pid, enum01 in free(data):
        print(pid, 'stock 0..1 limits' if enum01 else 'other stock limits: may be a hidden stock setting')


if __name__ == '__main__':
    main()
