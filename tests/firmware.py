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


def stock_e0():
    return pa.get_entry_swapped(stock(), 0)


def reader(e0):
    """read(va, n): the n bytes of Entry 0 e0 at address va."""
    segs = pa._parse_e0_segments(e0)

    def read(va, n):
        o = pa._e0_vaddr_to_foff(segs, va, n)
        return bytes(e0[o:o + n])
    return read


def built(env, mods=None, ids=None):
    """(read, the names of the features built in) of the stock Entry 0 with the features env turns on."""
    new, on = pm.menu_entry0(stock_e0(), mods, env, ids)
    return reader(new), [features.name(m) for m in on]


def branch_target(at, hw):
    """The target of the bl or b.w hw (4 bytes) at at."""
    h1, h2 = struct.unpack('<2H', hw)
    s, j1, j2 = (h1 >> 10) & 1, (h2 >> 13) & 1, (h2 >> 11) & 1
    off = (s << 24) | ((~(j1 ^ s) & 1) << 23) | ((~(j2 ^ s) & 1) << 22) | ((h1 & 0x3ff) << 12) | ((h2 & 0x7ff) << 1)
    return at + 4 + off - ((1 << 25) if s else 0)
