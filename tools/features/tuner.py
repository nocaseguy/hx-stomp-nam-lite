"""Tuner Activation (Hold or Press) and Lock Tuner Settings (Off or On), on a third page of the tuner's own settings (src/m4/tuner.s)."""
from features import Setting
import patch_menu as pm

FLAG = 'HX_TUNER'
ORDER = 0
MENU = False
SETTINGS = (     # labels and values as src/m4/tuner.s draws them
    Setting('activate', b'Activate', (b'Hold', b'Press')),
    Setting('lock', b'Lock', (b'Off', b'On')),
)

# The tap in the footswitch case for function TAP/Tunr is a tail call; Press mode turns it into a tuner request.
TAP_SITE, TAP_CORE = 0x28dd1656, 0x28d9bfa8
GUARD, REQUEST_TUNER = 0x28d96134, 0x28d96588

# The tuner's settings (Output, Refrnc, Type, Trails, Offsets): knob turns are handled at TURN_FN, and a knob press resets the
# item to its default in one of three cases of the event handler. Lock Tuner Settings On skips both; page changes stay.
TURN_FN, TURN_FN_STOCK, TURN_FN_CONT = 0x28d916d4, bytes.fromhex('f8b5 4678'), 0x28d916d8      # push {r3-r7,lr}; ldrb r6,[r0,#1]
RESET_SITES = {0x28d917fa: 2, 0x28d9183e: 1, 0x28d91854: 0}                       # site: the knob it resets
RESET_STOCK, RESET_RET = bytes.fromhex('91f8 7430'), 0x28d9176e     # ldrb.w r3,[r1,#0x74]; pop {r3,r4,r5,pc}

# The view has four pages of three knobs, the page at [view+0x74]; these settings are a fifth, page 4, its knob 2 empty. Paging
# and the page dots go by each page's place in the order instead, where page 4 is third (SHOWN_AT) and the string pages follow it.
PAGE, PAGES, SHOWN_AT = 4, 5, 2      # third, ahead of the per-string offsets, which few players use, so these are quick to reach
NEXT_PAGE, NEXT_PAGE_STOCK = 0x28d91784, bytes.fromhex('022b')                    # cmp r3,#2: the last page with a next one
PAGE_READ = bytes.fromhex('91f8 7430')                                            # ldrb.w r3,[r1,#0x74]
NEXT_READ, PREV_READ = 0x28d91780, 0x28d917c2                                     # the next- and previous-page cases' reads of it
PAGE_STORE, PAGE_STORE_STOCK = 0x28d917ca, bytes.fromhex('0125 2046')            # movs r5,#1; mov r0,r4: before both cases' store
DOTS_READ, DOTS_READ_STOCK = 0x28dccd52, bytes.fromhex('94f8 7400')              # ldrb.w r0,[r4,#0x74]: the page dots' current one
PAGE_CLAMPS, PAGE_CLAMP_STOCK = (0x28dcca6c, 0x28dccfd4), bytes.fromhex('032b')  # cmp r3,#3: the paint and redraw zero pages above
PAGE_DOTS, PAGE_DOTS_STOCK = 0x28dccd4c, bytes.fromhex('0420')                    # movs r0,#4: the page indicator's count
PAINT = 0x28dcca60                                                                # (view): takes the widget lock itself
PAINT_SWITCH, PAINT_SWITCH_STOCK = 0x28dcca8e, bytes.fromhex('032b 68d8')        # cmp r3,#3; bhi end: the paint's switch on the page
PAINT_TBH, PAINT_END = 0x28dcca92, 0x28dccb64
STEPS = 0x28dfe2d8                                  # (raw knob delta) -> detents, as the stock turn counts them
SETTER, SETTER_CONTEXT = 0x28e1f8f4, 0x28e007ec     # (context, ID, record, how), as the view stores its own settings
SHOW, VALUE_TEXT, POSITION, LABEL = 0x28dc6598, 0x28dc654c, 0x28dc648c, 0x28dc63d0   # (knob, shown / text / 0.0f..1.0f / text)
KNOB_COLOURS = ((0x28dc6454, 0xffffff), (0x28dc651c, 0x6b6b6b), (0x28dc6534, 0x4d4d4d), (0x28dc6504, 0xb1b1b1),
                (0x28dc6568, 0xb1b1b1))           # (knob, colour), as the stock paints a knob that can be turned


def apply(p):
    m = p.module('src/m4/tuner.s')
    p.own_call(TAP_SITE, TAP_CORE, 'the tap-tempo call', m['tuner_tap'])
    p.own_entry(TURN_FN, TURN_FN_STOCK, 'the tuner settings knob handler', m['tuner_turn_hook'])
    p.expect(RESET_RET, b'\x38\xbd', 'the tuner event handler epilogue')
    for site, knob in RESET_SITES.items():
        p.expect(site, RESET_STOCK, 'a tuner settings reset case')
        p.put(site, pm.thumb_bw(site, m[f'tuner_reset{knob}']), 'a tuner settings reset case')
    p.expect(PAINT_SWITCH, PAINT_SWITCH_STOCK, 'the tuner settings\' paint switch')
    p.put(PAINT_SWITCH, pm.thumb_bw(PAINT_SWITCH, m['tuner_switch']), 'the tuner settings\' paint switch')
    for site, stock, handler in ((NEXT_READ, PAGE_READ, 'tuner_next_page'), (PREV_READ, PAGE_READ, 'tuner_prev_page'),
                                 (PAGE_STORE, PAGE_STORE_STOCK, 'tuner_store_page'), (DOTS_READ, DOTS_READ_STOCK, 'tuner_dots')):
        p.expect(site, stock, 'the tuner settings\' page order')
        p.put(site, pm.thumb_bw(site, m[handler]), 'the tuner settings\' page order')
    p.expect(NEXT_PAGE, NEXT_PAGE_STOCK, 'the tuner settings\' next page')
    p.put(NEXT_PAGE, bytes([PAGE - 1, 0x2b]), 'the tuner settings\' next page')
    for site in PAGE_CLAMPS:
        p.expect(site, PAGE_CLAMP_STOCK, 'the tuner settings\' page clamp')
        p.put(site, bytes([PAGE, 0x2b]), 'the tuner settings\' page clamp')
    p.expect(PAGE_DOTS, PAGE_DOTS_STOCK, 'the tuner settings\' page count')
    p.put(PAGE_DOTS, bytes([PAGES, 0x20]), 'the tuner settings\' page count')
