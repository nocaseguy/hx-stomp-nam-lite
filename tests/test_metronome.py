"""tools/features/metronome.py and src/m4/metronome.s: the Metronome block's slot category in unicorn, and its block category and
hook in the firmware they build."""
import re
import struct

import pytest

import features
import patch_click
import patch_menu as pm
import setting_ids
from features import metronome as mt
from firmware import branch_target, built

MODS = features.load()
IDS = setting_ids.by_name()
CODE = 0x28e60000
VOLUME_PAN, LOOPER = 0x10, 0x12


class Slot:
    """metronome_slot in unicorn, called as the bl at the site is: the caller's block info at sp+4."""

    def __init__(self, m4emu):
        code, self.sym = m4emu.assemble('src/m4/metronome.s', MODS, IDS)
        self.m = m4emu.M4(code, CODE)
        self.sp = m4emu.STACK_TOP

    def __call__(self, preset_id, category):
        info = bytearray(0x34)
        struct.pack_into('<BI', info, 0, 1, preset_id & 0xffffffff)
        info[0xc] = category
        self.m.write(self.sp + 4, info)
        self.m.call(CODE + self.sym['metronome_slot'])
        return self.m.reg('r2')


@pytest.fixture
def slot(m4emu):
    return Slot(m4emu)


def test_the_metronome_gets_volume_pans_teal_pictures(slot):
    assert slot(patch_click.PRESET_ID, LOOPER) == VOLUME_PAN


@pytest.mark.parametrize('preset_id', (patch_click.PRESET_ID + 0x100, 0x1b5 + 0x10000, 509, 0, -1))
def test_every_other_block_keeps_its_category(slot, preset_id):
    assert slot(preset_id, LOOPER) == LOOPER
    assert slot(preset_id, 5) == 5


def test_its_constants_are_the_click_tools():
    asm = open(pm.ROOT + '/src/m4/metronome.s').read()
    assert int(re.search(r'\.equ PRESET_ID, (\d+)', asm).group(1)) == patch_click.PRESET_ID
    assert mt.NAME == patch_click.DISPLAY.encode() and mt.FLAG == 'HX_CLICK' and not getattr(mt, 'SETTINGS', ())


@pytest.mark.firmware
def test_build_sends_the_slot_category_load_to_the_module(m4emu):
    code, sym = m4emu.assemble('src/m4/metronome.s', MODS, IDS)
    read, on = built({'HX_CLICK': '1'})
    assert 'metronome' in on
    module = branch_target(mt.SLOT_CATEGORY, read(mt.SLOT_CATEGORY, 4)) - sym['metronome_slot']
    assert read(module, len(code)) == code
    assert read(mt.SLOT_CATEGORY + 4, 4) == bytes.fromhex('83f8 3720'), 'the stock strb.w r2, [r3, #0x37] follows'


@pytest.mark.firmware
def test_build_makes_the_unknown_block_category_metronome_with_icon_tempo():
    read, _ = built({'HX_CLICK': '1'})
    rec = read(mt.CATEGORIES + 0x2c * mt.METRONOME, 0x2c)
    assert rec[:0x11].rstrip(b'\0') == rec[0x11:0x1c].rstrip(b'\0') == b'Metronome'
    colour, dim, icon, off = struct.unpack_from('<4I', rec, 0x1c)
    assert (colour, dim, icon) == (0x3cceb5, 0x21665d, pm.ICONS['Icon_Tempo']) and off not in (icon, 0xde)
    assert read(mt.CATEGORIES + 0x2c * 0x18, 0x2c)[:4] == b'None', 'the record before it is stock'


@pytest.mark.firmware
def test_without_the_flag_both_stay_stock():
    read, on = built({})
    assert 'metronome' not in on
    assert read(mt.SLOT_CATEGORY, 4) == mt.SLOT_CATEGORY_STOCK
    assert read(mt.CATEGORIES + 0x2c * mt.METRONOME, 0x2c) == mt.UNKNOWN_STOCK
