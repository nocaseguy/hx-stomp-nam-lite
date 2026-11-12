"""tools/features/real_names.py: titles that fit and the font draws, opt-in on the web page and off in build.py by default, and the Entry 0 it builds:
every renamed model's short name and browser items, nothing else."""
import struct

import pytest

import features
import m4cache
import patch_amp as pa
from features import real_names as rn
from firmware import built, menu_entry0, reader, stock_e0, stock_entry

MODS = features.load()


def test_titles_fit_the_short_name():
    for new in (*rn.BY_TITLE.values(), *rn.BY_MODEL.values()):
        assert 0 < len(new) <= rn.SHORT, new
        assert all(32 <= ord(c) < 127 for c in new), f'{new!r}: the font has printable ASCII only'


def test_unchanged_titles_are_not_listed():
    assert all(old != new for old, new in rn.BY_TITLE.items())
    assert 'Xenomorph Fuzz' not in rn.BY_TITLE            # NAM A2 Lite takes its place


def test_off_unless_asked_for():
    assert 'HX_REAL_NAMES' not in m4cache.web_flags() and 'HX_REAL_NAMES' in m4cache.web_options()
    assert rn not in features.enabled(MODS, {})
    assert rn in features.enabled(MODS, {'HX_REAL_NAMES': '1'})


def tables(read):
    """{name index: short name}, {name index: [browser item names]} of an Entry 0, and the byte ranges the names take."""
    A = pa.E0_DEVICES[0x28d8fa80]
    rows = struct.unpack('<I', read(A.TAB2_BASE_PTR, 4))[0]
    _, n = pa._decode_thumb_movw(read(A.TAB2_CNT_INSN, 4))
    short, browser, spans = {}, {}, []
    for i in range(n):
        row = read(rows + 44 * i, 44)
        short[struct.unpack_from('<I', row)[0]] = row[4:20].split(b'\0')[0].decode('latin1')
        spans.append((rows + 44 * i + 4, rows + 44 * i + 20))
    for idx in range(pa.E0_BLIST_SLOTS):
        items, count = (struct.unpack('<I', read(t + 4 * idx, 4))[0] for t in (A.BLIST_PTR_TAB, A.BLIST_CNT_TAB))
        for k in range(count if items else 0):
            item = read(items + 48 * k, 48)
            browser.setdefault(struct.unpack_from('<I', item, 4)[0], []).append(item[14:40].split(b'\0')[0].decode('latin1'))
            spans.append((items + 48 * k + 14, items + 48 * k + 40))
    return short, browser, spans


@pytest.mark.firmware
def test_every_listed_title_is_a_stock_one():
    short, browser, _ = tables(reader(stock_e0()))
    names = rn.strings(stock_entry(3))
    assert set(rn.BY_TITLE) <= set(short.values()) | {b for v in browser.values() for b in v}
    assert set(rn.BY_MODEL) <= {names[ni] for ni in short}


@pytest.mark.firmware
def test_builds_the_real_names():
    read, on = built({'HX_REAL_NAMES': '1'})
    assert 'real_names' in on
    stock = reader(stock_e0())
    old, _, _ = tables(stock)
    short, browser, _ = tables(read)
    names = rn.strings(stock_entry(3))
    by_name = {names[ni]: ni for ni in short}
    assert short[by_name['HD2_DistDeezOneModMono']] == 'Boss DS-1 Mod'
    assert browser[by_name['HD2_DistDeezOneModStereo']] == ['Boss DS-1 Mod']
    assert short[by_name['HD2_Cab1x12CaliExt']] == '1x12 Mesa Ext'                # stock titles it "4x12 SoloLead EM"
    for keep in ('HD2_DistXenomorphFuzzMono', 'HD2_SendMono1', 'HD2_ReverbGanymedeMono'):
        assert short[by_name[keep]] == old[by_name[keep]]
    assert browser[by_name['HD2_SendMono1']] == ['Send L']
    renamed = [ni for ni in short if short[ni] != old[ni]]
    assert len(renamed) == sum(rn.real_name(names[ni], old[ni]) != old[ni] for ni in old) > 400
    assert all(all(b == short[ni] for b in browser.get(ni, ())) for ni in renamed)


@pytest.mark.firmware
def test_writes_only_names():
    plain, _ = menu_entry0(stock_e0(), MODS, {})
    named, _ = menu_entry0(stock_e0(), MODS, {'HX_REAL_NAMES': '1'})
    assert len(named) == len(plain)
    segs = pa._parse_e0_segments(plain)
    _, _, spans = tables(reader(plain))
    inside = {pa._e0_vaddr_to_foff(segs, a, b - a) + j for a, b in spans for j in range(b - a)}
    changed = {o for o in range(len(plain)) if named[o] != plain[o]} - set(range(8, 12))     # the image CRC
    assert changed and changed <= inside
