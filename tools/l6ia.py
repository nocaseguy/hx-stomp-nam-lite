#!/usr/bin/env python3
"""Parser / extractor / repacker for the Line 6 L6IA image archive inside HX-series .hxf files.

Layout (all container header fields big-endian 32-bit):

  Root header (0x18 bytes)
    0x00  'L6IA'
    0x04  version (2)
    0x08  1
    0x0c  1
    0x10  0x40
    0x14  entry count (15)

  Entry header (0x24 bytes, starts at 0x18 for Entry 0)
    +0x00 index        entry index (0 .. count-1)
    +0x04 0x03800000   marker
    +0x08 type         1 = SPIFI boot image, 2 = main app, 6 = data
    +0x0c 4
    +0x10 words        in 32-bit words, covers sub-header (0x200) + payload (plen)
    +0x14 h1           Fletcher-32-like sum1 over (sub-header + payload) BE words
    +0x18 h2           Fletcher-32-like sum2 over (sub-header + payload) BE words
    +0x1c 0
    +0x20 0

  Sub-header (0x200 bytes = 1 eMMC sector, written to partition sec_hdr)
    +0x00 0x56112603   sector header magic
    +0x04 1            version / flags
    +0x08 crc32        zlib.crc32 of byte-swapped (little-endian) payload
    +0x0c plen         payload byte length (words * 4 - 0x200)
    +0x10..+0x1ff      zeros

  Payload (plen bytes, starts at entry_off + 0x224 = marker_off + 0x220)
"""
import struct, sys, os, zlib, hashlib
import numpy as np

ROOT = 0x18
EH   = 0x24
SH   = 0x200

def be32(b, o): return struct.unpack_from('>I', b, o)[0]
def le32(b, o): return struct.unpack_from('<I', b, o)[0]

def swap32(b):
    n = len(b) & ~3
    out = bytearray(b)
    out[:n] = np.frombuffer(b[:n], dtype='>u4').astype('<u4').tobytes()
    return bytes(out)

def _npswap(b):
    return swap32(b)

def fletcher_words(buf):
    """Compute (h1, h2) over big-endian 32-bit words in buf (sub-header + payload)."""
    w = np.frombuffer(buf, dtype='>u4').astype(np.uint64)
    n = len(w)
    m = np.uint64(0xffffffff)                  # typed: a plain int fails on 32-bit numpy (Pyodide)
    a = int(w.sum() & m)
    b = int((w * np.arange(n, 0, -1, dtype=np.uint64) & m).sum() & m)
    return a, b

def fix_internal_crcs(swapped_payload):
    """Recompute internal payload CRCs (Entry 0/1 LPC image CRC32, Entry 3 string table CRC32)."""
    buf = bytearray(swapped_payload)
    if len(buf) >= 0x34:
        magic = le32(buf, 0)
        if magic == 0x230b0c5e:
            # Entry 0 / Entry 1 LPC43xx segmented image header
            size = le32(buf, 4)
            icrc = zlib.crc32(buf[0x34:size]) & 0xffffffff
            struct.pack_into('<I', buf, 8, icrc)
        elif magic == 0x4023245e and len(buf) >= 0x200:
            # Entry 3 / Entry 5 DB image: update total size @+0x08 and string section CRC32 @+0x10
            str_off = le32(buf, 0x0c)
            str_len = le32(buf, 0x14)
            if str_off and str_off + str_len <= len(buf):
                struct.pack_into('<I', buf, 0x08, len(buf))
                scrc = zlib.crc32(buf[str_off:str_off + str_len]) & 0xffffffff
                struct.pack_into('<I', buf, 0x10, scrc)
    return bytes(buf)

