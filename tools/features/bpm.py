"""BPM: the tempo as text at the top left of the Home screen, and a beat dot that follows the TAP footswitch's ring (src/m4/bpm.s)."""
from features import Setting
import patch_menu as pm

FLAG = 'HX_BPM'
ORDER = 20
SETTINGS = (
    Setting('font', b'BPM\nFont', (b'41 Lite', b'35 Bold', b'28 Bold', b'28 Lite', b'21 Bold', b'21 Reg')),
    Setting('color', b'BPM\nColor', (b'White', b'Gray', b'Red', b'Orange', b'Yellow', b'Green', b'Cyan', b'Blue', b'Purple')),
    Setting('dot', b'BPM\nDot Pos', (b'Left', b'Right', b'Both')),
)

HOME_CTOR_CALL, HOME_CTOR = 0x28d96c44, 0x28dc91d0                  # bl to the Home view's constructor at boot
HOME_PAINT_LIT, HOME_PAINT = 0x28d96e28, 0x28dc8d39                  # the Home view's paint function, as registered
# The settings store's write (ID, value, how); its only callers are the three setters. A tempo write asks for a repaint.
STORE_WRITE, STORE_WRITE_CALLS = 0x28e1f0d8, (0x28e1f492, 0x28e1f936, 0x28e1fbce)
LED_TICK_CALL, LED_SLEEP = 0x28db7f44, 0x28e24c58                    # the LED task's 1 ms sleep: where the dot follows the TAP ring
# The two reads of Tap Tempo LED (26) that decide whether the stock blinks the tap LED: the dot needs the blink either way.
TAP_LED_ID, TAP_LED_READS = 26, (0x28d9c116, 0x28dd0ae2)
TAP_CORE, TAP_CORE_STOCK = 0x28d9bfa8, bytes.fromhex('10b5 86b0')   # push {r4,lr}; sub sp,#0x18
# The LED send (LED, colour): owned, as the hook rewrites the colour; its prologue loads a literal, so bpm_ledsend runs it itself.
LED_SEND, LED_SEND_STOCK, LED_SEND_LIT, LED_SEND_LIT_VALUE = 0x28d98f74, bytes.fromhex('00b5 234b'), 0x28d99004, 0x281c90a4


def apply(p):
    m = p.module('src/m4/bpm.s')
    p.chain_bl(HOME_CTOR_CALL, HOME_CTOR, after=m['bpm_construct'])
    p.chain_ptr(HOME_PAINT_LIT, HOME_PAINT, before=m['bpm_before'], after=m['bpm_after'])
    for site in STORE_WRITE_CALLS:
        p.chain_bl(site, STORE_WRITE, after=m['bpm_written'])
    p.chain_bl(LED_TICK_CALL, LED_SLEEP, after=m['bpm_tick'])
    for site in TAP_LED_READS:
        p.expect(site - 2, bytes([TAP_LED_ID, 0x20]), 'a read of Tap Tempo LED')
        p.chain_bl(site, pm.GET_VALUE, after=m['bpm_tapled'])
    p.chain_entry(TAP_CORE, TAP_CORE_STOCK, before=m['bpm_tap'])
    if p.u32(LED_SEND_LIT) != LED_SEND_LIT_VALUE:      # own_entry checks only the prologue; bpm_ledsend repeats its literal load
        raise SystemExit('patch-menu: the LED send does not load its stock literal')
    p.own_entry(LED_SEND, LED_SEND_STOCK, 'the LED send', m['bpm_ledsend'])
