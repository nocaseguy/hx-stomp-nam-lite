"""tools/icon_library.py: the PNG it draws an image-store picture as, the groups of images, the tags of the icons CustomOS uses, and
the page made from the stock firmware."""
import re
import struct
import types
import zlib

import pytest

import icon_library as il
import image_store
import patch_menu as pm
from firmware import stock


def unpng(data):
    """(width, height, rows of RGBA tuples) of a PNG icon_library wrote: one IDAT, no filter."""
    w, h = struct.unpack_from('>2I', data, 16)
    at = data.index(b'IDAT')
    raw = zlib.decompress(data[at + 4:at + 4 + struct.unpack_from('>I', data, at - 4)[0]])
    stride = 1 + 4 * w
    return w, h, [[tuple(raw[y * stride + 1 + 4 * x:y * stride + 5 + 4 * x]) for x in range(w)] for y in range(h)]


def test_png_is_upright_with_black_0_transparent():
    red, white = image_store.pixel(255, 0, 0), image_store.pixel(255, 255, 255)
    # 2x3, column by column from the bottom: column 0 is red, white, 0 (top); column 1 is 0, 0, white (top)
    w, h, rows = unpng(il.png(2, 3, [red, white, 0, 0, 0, white]))
    assert (w, h) == (2, 3)
    assert rows == [[(0, 0, 0, 0), (255, 255, 255, 255)],
                    [(255, 255, 255, 255), (0, 0, 0, 0)],
                    [(255, 0, 0, 255), (0, 0, 0, 0)]]


def test_groups_split_the_section_pictures_from_the_other_icons():
    names = ['Icon_InsOuts', 'Icon_InsOutsSel', 'Global_InsOuts', 'Setup_MIDI', 'Icon_Tempo', 'Block_Delay', 'Icon_Amp']
    g = il.groups(names)
    assert g['title'][0] == 'Icon_InsOuts' and len(g['title']) == 6
    assert g['strip'][:2] == ['Global_InsOuts', 'Global_InsOutsSel'] and len(g['strip']) == 12
    assert 'Icon_InsOutsSel' in g['unused'] and 'Setup_MIDI' in g['unused']
    assert g['others'] == ['Icon_Amp', 'Icon_Tempo']


def test_tags_name_the_default_icon_and_each_feature_s():
    bpm = types.ModuleType('features.bpm')
    bpm.TITLE, bpm.ICON = 'BPM Display', 'Icon_Tempo'
    plain = types.ModuleType('features.plain')
    assert il.tags([bpm, plain]) == {'Icon_Displays': ['CustomOS default'], 'Icon_Tempo': ['BPM Display']}


@pytest.mark.firmware
def test_page_draws_every_icon_of_the_stock_firmware():
    out = il.page(stock())
    assert not re.search(r'\{\{\w+\}\}', out)
    shown = re.findall(r'alt="([^"]+)"', out)
    assert len(shown) == len(set(shown)) == 172
    assert {'Icon_Tempo', 'Icon_DualIR', 'Global_DisplaysSel', 'Setup_Audio'} <= set(shown)
    assert out.count('in ICONS</span>') == len(pm.ICONS)
