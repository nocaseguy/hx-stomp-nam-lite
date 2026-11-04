"""DSP meter: each block in the Edit view shows its share of the DSP in per cent, and the top right corner the blocks' total (DSP Disp)."""
from features import Setting

FLAG = 'HX_DSP_METER'
SETTINGS = (
    Setting('disp', b'DSP\nDisp', (b'Used/All', b'Free', b'Used%')),     # a value shows 8 characters, on one line
)

EDIT_PAINT_LIT, EDIT_PAINT = 0x28d96da0, 0x28dc27f9     # the Edit view top half's paint function (block slots), as registered


def apply(p):
    m = p.module('src/m4/dsp_meter.s')
    p.chain_ptr(EDIT_PAINT_LIT, EDIT_PAINT, after=m['paint'])
