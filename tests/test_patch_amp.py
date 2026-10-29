"""patch_amp.py helpers that need no firmware."""
import pytest

import patch_amp


@pytest.mark.parametrize("rd, imm", [(0, 0), (3, 0x1234), (15, 0xFFFF), (7, 0x0800)])
def test_thumb_movw_round_trip(rd, imm):
    assert patch_amp._decode_thumb_movw(patch_amp._encode_thumb_movw(rd, imm)) == (rd, imm)


def test_decode_refuses_other_instructions():
    with pytest.raises(AssertionError):
        patch_amp._decode_thumb_movw(b"\x00\xbf\x00\xbf")   # two Thumb NOPs


def test_thumb_bw():
    # B.W forward and back, as an assembler encodes them
    assert patch_amp.thumb_bw(0x1000, 0x1004) == bytes.fromhex("00f000b8")
    assert patch_amp.thumb_bw(0x1004, 0x1000) == bytes.fromhex("fff7fcbf")


def test_ir_title_cave():
    X = patch_amp.IR_TITLE[0x28d8fa80]
    cave, ca, cb = patch_amp.ir_title_cave(0x28e4d344, [148], X)
    assert len(cave) == 60 and len(cave) % 4 == 0 and ca == 0x28e4d344
    assert cave[:4] == bytes.fromhex("237b0f2b")                  # caveA: ldrb r3,[r4,#12]; cmp r3,#15
    assert cave[cb - ca: cb - ca + 4] == bytes.fromhex("2b7b0f2b")  # caveB: ldrb r3,[r5,#12]; cmp r3,#15
    assert patch_amp._cmp_r3(148) in cave
    assert bytes.fromhex("0025") in cave                          # movs r5,#0 (the Stomp's IR_REG)


def test_ir_title_cave_xl():
    X = patch_amp.IR_TITLE[0x28d92230]
    cave, ca, cb = patch_amp.ir_title_cave(0x28e53aac, [147], X)
    assert len(cave) == 60 and cave[:4] == bytes.fromhex("237b0f2b")
    assert bytes.fromhex("0026") in cave and bytes.fromhex("0025") not in cave   # movs r6,#0
