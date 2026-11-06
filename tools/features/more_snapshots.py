"""More snapshots: pressing the lit snapshot footswitch again flips between snapshots 1-3 and 4-6 (src/m4/more_snapshots.s); in
4-6 the snapshot icon at the top right and the footswitch labels show 4, 5 or 6. Snapshots 4-6 live in RAM until the next preset load; a save writes
snapshots 1-3, whichever bank is live."""
import patch_menu as pm

FLAG = 'HX_MORE_SNAPSHOTS'

SELECT = 0x28de2f90                 # (manager, index): recalls a snapshot
# The tail calls of select (b.w) a footswitch press reaches: the footswitch functions' (0x28dd14a0: 14 snapshot k for footswitch k,
# as Snapshot mode sets them [verified on unit], and 7, 8 next and previous) and the snapshot action's (0x28de59a8)
FS_SELECT_CALLS = (0x28dd1640, 0x28de59d8)
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
        what = f"a footswitch's call of select at {site:#x}"
        p.expect(site, pm.thumb_bw(site, SELECT), what)
        p.put(site, pm.thumb_bw(site, m['snaps_select']), what)
    p.chain_entry(PARSE, PARSE_STOCK, before=m['snaps_loaded'])
    for site, stock, handler in FILE_CALLS:
        what = f'the call at {site:#x} of {stock:#x}'
        p.expect(site, pm.bl(site, stock), what)
        p.put(site, pm.bl(site, m[handler]), what)
    for fn, stock in SERIALIZERS:
        p.chain_entry(fn, stock, before=m['snaps_saving'], after=m['snaps_saved'])
    p.chain_ptr(TOP_PAINT_LIT, TOP_PAINT, after=m['snaps_paint'])
    p.chain_ptr(HOME_PAINT_LIT, HOME_PAINT, after=m['snaps_home_paint'])
