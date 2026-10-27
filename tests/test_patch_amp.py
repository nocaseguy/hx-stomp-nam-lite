"""patch_amp.py helpers that need no firmware."""
import pytest

import patch_amp


@pytest.mark.parametrize("rd, imm", [(0, 0), (3, 0x1234), (15, 0xFFFF), (7, 0x0800)])
def test_thumb_movw_round_trip(rd, imm):
    assert patch_amp._decode_thumb_movw(patch_amp._encode_thumb_movw(rd, imm)) == (rd, imm)


def test_decode_refuses_other_instructions():
    with pytest.raises(AssertionError):
        patch_amp._decode_thumb_movw(b"\x00\xbf\x00\xbf")   # two Thumb NOPs
