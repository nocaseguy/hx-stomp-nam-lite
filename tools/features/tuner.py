"""Tuner Activation (Hold or Press) and Lock Tuner Settings (Off or On)."""
from features import Setting
import patch_menu as pm

ORDER = 0
SETTINGS = (
    Setting('activate', b'Activate\nTuner', (b'Hold', b'Press')),
    Setting('lock', b'Settings\nLock Tnr', (b'Off', b'On')),
)

# The tap in the footswitch case for function TAP/Tunr is a tail call; Press mode turns it into a tuner request.
TAP_SITE, TAP_SITE_STOCK, TAP_CORE = 0x28dd1656, bytes.fromhex('caf7 a7bc'), 0x28d9bfa8
GUARD, REQUEST_TUNER = 0x28d96134, 0x28d96588

# The tuner's settings (Output, Refrnc, Type, Trails, Offsets): knob turns are handled at TURN_FN, and a knob press resets the
# item to its default in one of three cases of the event handler. Lock Tuner Settings On skips both; page changes stay.
TURN_FN, TURN_FN_STOCK, TURN_FN_CONT = 0x28d916d4, bytes.fromhex('f8b5 4678'), 0x28d916d8      # push {r3-r7,lr}; ldrb r6,[r0,#1]
RESET_SITES, RESET_STOCK, RESET_RET = (0x28d917fa, 0x28d9183e, 0x28d91854), bytes.fromhex('91f8 7430'), 0x28d9176e   # ldrb.w r3,[r1,#0x74]; pop {r3,r4,r5,pc}


def tap_cave(at, activate_id):
    """In Press mode the tap becomes a tuner request; otherwise the stock tap-tempo core runs."""
    a = pm.Asm(at)
    a.h(0xb510, 0xb082, 0x2000 | activate_id, 0x4669)   # push {r4,lr}; sub sp,#8; Tuner Activation into [sp+4]
    a.bl(pm.GET_VALUE)
    a.h(0x9801, 0xb002, 0x2801)             # ldr r0,[sp,#4]; add sp,#8; cmp r0,#1
    a.b16('ne', 'stock')
    a.h(0x2005)                             # movs r0,#5
    a.bl(GUARD)
    a.h(0x2800)                             # cmp r0,#0
    a.b16('ne', 'done')
    a.bl(REQUEST_TUNER)
    a.label('done')
    a.h(0xbd10)                             # pop {r4,pc}
    a.label('stock')
    a.raw(bytes.fromhex('bde8 1040'))       # pop.w {r4,lr}
    a.bw(TAP_CORE)
    return a.bytes()


def turn_cave(at, lock_id):
    """Knob turns on the tuner's settings: nothing happens while Lock Tuner Settings is On."""
    a = pm.Asm(at)
    a.h(0xb507, 0xb082, 0x2000 | lock_id, 0x4669)       # push {r0-r2,lr}; sub sp,#8; Lock Tuner Settings into [sp+4]
    a.bl(pm.GET_VALUE)
    a.h(0x9b01, 0xb002)                                 # ldr r3,[sp,#4]; add sp,#8
    a.raw(bytes.fromhex('bde8 0740'))                   # pop.w {r0-r2,lr}
    a.h(0x2b01)                                         # cmp r3,#1
    a.b16('eq', 'locked')
    a.raw(TURN_FN_STOCK)
    a.bw(TURN_FN_CONT)
    a.label('locked')
    a.h(0x4770)                                         # bx lr
    return a.bytes()


def reset_cave(at, site, lock_id):
    """A knob press that resets a tuner setting to its default: skipped while Lock Tuner Settings is On."""
    a = pm.Asm(at)
    a.h(0xb082, 0x2000 | lock_id, 0x4669)               # sub sp,#8; Lock Tuner Settings into [sp+4]
    a.bl(pm.GET_VALUE)
    a.h(0x9b01, 0xb002, 0x4621, 0x2b01)                 # ldr r3,[sp,#4]; add sp,#8; mov r1,r4; cmp r3,#1
    a.b16('eq', 'locked')
    a.raw(RESET_STOCK)
    a.bw(site + 4)
    a.label('locked')
    a.bw(RESET_RET)
    return a.bytes()


def apply(p):
    p.expect(TAP_SITE, TAP_SITE_STOCK, 'the tap-tempo call')
    p.expect(TURN_FN, TURN_FN_STOCK, 'the tuner settings knob handler')
    p.expect(RESET_RET, b'\x38\xbd', 'the tuner event handler epilogue')
    for site in RESET_SITES:
        p.expect(site, RESET_STOCK, 'a tuner settings reset case')
    activate, lock = p.id('tuner.activate'), p.id('tuner.lock')
    p.put(TAP_SITE, pm.thumb_bw(TAP_SITE, p.add(tap_cave(p.next(), activate))), 'the tap-tempo call')
    p.put(TURN_FN, pm.thumb_bw(TURN_FN, p.add(turn_cave(p.next(), lock))), 'the tuner settings knob handler')
    for site in RESET_SITES:
        p.put(site, pm.thumb_bw(site, p.add(reset_cave(p.next(), site, lock))), 'a tuner settings reset case')
