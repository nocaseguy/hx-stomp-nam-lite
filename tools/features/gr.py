"""The gain-reduction meter on the Home screen (src/m4/gr_meter.s), set by each compressor block's own Mtr knobs (tools/patch_comp.py).

No Global Settings: the knobs live in the blocks. The DSP side (src/sharc/frame_probe.asm) goes in with them, and NAM keeps two blocks."""
FLAG = 'HX_GR'
ORDER = 90                          # before the breathing line, which reads SHOWN
MODULE = 'src/m4/gr_meter.s'
SHOWN = 20                          # data + 20 in the module: nonzero while the meter shows

RX_CB_LIT, RX_CB = 0x28da6134, 0x10001095                   # the receive callback of the DSP stream (frames of 256 words)
HOME_CTOR_CALL, HOME_CTOR = 0x28d96c44, 0x28dc91d0          # bl to the Home view's constructor at boot
HOME_PAINT_LIT, HOME_PAINT = 0x28d96e28, 0x28dc8d39         # the Home view's paint function, as registered


def apply(p):
    m = p.module(MODULE)
    p.chain_ptr(RX_CB_LIT, RX_CB, before=m['frame'])
    p.chain_bl(HOME_CTOR_CALL, HOME_CTOR, after=m['construct'])
    p.chain_ptr(HOME_PAINT_LIT, HOME_PAINT, before=m['erase'], after=m['draw'])
