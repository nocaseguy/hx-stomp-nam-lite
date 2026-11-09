"""Long press: in Stomp mode, holding a stomp footswitch 1..5 for 1 s opens the tuner, presses FS4/FS5 or toggles a virtual
footswitch FS6..FS10 (the blocks assigned to MIDI CC 20..24); a tap still toggles its blocks, on release (src/m4/long_press.s)."""
from features import Setting
import patch_menu as pm

FLAG = 'HX_LONG_PRESS'
VALUES = (b'Off', b'Tuner', b'FS4', b'FS5', b'FS6', b'FS7', b'FS8', b'FS9', b'FS10')
VIRTUAL_CC = 20                     # FS6..FS10 are MIDI CC 20..24 (undefined in the MIDI spec), as Bypass Assign > MIDI In sets them
# FS1..FS5 Hold default to FS6..FS10 (values 4..8): virtual settings read their default until first set.
SETTINGS = tuple(Setting(f'fs{n}', f'Hold\nFS{n}'.encode(), VALUES, default=n + 3) for n in (1, 2, 3, 4, 5))

# The footswitch event handler (event, object): owned, as a held-back press means not running it for that event.
HANDLER, HANDLER_STOCK = 0x28dd1978, bytes.fromhex('2de9 f043')    # push.w {r4-r9,lr}
# Bypass Assign > MIDI In: the first step up from Off is CC 4 (movs r2,#4); it lands on FS6's CC instead, and CC 4..19 stay below it.
MIDI_IN_FIRST, MIDI_IN_FIRST_STOCK = 0x28dbc2b4, bytes.fromhex('0422')
# A CC shows as "CC" then the digits itoa writes; after it, CC 20..24 read FS6..FS10. Bypass Assign's redraw and knob refresh, and
# Controller Assign's CC# (a parameter on CC 20 follows FS6 too). The Command Center's CCs are ones it sends, so they keep their numbers.
ITOA, CC_TEXT_CALLS = 0x28daaf6c, (0x28dbb6b2, 0x28dbbcd6, 0x28d8ff4c)


def apply(p):
    hook = p.own_entry(HANDLER, HANDLER_STOCK, 'the footswitch event handler')
    m = p.module('src/m4/long_press.s')
    p.expect(MIDI_IN_FIRST, MIDI_IN_FIRST_STOCK, 'the MIDI In knob\'s first CC')
    p.put(MIDI_IN_FIRST, bytes([VIRTUAL_CC, 0x22]), 'the MIDI In knob\'s first CC')
    for site in CC_TEXT_CALLS:
        p.chain_bl(site, ITOA, after=m['lp_cc_text'])
    a = pm.Asm(p.next())
    a.movw_movt(2, hook.stock | 1)
    a.bw(m['lp_event'])
    hook.to(p.add(a.bytes()))