def parse(data):
    assert data[:4] == b'L6IA', 'not an L6IA archive'
    count = be32(data, 0x14)
    entries = []
    off = ROOT
    for n in range(count):
        idx = be32(data, off)
        if data[off+4:off+8] != b'\x03\x80\x00\x00':
            raise ValueError(f'bad entry marker at {off+4:#x} (entry {n})')
        etype = be32(data, off+8)
        words = be32(data, off+0x10)
        h1, h2 = be32(data, off+0x14), be32(data, off+0x18)
        sub = data[off+EH: off+EH+SH]
        crc_stored = be32(sub, 8)
        plen = be32(sub, 0xc)
        payload_off = off + EH + SH
        payload_len = words*4 - SH
        assert plen == payload_len, f'entry {n}: sub plen {plen:#x} != words*4-SH {payload_len:#x}'
        entries.append(dict(index=idx, off=off, marker_off=off+4, type=etype, words=words,
                            h1=h1, h2=h2, crc32=crc_stored, sub=sub,
                            payload_off=payload_off, payload_len=payload_len))
        off = off + EH + words*4
    return entries

def rebuild_archive(orig_data, replaced_swapped_by_index):
    """Rebuild full L6IA + trailing P36Updater data, replacing entries in replaced_swapped_by_index.

    replaced_swapped_by_index: dict mapping entry index (int) -> little-endian (.sw4.bin) bytes.
    Returns (new_data_bytes, old_l6ia_end, new_l6ia_end).
    """
    entries = parse(orig_data)
    old_l6ia_end = entries[-1]['payload_off'] + entries[-1]['payload_len']
    trailer = orig_data[old_l6ia_end:]

    out = bytearray(orig_data[:ROOT])
    for e in entries:
        idx = e['index']
        if idx in replaced_swapped_by_index:
            sw = fix_internal_crcs(replaced_swapped_by_index[idx])
            if len(sw) % 4 != 0:
                sw += b'\x00' * (4 - (len(sw) % 4))
            plen = len(sw)
            words = (SH + plen) // 4
            crc = zlib.crc32(sw) & 0xffffffff
            raw_payload = swap32(sw)
            sub = bytearray(e['sub'])
            struct.pack_into('>I', sub, 8, crc)
            struct.pack_into('>I', sub, 0xc, plen)
            body = bytes(sub) + raw_payload
            h1, h2 = fletcher_words(body)
            hdr = struct.pack('>9I', idx, 0x03800000, e['type'], 4, words, h1, h2, 0, 0)
            out += hdr + body
        else:
            raw_entry = orig_data[e['off']: e['payload_off'] + e['payload_len']]
            out += raw_entry

    new_l6ia_end = len(out)
    out += trailer
    return bytes(out), old_l6ia_end, new_l6ia_end

def describe(data, e):
    p = data[e['payload_off']: e['payload_off']+e['payload_len']]
    sw = _npswap(p[:len(p)&~3])
    kind = '?'
    if e['type'] == 1: kind = 'boot image (SPIFI XIP, Cortex-M4)'
    elif e['type'] == 2: kind = 'main application (Cortex-M4, SDRAM)'
    elif e['type'] == 6: kind = 'data'
    return p, sw, kind

if __name__ == '__main__':
    path = sys.argv[1]
    outdir = sys.argv[2] if len(sys.argv) > 2 else None
    data = open(path, 'rb').read()
    entries = parse(data)
    print(f"{len(entries)} entries (L6IA ends at {entries[-1]['payload_off']+entries[-1]['payload_len']:#x}, total file {len(data):#x})")
    for e in entries:
        p, sw, kind = describe(data, e)
        subw = [be32(e['sub'], i) for i in range(0, 0x10, 4)]
        print(f"[{e['index']:2d}] off={e['off']:#010x} type={e['type']} payload@{e['payload_off']:#010x} len={e['payload_len']:#x} ({e['payload_len']/1024:.1f} KiB) "
              f"h1={e['h1']:08x} h2={e['h2']:08x} sub={' '.join(f'{x:08x}' for x in subw)} crc32(sw)={zlib.crc32(sw):08x}  {kind}")
        if outdir:
            os.makedirs(outdir, exist_ok=True)
            open(os.path.join(outdir, f"{e['index']:02d}_type{e['type']}.bin"), 'wb').write(p)
            open(os.path.join(outdir, f"{e['index']:02d}_type{e['type']}.sw4.bin"), 'wb').write(sw)
            open(os.path.join(outdir, f"{e['index']:02d}_type{e['type']}.sub"), 'wb').write(e['sub'])

