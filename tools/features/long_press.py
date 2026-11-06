"""Long press: in Stomp mode, holding a stomp footswitch 1..3 for 1 s opens the tuner or presses FS4/FS5; a tap still toggles its
blocks, on release (src/m4/long_press.s)."""
from features import Setting
import patch_menu as pm

FLAG = 'HX_LONG_PRESS'
VALUES = (b'Off', b'Tuner', b'FS4', b'FS5')
SETTINGS = tuple(Setting(f'fs{n}', f'FS{n}\nHold'.encode(), VALUES) for n in (1, 2, 3))

# The footswitch event handler (event, object): owned, as a held-back press means not running it for that event.
HANDLER, HANDLER_STOCK = 0x28dd1978, bytes.fromhex('2de9 f043')    # push.w {r4-r9,lr}
HOME_CTOR_CALL, HOME_CTOR = 0x28d96c44, 0x28dc91d0                  # boot: where the Hold settings' records become ints


def apply(p):
    hook = p.own_entry(HANDLER, HANDLER_STOCK, 'the footswitch event handler')
    m = p.module('src/m4/long_press.s')
    p.chain_bl(HOME_CTOR_CALL, HOME_CTOR, after=m['lp_boot'])
    a = pm.Asm(p.next())
    a.movw_movt(2, hook.stock | 1)
    a.bw(m['lp_event'])
    hook.to(p.add(a.bytes()))
