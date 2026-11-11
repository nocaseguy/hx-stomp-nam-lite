"""Breathing line: the Home screen's divider animated in Type's pattern, Color's colours and at Speed (src/m4/breathing_line.s)."""
from features import Setting, gr

FLAG = 'HX_BREATHING_LINE'
TITLE = 'Breathing Line'
ICON = 'Icon_DualIR'
SETTINGS = (
    Setting('color', b'Color', (b'White', b'Red', b'Green', b'Blue', b'Fire', b'Ice', b'Sunset', b'Ocean', b'Aurora', b'Neon',
                                       b'Rainbow'), default=10),
    Setting('motion', b'Type', (b'Off', b'Steady', b'Breathe', b'Cylon', b'Comet', b'Heart', b'Sparkle'), default=2),
    Setting('speed', b'Speed', tuple(str(n).encode() for n in range(1, 11)), default=3),
)

HOME_PAINT_LIT, HOME_PAINT = 0x28d96e28, 0x28dc8d39                  # the Home view's paint function, as registered
LED_TICK_CALL, LED_SLEEP = 0x28db7f44, 0x28e24c58                    # the LED task's 1 ms sleep: the animation's clock


def apply(p):
    meter = p.modules.get(gr.MODULE)    # the line holds still while a compressor's gain-reduction meter shows (user decision)
    shown = meter['data'] + gr.SHOWN if meter else 0
    m = p.module('src/m4/breathing_line.s', inc={'gr.inc': f'.equ GR_SHOWN, {shown:#x}\n'})
    p.chain_ptr(HOME_PAINT_LIT, HOME_PAINT, after=m['bl_paint'])
    p.chain_bl(LED_TICK_CALL, LED_SLEEP, after=m['bl_tick'])
