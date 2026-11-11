"""firmware - the stock HX Stomp file for the features' firmware tests: Entry 0 with features built in, and reading its code.

Each helper skips the test when HX_STOMP_HXF is not set; mark the test `firmware` too, so the default run reports it as skipped."""
import functools
import os
import struct

import pytest

import features
import patch_amp as pa
import patch_menu as pm


@functools.lru_cache(maxsize=None)
def _load(path):
    return pa.load_l6ia_from_any(path)[0]


def stock():
    """The stock L6IA."""
    path = os.environ.get('HX_STOMP_HXF')
    if not path:
        pytest.skip('HX_STOMP_HXF is not set')
    return _load(path)


@functools.lru_cache(maxsize=None)
def stock_entry(n):
    """Stock entry n, swapped."""
    return pa.get_entry_swapped(stock(), n)


def stock_e0():
    return stock_entry(0)


def menu_entry0(e0, *args, **kw):
    """patch_menu.menu_entry0 with the stock file's other entries, which a feature category's strip icons need."""
    return pm.menu_entry0(e0, *args, others=stock_entry, **kw)


def reader(e0):
    """read(va, n): the n bytes of Entry 0 e0 at address va."""
    segs = pa._parse_e0_segments(e0)

    def read(va, n):
        o = pa._e0_vaddr_to_foff(segs, va, n)
        return bytes(e0[o:o + n])
    return read


def built(env, mods=None, ids=None):
    """(read, the names of the features built in) of the stock Entry 0 with the features env turns on."""
    new, on = menu_entry0(stock_e0(), mods, env, ids)
    return reader(new), [features.name(m) for m in on]


def branch_target(at, hw):
    """The target of the bl or b.w hw (4 bytes) at at."""
    h1, h2 = struct.unpack('<2H', hw)
    s, j1, j2 = (h1 >> 10) & 1, (h2 >> 13) & 1, (h2 >> 11) & 1
    off = (s << 24) | ((~(j1 ^ s) & 1) << 23) | ((~(j2 ^ s) & 1) << 22) | ((h1 & 0x3ff) << 12) | ((h2 & 0x7ff) << 1)
    return at + 4 + off - ((1 << 25) if s else 0)


def built_e0(env, mods=None, ids=None):
    """The stock Entry 0 with the features env turns on."""
    return menu_entry0(stock_e0(), mods, env, ids)[0]


def assert_virtual(e0, feature, setting):
    """That Entry 0 e0 serves feature's setting as a virtual setting: GET_VALUE is the engine's, whose table holds the setting's ID,
    field, max and default as tools/setting_ids.py VIRTUAL gives them, and whose labels hold its label."""
    import setting_ids
    name = f'{features.name(feature)}.{setting.key}'
    (vid, cid, bit, bits), = [(v, c, b, n) for v, c, b, n, who, _ in setting_ids.VIRTUAL if who == name]
    fn, stock = pm.VIRTUAL_HOOKS['get']
    assert reader(e0)(fn, len(stock)) != stock, 'GET_VALUE goes to the engine'
    assert struct.pack('<HBBBBB', vid, cid, bit, bits, setting.max, setting.default) in e0, f'{name}: no table entry'
    assert setting.label.ljust(pm.VIRTUAL_LABEL_LEN, b'\0') in e0, f'{name}: no label'
