"""More snapshots: pressing the lit snapshot footswitch again flips between snapshots 1-3 and 4-6 (src/m4/more_snapshots.s); in
4-6 the snapshot icon at the top right and the footswitch labels show 4, 5 or 6. Once a preset has a bank B, the next and previous snapshot
footswitches and MIDI CC 69 run through all six: next on 3 goes to 4, next on 6 to 1, previous on 1 to 6, previous on 4 to 3.
MIDI CC 69's values 0..2 select snapshots 1..3 and 3..5 snapshots 4..6, from either bank."""

FLAG = 'HX_MORE_SNAPSHOTS'

SELECT = 0x28de2f90                 # (manager, index): recalls a snapshot
# The tail calls of select (b.w) a footswitch press reaches: the footswitch functions' (0x28dd14a0: 14 snapshot k for footswitch k,
# as Snapshot mode sets them [verified on unit], and 7, 8 next and previous) and the snapshot action's (0x28de59a8)
FS_SELECT_CALLS = (0x28dd1640, 0x28de59d8)
# Footswitch next and previous (the dispatch's cases 7 and 8) read the current snapshot at these calls of 0x28de3750, then wrap it in 0..2
NEXT_CUR, PREV_CUR, CUR_GET = 0x28dd1628, 0x28dd16dc, 0x28de3750
# MIDI CC 69 (0x28d9b120): its calls of the manager getter only where 8 (next) wraps 2 to 0 and 9 (previous) 0 to 2, and its select
CC_WRAP_CALLS, MANAGER_GET, CC_SELECT = (0x28d9b676, 0x28d9b6d8), 0x28d960a4, 0x28d9b5de
# CC 69's cmp r1, #2 before its select of the value: #5 sends 3..5 there too, which stock ignores; that path alone calls the manager
# getter at CC_VALUE_CALL, as next and previous within a bank select 0..2 through the same tail call
CC_RANGE, CC_RANGE_STOCK, CC_RANGE_SIX, CC_VALUE_CALL = 0x28d9b5a2, bytes.fromhex('0229'), bytes.fromhex('0529'), 0x28d9b63a
PARSE, PARSE_STOCK = 0x28de42c4, bytes.fromhex('2de9 f04f')     # the preset's snapshots into the manager; push.w {r4-r11,lr}
# The preset serializers: each copies the blocks, with their live values, then calls the snapshot writer 0x28de3c9c; a load takes the
# live values as its current snapshot's. 0x28dea8c4 (push.w {r4-r8,lr}) is the one a save on the unit took [verified on unit],
# 0x28deacf4 (push.w {r4-r11,lr}) the other save path's and HX Edit's (0x28e1c5b2). They are the writer's only callers.
SERIALIZERS = ((0x28dea8c4, bytes.fromhex('2de9 f041')), (0x28deacf4, bytes.fromhex('2de9 f04f')))
# The preset file (0x28df2060): bank B goes after the map as key 0x64, and the map's count, written up front, is rewritten after the
# TOC; the load reads it back with section 10, the bytes from the end of key 10 to the end of the file, which stock parses only
# as far as key 12's names
FILE_CALLS = ((0x28df20f2, 0x28deacf4, 'snaps_file_serialize'), (0x28df210a, 0x28deabdc, 'snaps_file_toc'),
              (0x28deb53c, 0x28def9a8, 'snaps_file_section'))
TOP_PAINT_LIT, TOP_PAINT = 0x28d96d90, 0x28dca359              # the top view's paint (preset number, name, snapshot icon), as registered
HOME_PAINT_LIT, HOME_PAINT = 0x28d96e28, 0x28dc8d39            # the Home view's paint (footswitch labels), as registered


def apply(p):
    m = p.module('src/m4/more_snapshots.s')
    for site in FS_SELECT_CALLS:
        p.own_call(site, SELECT, f"a footswitch's call of select at {site:#x}", m['snaps_select'])
    p.own_call(NEXT_CUR, CUR_GET, "footswitch next's read of the current snapshot", m['snaps_next_cur'])
    p.own_call(PREV_CUR, CUR_GET, "footswitch previous's read of the current snapshot", m['snaps_prev_cur'])
    for site in CC_WRAP_CALLS:
        p.own_call(site, MANAGER_GET, f"MIDI CC 69's call of the manager getter at {site:#x}, where it wraps", m['snaps_cc_wrap'])
    p.own_call(CC_SELECT, SELECT, "MIDI CC 69's call of select", m['snaps_cc_select'])
    p.own_call(CC_VALUE_CALL, MANAGER_GET, "MIDI CC 69's call of the manager getter before its select of the value", m['snaps_cc_value'])
    p.expect(CC_RANGE, CC_RANGE_STOCK, "MIDI CC 69's range of snapshot values")
    p.put(CC_RANGE, CC_RANGE_SIX, "MIDI CC 69's values 3..5, snapshots 4..6")
    p.chain_entry(PARSE, PARSE_STOCK, before=m['snaps_loaded'])
    for site, stock, handler in FILE_CALLS:
        p.own_call(site, stock, f'the call at {site:#x} of {stock:#x}', m[handler])
    for fn, stock in SERIALIZERS:
        p.chain_entry(fn, stock, before=m['snaps_saving'], after=m['snaps_saved'])
    p.chain_ptr(TOP_PAINT_LIT, TOP_PAINT, after=m['snaps_paint'])
    p.chain_ptr(HOME_PAINT_LIT, HOME_PAINT, after=m['snaps_home_paint'])
