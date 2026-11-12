"""Screen mirror: HX Edit's editor service answers one more command with the frame on the LCD and the UI events posted since the
last frame, so tools/hx_mirror.py can show the screen on a computer and record it with the controls being used
(src/m4/screen_mirror.s). Nothing changes on the HX Stomp itself."""

import usb_commands

FLAG = 'HX_SCREEN_MIRROR'
MENU = False
WEB = False

CMD = usb_commands.by_feature()['screen_mirror']
REGISTER_ALL_CALL, REGISTER_ALL = 0x28d96adc, 0x28e1661c       # the boot's call of the editor's command registrations
POST, POST_STOCK = 0x28db8830, bytes.fromhex('f8b5 0446')       # (event): every UI event to its listeners; push {r3-r7,lr}; mov r4,r0
# The firmware functions src/m4/screen_mirror.s calls, by their first bytes
CALLED = (
    (0x28e165f0, '7b28 0dd8', 'the editor command table setter'),                   # cmp r0, #0x7b; bhi
    (0x28e19204, '0020 7047', 'the no-parameter check'),                            # movs r0, #0; bx lr
    (0x28e157c8, '0228 07d0 054b a3f1 0802', 'the reply writer getter'),            # cmp r0, #2; beq; ...; sub.w r2, r3, #8
    (0x28e157ec, '0228 07d0 054b a3f1 0c02', 'the reply prefix length getter'),     # ...; sub.w r2, r3, #0xc
    (0x28e15810, '0228 07d0 054b a3f1 6402', 'the reply prefix getter'),            # ...; sub.w r2, r3, #0x64
    (0x28e15834, '0228 0c4b 4ff0 0002', 'the reply prefix reset'),
    (0x28e15878, '70b5 82b0 8323', "the reply map's head"),                         # push; sub sp; movs r3, #0x83
    (0x28e24c00, '5ff8 00f0 bd34 0010', 'the lock'),
    (0x28e24bb0, '5ff8 00f0 d134 0010', 'the unlock'),
    (0x28da6458, '0120 fdf7 a7b9', 'the microsecond clock'),                       # movs r0, #1; b.w the timer read
    (0x28e24c58, '5ff8 00f0 3108 0010', 'the task sleep'),                          # ldr.w pc, =0x10000831: the boot ROM's
    (0x28d9f9a0, '034b 1861', "the framebuffer setter's write of the LCD's frame address"),   # ldr r3, =0x40008000; str r0, [r3, #0x10]
    (0x28d9f9b0, '0080 0040', 'the LCD controller'),
)


def apply(p):
    for va, stock, what in CALLED:
        p.expect(va, bytes.fromhex(stock), what)
    m = p.module('src/m4/screen_mirror.s', inc={'usb.inc': usb_commands.inc('screen_mirror')})
    p.chain_bl(REGISTER_ALL_CALL, REGISTER_ALL, after=m['sm_register'])
    p.chain_entry(POST, POST_STOCK, before=m['sm_event'])
