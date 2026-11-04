"""tests/m4emu.py itself: a broken test must fail, not pass. Calls of functions nobody stubbed, loops and a 5th argument fail;
stubs log their calls and can run code of their own; more memory can be mapped."""
import struct

import pytest

import patch_menu as pm

CAVE, FN = 0x28e60000, 0x28e61000


def calls_fn(target):
    """push {lr}; bl target; pop {pc}"""
    return struct.pack('<H', 0xb500) + pm.bl(CAVE + 2, target) + struct.pack('<H', 0xbd00)


def test_a_call_of_a_function_with_no_stub_fails(m4emu):
    m = m4emu.M4(calls_fn(FN), CAVE)
    m.stub(FN + 0x40)           # zeros run as movs r0,r0: without the check this would slide into that stub and return
    with pytest.raises(AssertionError, match='no stub'):
        m.call(CAVE)


def test_a_loop_fails(m4emu, monkeypatch):
    monkeypatch.setattr(m4emu, 'STEPS', 1000)
    m = m4emu.M4(struct.pack('<H', 0xe7fe), CAVE)       # b .
    with pytest.raises(AssertionError, match='a loop'):
        m.call(CAVE, 5)


def test_call_refuses_a_fifth_argument(m4emu):
    m = m4emu.M4(m4emu.BX_LR, CAVE)
    with pytest.raises(AssertionError, match='at most 4'):
        m.call(CAVE, 1, 2, 3, 4, 5)


def test_a_stub_logs_its_calls_and_can_set_r0(m4emu):
    m = m4emu.M4(calls_fn(FN), CAVE, log_regs=('r0', 'r12'))
    m.stub(FN, lambda m: m.reg('r0', 9))
    m.reg('r12', 0xabc)
    assert m.call(CAVE, 7) == 9
    assert m.calls(FN) == [(7, 0xabc)]
    m.log.clear()
    assert m.calls(FN) == []


def test_a_stub_can_run_code_of_its_own(m4emu):
    code = struct.pack('<H', 0xb500) + pm.thumb_bw(CAVE + 2, FN)       # push {lr}; b.w FN: FN returns for both
    m = m4emu.M4(code, CAVE)
    m.stub(FN, code=struct.pack('<H', 0xbd00))                       # pop {pc}
    m.call(CAVE)
    assert len(m.calls(FN)) == 1


def test_map_adds_memory(m4emu):
    m = m4emu.M4(m4emu.BX_LR, CAVE)
    m.map(0x20000000, 0x300000)
    m.u32(0x202ffffc, 0x12345678)
    assert m.u32(0x202ffffc) == 0x12345678
