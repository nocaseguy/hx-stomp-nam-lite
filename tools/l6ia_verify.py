#!/usr/bin/env python3
"""Verify every integrity field inside an L6IA archive (HX .hxf payload)."""
import sys, struct, zlib
import numpy as np
A = open(sys.argv[1], 'rb').read()
be = lambda o: struct.unpack_from('>I', A, o)[0]

def fletcher_words(buf):                      # a += w ; b += a   (mod 2^32), BE words
    w = np.frombuffer(buf, dtype='>u4').astype(np.uint64)
    n = len(w)
    a = int(w.sum() & 0xffffffff)
    b = int((w * np.arange(n, 0, -1, dtype=np.uint64) & 0xffffffff).sum() & 0xffffffff)
    return a, b

off, ok = 0x1c, True
for n in range(be(0x14)):
    etype, words, h1, h2 = be(off+4), be(off+0xc), be(off+0x10), be(off+0x14)
    body = A[off+0x20: off+0x20+words*4]      # starts at the 0x56112603 word
    a, b = fletcher_words(body)
    crc_stored, plen = be(off+0x28), be(off+0x2c)
    data = A[off+0x220: off+0x220+plen]       # image data, 0x200 after the 0x56112603 word
    swapped = np.frombuffer(data[:plen & ~3], dtype='>u4').astype('<u4').tobytes() + data[plen & ~3:]
    crc = zlib.crc32(swapped)
    line = f"[{n:2d}] type={etype} words={words:#x} fletcher={'OK ' if (a,b)==(h1,h2) else 'BAD'} crc32={'OK ' if crc==crc_stored else 'BAD'}"
    magic = struct.unpack_from('<I', swapped, 0)[0]
    if magic == 0x230b0c5e:     # LPC image header
        _, size, icrc, ver = struct.unpack_from('<4I', swapped, 0)
        c2 = zlib.crc32(swapped[0x34:size])
        line += f" image(size={size:#x}) crc32={'OK' if c2==icrc else 'BAD'}"
        ok &= c2 == icrc
    elif magic == 0x4023245e and len(swapped) >= 0x200:  # Entry 3 / Entry 5 DB header
        _, ver, tsize, str_off, scrc, str_len = struct.unpack_from('<6I', swapped, 0)
        if str_off and str_off + str_len <= len(swapped):
            c2 = zlib.crc32(swapped[str_off:str_off+str_len])
            line += f" db(size={tsize:#x}) str_crc32={'OK' if c2==scrc and tsize==len(swapped) else 'BAD'}"
            ok &= (c2 == scrc and tsize == len(swapped))
    elif magic == 0x28267e5e:   # Entry 4 Model & Composite Blob Directory
        _, ver, nblobs, dir_off, b0_off, twords = struct.unpack_from('<6I', swapped, 0)
        line += f" blobs(n={nblobs}, words={twords:#x}) size={'OK' if twords*4==len(swapped) else 'BAD'}"
        ok &= (twords * 4 == len(swapped))
    ok &= (a, b) == (h1, h2) and crc == crc_stored
    print(line)
    off += 0x24 + words*4
print('ALL OK' if ok else 'MISMATCH')
