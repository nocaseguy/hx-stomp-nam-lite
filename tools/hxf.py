#!/usr/bin/env python3
"""hxf.py - round-trip tool for Line 6 HX-series .hxf firmware files.

An .hxf file is an IFF container:

    FORM <size> L6FF
        HEAD <0x34>   version words, uncompressed size @16, MD5 of payload @20
        dinf <0x10>   data-info: {kind, 1, offset, length}   (one per region)
        dinf <0x10>
        data <n>      zlib stream (level 9)  ->  an L6IA image archive

Verified against HX_Stomp_v3.80.0: the decompressed payload's MD5 equals the
value stored in HEAD, and recompressing with zlib level 9 reproduces the data
chunk byte-for-byte, so `unpack` followed by `pack` is a bit-exact round trip.

Usage:
    hxf.py info    <in.hxf>
    hxf.py unpack  <in.hxf> <out.l6ia>        # decompress inner archive
    hxf.py pack    <in.l6ia> <out.hxf> [--donor in.hxf]
                                              # recompress + fix FORM size & MD5
"""
import struct, zlib, hashlib, sys, os

def _chunks(raw):
    assert raw[:4] == b'FORM' and raw[8:12] == b'L6FF', 'not an L6FF/.hxf file'
    pos, out = 12, []
    while pos < len(raw):
        cid = raw[pos:pos+4]
        sz  = struct.unpack('>I', raw[pos+4:pos+8])[0]
        out.append((cid, pos, sz, raw[pos+8:pos+8+sz]))
        pos += 8 + sz + (sz & 1)
    return out

def info(path):
    raw = open(path, 'rb').read()
    print(f"{path}: {len(raw)} bytes")
    for cid, pos, sz, body in _chunks(raw):
        extra = ''
        if cid == b'HEAD':
            usize = struct.unpack('>I', body[16:20])[0]
            extra = f" uncompressed={usize:#x} md5={body[20:36].hex()}"
        elif cid == b'dinf':
            k, one, off, ln = struct.unpack('>IIII', body[:16])
            extra = f" kind={k} off={off:#x} len={ln:#x}"
        elif cid == b'data':
            dec = zlib.decompress(body)
            extra = f" -> {len(dec):#x} bytes, md5={hashlib.md5(dec).hexdigest()}"
        print(f"  {cid.decode()} @{pos:#x} size={sz:#x}{extra}")

def unpack(path, out):
    raw = open(path, 'rb').read()
    data = [b for c, p, s, b in _chunks(raw) if c == b'data'][0]
    dec = zlib.decompress(data)
    open(out, 'wb').write(dec)
    print(f"[+] wrote {len(dec)} bytes to {out} (md5 {hashlib.md5(dec).hexdigest()})")

def pack(l6ia_path, out_path, donor=None):
    payload = open(l6ia_path, 'rb').read()
    comp = zlib.compress(payload, 9)
    md5 = hashlib.md5(payload).digest()
    # Reuse donor's HEAD/dinf metadata, patching size + md5 + dinf offsets if L6IA length changed; else synthesize.
    if donor:
        chunks = _chunks(open(donor, 'rb').read())
        head = bytearray([b for c, p, s, b in chunks if c == b'HEAD'][0])
        struct.pack_into('>I', head, 16, len(payload))   # uncompressed size
        head[20:36] = md5
        raw_dinfs = [bytearray(b) for c, p, s, b in chunks if c == b'dinf']
        if len(raw_dinfs) == 2 and payload[:4] == b'L6IA':
            # dinf[0] is L6IA archive (kind=0, off=0, len=l6ia_end); dinf[1] is P36Updater trailer (kind=5, off=l6ia_end, len=trailer_len)
            _, _, _, old_trailer_len = struct.unpack('>IIII', raw_dinfs[1][:16])
            l6ia_end = len(payload) - old_trailer_len
            # Only offset and length move; kind and the word after it stay the donor's.
            struct.pack_into('>II', raw_dinfs[0], 8, 0, l6ia_end)
            struct.pack_into('>II', raw_dinfs[1], 8, l6ia_end, old_trailer_len)
        dinfs = [bytes(d) for d in raw_dinfs]
    else:
        # HEAD names the product (word 0x1E: 0x0006 Stomp, 0x000b XL), so it
        # must come from the stock file of the unit it is for.
        raise SystemExit("pack needs --donor: the stock .hxf of the same unit")
    body = bytearray(b'L6FF')
    for cid, data in [(b'HEAD', bytes(head)), *[(b'dinf', d) for d in dinfs], (b'data', comp)]:
        body += cid + struct.pack('>I', len(data)) + data
        if len(data) & 1: body += b'\x00'
    out = b'FORM' + struct.pack('>I', len(body)) + bytes(body)
    open(out_path, 'wb').write(out)
    print(f"[+] wrote {out_path}: {len(out)} bytes, payload md5 {md5.hex()}")

if __name__ == '__main__':
    a = sys.argv
    if len(a) < 3: print(__doc__); sys.exit(1)
    if a[1] == 'info':   info(a[2])
    elif a[1] == 'unpack': unpack(a[2], a[3])
    elif a[1] == 'pack':
        donor = a[a.index('--donor')+1] if '--donor' in a else None
        pack(a[2], a[3], donor)
    else: print(__doc__); sys.exit(1)
