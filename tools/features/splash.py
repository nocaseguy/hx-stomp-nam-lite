"""The boot screen: a picture (HX_SPLASH, any picture; HX_SPLASH_FIT fill or fit), the line of text under it (HX_SPLASH_TEXT),
and that line's glyphs drawn without their black boxes. build.py --splash, --splash-fit and --splash-text set these.

The app's boot view draws HXStomp_Splash (320x181) at the top, the loading bar across it at y = 121 and "   Firmware  3.80.0"
next to Icon_Firmware below it. A 320x240 picture goes into the unused Screen_Boot image instead, and the boot view's image name
becomes Screen_Boot. The bootloader's own copy of the stock picture (shown from power-on until the app starts) is not changed.
"""
from features import Input
import image_store
import patch_menu as pm
import patch_splash as ps

FLAG = ('HX_SPLASH', 'HX_SPLASH_TEXT')
INPUTS = (Input('HX_SPLASH', path=True), Input('HX_SPLASH_FIT', choices=('fill', 'fit'), default='fill'))

NAME_SITE = 0x28e24cf4                              # the boot view's image name, read only by the literal at 0x28d92924
TEXT_SITE, TEXT_STOCK = 0x28e24d14, b'   Firmware  \0\0\0' + b'3.80.0\0\0'
VERSION_LITERAL = 0x28d92938                        # the "3.80.0" the boot view appends to the text
RENDER_FN, RENDER_STOCK = 0x28db7aa4, bytes.fromhex('82b02de9f04f')    # the text renderer's sub sp,#8; push.w {r4-r11,lr}
TEXT_BUF = 0x2811ee38                               # the boot view's text buffer: the renderer's r1 for that line only


def transparent_text_cave(at, stock):
    """Sets the renderer's 9th argument (glyph mode, [sp, #0x10] on entry) to 1 for the boot line, then runs the stock renderer."""
    a = pm.Asm(at)
    a.movw_movt(12, TEXT_BUF)
    a.h(0x4561)                         # cmp r1, r12
    a.b16('ne', 'stock')
    a.h(0xf04f, 0x0c01)                 # mov.w r12, #1
    a.h(0xf8cd, 0xc010)                 # str.w r12, [sp, #0x10]
    a.label('stock')
    a.bw(stock)
    return a.bytes()


def picture(p, path, fit):
    """The picture into HXStomp_Splash (320x181) or, at 320x240, into Screen_Boot, which the boot view then draws."""
    w, h, rows = ps.load_picture(path, fit)
    name, _, stock_md5 = ps.FULL if h == ps.FULL[1] else ps.SPLASH
    e7, e8 = p.entry(7), p.entry(8)
    img = image_store.image(e7.data, e8.data, name)
    if (img.width, img.height, img.bpp) != (w, h, 16):
        raise SystemExit(f'splash: {name.decode()} is {img.width}x{img.height}, {img.bpp} bpp; expected {w}x{h}, 16 bpp')
    e8.expect_md5(img.offset, img.length, stock_md5, name.decode())
    e8.put(img.offset, ps.encode(rows), f'the boot picture ({name.decode()})')
    if name == ps.FULL[0]:
        p.expect(NAME_SITE, ps.SPLASH[0].ljust(16, b'\0'), "the boot view's image name")
        p.put(NAME_SITE, ps.FULL[0].ljust(16, b'\0'), "the boot view's image name")


def boot_text(p, text):
    """The bytes the boot line holds for text: ASCII only, as the fonts have nothing else."""
    if not text.isascii() or not text.isprintable():
        raise SystemExit(f'splash: HX_SPLASH_TEXT must be printable ASCII, not {text!r}')
    return text.encode('ascii')


def line(p, text):
    """The boot line's text in place of "   Firmware  " + "3.80.0" (the two strings are adjacent, 24 bytes, each read once)."""
    raw = boot_text(p, text)
    if not raw or len(raw) >= len(TEXT_STOCK):
        raise SystemExit(f'splash: the text must be 1 to {len(TEXT_STOCK) - 1} characters, not {len(raw)}')
    p.expect(TEXT_SITE, TEXT_STOCK, 'the boot text')
    p.expect(VERSION_LITERAL, (TEXT_SITE + 16).to_bytes(4, 'little'), 'the boot text\'s version pointer')
    p.put(TEXT_SITE, raw.ljust(len(TEXT_STOCK), b'\0'), 'the boot text')
    p.put(VERSION_LITERAL, (TEXT_SITE + len(raw)).to_bytes(4, 'little'), 'the boot text\'s version pointer')   # "" appended


def apply(p):
    if p.input('HX_SPLASH'):
        picture(p, p.input('HX_SPLASH'), p.input('HX_SPLASH_FIT'))
    if p.input('HX_SPLASH_TEXT'):
        line(p, p.input('HX_SPLASH_TEXT'))
    hook = p.own_entry(RENDER_FN, RENDER_STOCK, 'the text renderer')
    hook.to(p.add(transparent_text_cave(p.next(), hook.stock)))
