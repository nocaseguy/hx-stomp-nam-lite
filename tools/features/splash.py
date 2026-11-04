"""The boot screen: a picture (HX_SPLASH, any picture; HX_SPLASH_FIT fill or fit), the line of text under it (HX_SPLASH_TEXT),
and that line's glyphs drawn without their black boxes. build.py --splash, --splash-fit and --splash-text set these.
Emoji in the text become colour glyphs of the line's font (pictures from HX_SPLASH_GLYPHS, build.py --splash-glyph, else
rendered on macOS), and the line is drawn white, the one colour the glyph blitters copy unchanged.

The app's boot view draws HXStomp_Splash (320x181) at the top, the loading bar across it at y = 121 and "   Firmware  3.80.0"
next to Icon_Firmware below it. A 320x240 picture goes into the unused Screen_Boot image instead, and the boot view's image name
becomes Screen_Boot. The bootloader's own copy of the stock picture (shown from power-on until the app starts) is not changed.
"""
import tempfile

from features import Input
import image_store
import patch_menu as pm
import patch_splash as ps
import splash_emoji

FLAG = ('HX_SPLASH', 'HX_SPLASH_TEXT')
INPUTS = (Input('HX_SPLASH', path=True), Input('HX_SPLASH_FIT', choices=('fill', 'fit'), default='fill'),
          Input('HX_SPLASH_GLYPHS', path=True, mapping=True))

NAME_SITE = 0x28e24cf4                              # the boot view's image name, read only by the literal at 0x28d92924
TEXT_SITE, TEXT_STOCK = 0x28e24d14, b'   Firmware  \0\0\0' + b'3.80.0\0\0'
VERSION_LITERAL = 0x28d92938                        # the "3.80.0" the boot view appends to the text
RENDER_FN, RENDER_STOCK = 0x28db7aa4, bytes.fromhex('82b02de9f04f')    # the text renderer's sub sp,#8; push.w {r4-r11,lr}
TEXT_BUF = 0x2811ee38                               # the boot view's text buffer: the renderer's r1 for that line only
TEXT_COLOUR_LITERAL, TEXT_COLOUR = 0x28d92940, 0xb1b1b1     # the boot view's two text widgets' colour
FONT_SITE, FONT_STOCK = 0x28d92836, b'\x01\x21'     # movs r1,#1 before setFont: the line's font is the loader's 2nd
FONT_NAME_LITERAL, FONT_NAME = 0x28db75c4, b'hx21_regularFont'
# Control codes the line can hold: not NUL (the end), \n or \r (line breaks); emoji take them from 0x01 up, other features from 0x1f down
EMOJI_SLOTS = [c for c in range(1, 32) if c not in (0x0a, 0x0d)]


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


def emoji_glyphs(p, emoji):
    """Each emoji as a colour glyph of the line's font, in EMOJI_SLOTS order; the line drawn white. Returns {emoji: slot}."""
    if len(emoji) > len(EMOJI_SLOTS):
        raise SystemExit(f'splash: at most {len(EMOJI_SLOTS)} different emoji')
    p.expect(FONT_SITE, FONT_STOCK, "the boot line's font")
    p.expect(p.u32(FONT_NAME_LITERAL), FONT_NAME + b'\0', "the font loader's 2nd font")
    p.expect(TEXT_COLOUR_LITERAL, TEXT_COLOUR.to_bytes(4, 'little'), "the boot line's colour")
    p.put(TEXT_COLOUR_LITERAL, (0xffffff).to_bytes(4, 'little'), "the boot line's colour (white: colour glyphs drawn as they are)")
    pictures, cell_h = p.input('HX_SPLASH_GLYPHS'), image_store.cell_height(p.entry(7).data, FONT_NAME)
    slots = dict(zip(emoji, EMOJI_SLOTS))
    with tempfile.TemporaryDirectory() as tmp:
        for e, slot in slots.items():
            width, px = splash_emoji.glyph_from_png(pictures.get(e) or splash_emoji.render_emoji(e, tmp), cell_h)
            p.add_glyph(FONT_NAME, slot, width, px, f'the emoji {e}')
    return slots


def boot_text(p, text):
    """The bytes the boot line holds for text: printable ASCII, and each emoji as the control code of its glyph's slot."""
    parts = splash_emoji.clusters(text)
    if not all(not c.isascii() or c.isprintable() for c in parts):
        raise SystemExit(f'splash: HX_SPLASH_TEXT must be printable ASCII and emoji, not {text!r}')
    emoji = list(dict.fromkeys(c for c in parts if not c.isascii()))
    slots = emoji_glyphs(p, emoji) if emoji else {}
    return b''.join(bytes([slots[c]]) if c in slots else c.encode('ascii') for c in parts)


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
