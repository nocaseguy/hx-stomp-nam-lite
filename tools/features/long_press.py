"""Long press: in Stomp mode, holding a stomp footswitch 1..5 for 1 s opens the tuner, presses FS4/FS5 or toggles a virtual
footswitch FS6..FS10 (the blocks assigned to MIDI CC 20..24); a tap still toggles its blocks, on release (src/m4/long_press.s)."""
from features import Setting
import patch_menu as pm

FLAG = 'HX_LONG_PRESS'
VALUES = (b'Off', b'Tuner', b'FS4', b'FS5', b'FS6', b'FS7', b'FS8', b'FS9', b'FS10')
VIRTUAL_CC = 20                     # FS6..FS10 are MIDI CC 20..24 (undefined in the MIDI spec), as Bypass Assign > MIDI In sets them
# FS1..FS5 Hold default to FS6..FS10 (values 4..8), written once on the first boot (src/m4/long_press.s lp_boot).
SETTINGS = tuple(Setting(f'fs{n}', f'FS{n}\nHold'.encode(), VALUES, default=n + 3) for n in (1, 2, 3, 4, 5))

# The footswitch event handler (event, object): owned, as a held-back press means not running it for that event.
HANDLER, HANDLER_STOCK = 0x28dd1978, bytes.fromhex('2de9 f043')    # push.w {r4-r9,lr}
HOME_CTOR_CALL, HOME_CTOR = 0x28d96c44, 0x28dc91d0                  # boot: where the Hold settings' records become ints
# Bypass Assign > MIDI In: the first step up from Off is CC 4 (movs r2,#4); it lands on FS6's CC instead, and CC 4..19 stay below it.
MIDI_IN_FIRST, MIDI_IN_FIRST_STOCK = 0x28dbc2b4, bytes.fromhex('0422')


def apply(p):
    hook = p.own_entry(HANDLER, HANDLER_STOCK, 'the footswitch event handler')
    m = p.module('src/m4/long_press.s')
    p.chain_bl(HOME_CTOR_CALL, HOME_CTOR, after=m['lp_boot'])
    p.expect(MIDI_IN_FIRST, MIDI_IN_FIRST_STOCK, 'the MIDI In knob\'s first CC')
    p.put(MIDI_IN_FIRST, bytes([VIRTUAL_CC, 0x22]), 'the MIDI In knob\'s first CC')
    a = pm.Asm(p.next())
    a.movw_movt(2, hook.stock | 1)
    a.bw(m['lp_event'])
    hook.to(p.add(a.bytes()))
