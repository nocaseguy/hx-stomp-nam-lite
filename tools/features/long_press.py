"""Long press: in Stomp mode, holding a stomp footswitch 1..5 for 1 s opens the tuner, presses FS4/FS5 or presses a virtual
footswitch FS6..FS10; a tap still toggles its blocks, on release (src/m4/long_press.s). FS6..FS10 Function give each virtual
footswitch a stock footswitch function; as Stomp it toggles the blocks assigned to MIDI CC 20..24."""
from features import Setting
import patch_menu as pm

FLAG = 'HX_LONG_PRESS'
MENU = 'Footswitches'
VALUES = (b'Off', b'Tuner', b'FS4', b'FS5', b'FS6', b'FS7', b'FS8', b'FS9', b'FS10')
VIRTUAL_CC = 20                     # FS6..FS10 are MIDI CC 20..24 (undefined in the MIDI spec), as Bypass Assign > MIDI In sets them
# FS1..FS5 Hold default to FS6..FS10 (values 4..8): virtual settings read their default until first set.
HOLDS = tuple(Setting(f'fs{n}', f'Function\nFS{n} Hold'.encode(), VALUES, default=n + 3) for n in (1, 2, 3, 4, 5))
# FS3..FS5 Function's values with Tuner for TAP/Tunr, as a hold has no use for a tap; from Stomp on, value v is function v + 1 of the
# stock dispatch 0x28dd14a0. Stomp, the default, toggles CC 20..24.
FUNCTIONS = tuple(Setting(f'fs{n}_function', f'Function\nFS{n}'.encode(),
                          (b'Tuner', f'Stomp {n}'.encode(), b'Bank Up', b'Bank Dn', b'PresetUp', b'PresetDn', b'SnpshtUp', b'SnpshtDn',
                           b'FS Mode>', b'<FS Mode', b'AllBypas', b'TogglEXP'), default=1) for n in (6, 7, 8, 9, 10))
SETTINGS = HOLDS + FUNCTIONS

# The footswitch event handler (event, object): owned, as a held-back press means not running it for that event.
HANDLER, HANDLER_STOCK = 0x28dd1978, bytes.fromhex('2de9 f043')    # push.w {r4-r9,lr}
# Bypass Assign > MIDI In: the first step up from Off is CC 4 (movs r2,#4); it lands on FS6's CC instead, and CC 4..19 stay below it.
MIDI_IN_FIRST, MIDI_IN_FIRST_STOCK = 0x28dbc2b4, bytes.fromhex('0422')
# A CC shows as "CC" then the digits itoa writes; after it, CC 20..24 read FS6..FS10. Bypass Assign's redraw and knob refresh, and
# Controller Assign's CC# (a parameter on CC 20 follows FS6 too). The Command Center's CCs are ones it sends, so they keep their numbers.
ITOA, CC_TEXT_CALLS = 0x28daaf6c, (0x28dbb6b2, 0x28dbbcd6, 0x28d8ff4c)
# A virtual footswitch's function runs in the stock dispatch's own code (src/m4/long_press.s enters it at these addresses), so the
# hooks other features put in it hold: its switch on the function byte, and TogglEXP's body past its press check.
SWITCH, SWITCH_STOCK = 0x28dd14d2, bytes.fromhex('00eb4400 6500 0379 013b 0d2b f4d8 dfe8 13f0 b000 2e00 bb00 3b00 6500 7c00 9300 ed00 0701 2201 3101 4201')
TOGGLE_EXP, TOGGLE_EXP_STOCK = 0x28dd17fc, bytes.fromhex('c5f7 4cf8 0228 40d0')
# Bypass Assign's redraw and knob refresh label the MIDI In knob "MIDI In" just after its text; on FS6..FS10 the label reads FootswIn.
LABEL = 0x28dc63d0
LABEL_CALLS = ((0x28dbb6c2, 'lp_label_redraw'), (0x28dbbce6, 'lp_label_refresh'))


def apply(p):
    hook = p.own_entry(HANDLER, HANDLER_STOCK, 'the footswitch event handler')
    m = p.module('src/m4/long_press.s')
    p.expect(SWITCH, SWITCH_STOCK, 'the footswitch dispatch\'s switch on the function')
    p.expect(TOGGLE_EXP, TOGGLE_EXP_STOCK, 'the footswitch dispatch\'s TogglEXP')
    p.expect(MIDI_IN_FIRST, MIDI_IN_FIRST_STOCK, 'the MIDI In knob\'s first CC')
    p.put(MIDI_IN_FIRST, bytes([VIRTUAL_CC, 0x22]), 'the MIDI In knob\'s first CC')
    for site in CC_TEXT_CALLS:
        p.chain_bl(site, ITOA, after=m['lp_cc_text'])
    for site, handler in LABEL_CALLS:
        p.own_call(site, LABEL, 'the MIDI In knob\'s label', m[handler])
    a = pm.Asm(p.next())
    a.movw_movt(2, hook.stock | 1)
    a.bw(m['lp_event'])
    hook.to(p.add(a.bytes()))
