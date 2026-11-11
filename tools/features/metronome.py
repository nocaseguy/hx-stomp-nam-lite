"""Metronome: how the Metronome block (tools/patch_click.py, HX_CLICK=1) looks. In the signal flow it takes the teal pictures of
Volume/Pan, lit when on, dim when off (src/m4/metronome.s), and its block category is Metronome, with Icon_Tempo."""
import struct

import image_store
import patch_menu as pm

FLAG = 'HX_CLICK'

# Looper's slot category (0x12) draws the looper's grey pictures with the looper's on/off, so the Metronome gets Volume/Pan's
SLOT_CATEGORY, SLOT_CATEGORY_STOCK = 0x28dd3042, bytes.fromhex('9df8 1020')    # ldrb.w r2, [sp, #0x10]

# A model without Entry 3 meta 'category' is block category 0x19, Unknown, otherwise only app, harness and mic models
CATEGORIES, METRONOME = 0x28e2815c, 0x19    # 0x2c-byte records {name[0x11], short[0xb], colour, dim colour, icon, icon off}
UNKNOWN_STOCK = bytes.fromhex('556e6b6f776e0000000000000000000000556e6b6f776e00000000008080800080808000de000000de000000')
NAME = b'Metronome'                 # tools/patch_click.py DISPLAY
COLOURS = (0x3cceb5, 0x21665d)      # Volume, Send, Return and FX Loop's
ICON_OFF_DIMMED = 0.39              # Icon_Tempo has no off picture: dimmed as the strip icons are


def apply(p):
    m = p.module('src/m4/metronome.s')
    p.expect(SLOT_CATEGORY, SLOT_CATEGORY_STOCK, "the signal flow's slot category load")
    p.put(SLOT_CATEGORY, pm.bl(SLOT_CATEGORY, m['metronome_slot']), "the signal flow's slot category load")

    e7, e8 = p.entry(7), p.entry(8)
    icon = pm.ICONS['Icon_Tempo']
    im = image_store.image_at(e7.data, e8.data, icon)
    off = p.add_image(icon, im.width, im.height, image_store.scaled(e8.read(im.offset, im.length), ICON_OFF_DIMMED))
    rec = CATEGORIES + 0x2c * METRONOME
    p.expect(rec, UNKNOWN_STOCK, 'the Unknown block category')
    p.put(rec, NAME.ljust(0x11, b'\0') + NAME.ljust(0xb, b'\0') + struct.pack('<4I', *COLOURS, icon, off),
          'the Unknown block category, as Metronome')
