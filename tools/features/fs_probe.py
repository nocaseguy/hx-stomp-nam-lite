"""Footswitch probe: the panel's raw reports and the key events for footswitches 1..5, as hex rows on the Home screen (src/m4/fs_probe.s).
A test build for long-press footswitches, which must know whether a latching footswitch reports its release and repeats while held."""
FLAG = 'HX_FS_PROBE'

RING_FLAG_CALL, FLAG_GET = 0x28d9af12, 0x28dd83c4                  # the ring loop's read of a footswitch's report mode
POST, POST_STOCK = 0x28db8830, bytes.fromhex('f8b5 0446')         # the key event post: push {r3-r7,lr}; mov r4,r0
HOME_PAINT_LIT, HOME_PAINT = 0x28d96e28, 0x28dc8d39


def apply(p):
    m = p.module('src/m4/fs_probe.s')
    p.chain_bl(RING_FLAG_CALL, FLAG_GET, after=m['fs_raw'])
    p.chain_entry(POST, POST_STOCK, before=m['fs_post'])
    p.chain_ptr(HOME_PAINT_LIT, HOME_PAINT, after=m['fs_paint'])
