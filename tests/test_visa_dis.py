"""visa_dis: the ISA decoder against sasm, the VISA lengths and short forms, the Entry 2 loader, and (firmware) the stock code."""
import functools
import os
import re
import struct

import pytest

import sasm
import visa_dis as v


# ---- ISA
ISA = ["R2 = R2 AND R3", "IF EQ R1 = R2 + R3", "F4 = F12 * F4", "R0 = R1 + R2, R3 = R1 - R2",
       "F8 = F2 * F4, F12 = F8 + F12", "MRF = MRF + R2 * R3 (SSF)", "R1 = MR0F", "MR1B = R4",
       "R2 = LSHIFT R3 BY -5", "R1 = FEXT R2 BY 4:8", "R4 = R14 + R2, DM(I7,M7) = R2", "R0 = DM(I1,M2), R4 = PM(I9,M10)",
       "R10 = DM(M6,I6)", "DM(-10,I6) = R2", "R2 = PASS R12, DM(-3,I6) = R2", "R2 = I6", "I4 = R15", "R2 <-> S2",
       "R2 = LSHIFT R3 BY 3, DM(I1,M2) = R4", "DM(I7,M7) = 0x608492", "R3 = DM(-25,I6)", "DM(0x88,I4) = M14",
       "NOP", "IDLE", "MODIFY(I3,M2)", "I2 = MODIFY(I5,M5), R1 = R1 + 1", "JUMP 0x6082b3 (DB)", "IF LT CALL 0x8c3ea",
       "JUMP (M14,I12) (DB)", "IF EQ JUMP (M8,I9), ELSE R1 = R1 - 1", "RTS (DB)", "IF NE RTI",
       "LCNTR = 16, DO 0x120 UNTIL LCE", "LCNTR = R2, DO 0x120 UNTIL LCE", "DO 0x120 UNTIL NOT AC",
       "R0 = 0x77aac", "I4 = 0x13d29f1", "R2 = DM(0xe149a)", "DM(0xc00) = I4", "BIT SET MODE1 0x200000",
       "MODIFY(I7,-2)", "I2 = MODIFY(I5,5)", "BITREV(I1,4)", "PUSH LOOP, PUSH STS", "CJUMP 0x6082b3 (DB)", "RFRAME"]


@pytest.mark.parametrize("text", ISA)
def test_isa_text_reencodes_to_the_same_word(text):
    pc = 0x100
    for w in sasm.encode(text, sasm.Ctx(pc=pc)):
        assert w in sasm.encode(v.isa_text(w, pc), sasm.Ctx(pc=pc)), text


def test_isa_pc_relative_targets_are_absolute():
    w = sasm.encode("JUMP (PC, 0x90) (DB)", sasm.Ctx(pc=0x100))[0]
    assert v.isa_text(w, 0x100) == "JUMP (PC, 0x90) (DB)"


def test_isa_unknown_is_none():
    assert v.isa_text(0x000E16970000) is None


# ---- VISA lengths and forms
@pytest.mark.parametrize("p1, p2, n", [
    (0x1804, 0, 3), (0x9FF2, 0, 1), (0x9FC0, 0, 3), (0x9FC4, 0, 2), (0x9D08, 0, 2), (0x9428, 0, 2),
    (0x0F82, 0, 2), (0x0F02, 0, 3), (0x01A8, 0, 2), (0x013E, 0, 3), (0x083F, 0x343F, 2), (0x083F, 0x3400, 3),
    (0x713E, 0x013F, 2), (0x70FF, 0x8200, 3), (0x294F, 0xB13F, 2), (0x1901, 0, 1), (0x0001, 0, 1), (0x0000, 0, 3), (0x0A3E, 0, 3),
    (0xCC23, 0, 1), (0x0ABF, 0, 1), (0x1002, 0, 3), (0xA602, 0, 3), (0xD000, 0, None)])
def test_length(p1, p2, n):
    assert v.length(p1, p2) == n


@pytest.mark.parametrize("parcels, text", [
    ((0x1804, 0x0060, 0x82B3), "CJUMP 0x6082b3 (DB)"),
    ((0x9FF2,), "DM(I7,M7) = R2"),
    ((0x9B52,), "R2 = DM(I5,M5)"),
    ((0x9FC0, 0x0060, 0x8492), "DM(I7,M7) = 0x608492"),
    ((0x9FC4, 0x0005), "DM(I7,M7) = 5"),
    ((0x9D08, 0x01E7), "DM(-25,I6) = R3"),
    ((0x9C08, 0x07FD), "R15 = DM(-3,I6)"),
    ((0x9428, 0x0110), "R2 = PM(16,I10)"),
    ((0x4DFE, 0x0E3F), "I12 = DM(M7,I6)"),
    ((0x083F, 0x343F), "JUMP (M14,I12) (DB)"),
    ((0x713E, 0x013F), "R2 = I0"),
    ((0x0F14, 0x013D, 0x29F1), "I4 = 0x13d29f1"),
    ((0x0F80, 0xFF80), "R0 = -0x80"),
    ((0x0193, 0x04C4), "F4 = F12 * F4"),
    ((0x0180, 0xB0DA), "COMPU(R13, R10)"),
    ((0x1002, 0x000E, 0x149A), "R2 = DM(0xe149a)"),
    ((0x1901,), "RFRAME"),
    ((0x0001,), "NOP"),
    ((0xCC2C,), "R2 = R2 AND R12"),
    ((0xCD21,), "R2 = R2 OR R1"),
    ((0xC321,), "COMP(R2, R1)"),
    ((0xC412,), "R1 = NOT R2"),
    ((0x0ABE,), "RTS"),
    ((0x0ABF,), "RTS (LR)"),
    ((0x0AC4,), "IF LE RTS (DB)"),
])
def test_visa_text(parcels, text):
    assert v.visa_text(parcels, 0x600000) == text


def test_visa_pc_relative_counts_parcels():
    assert v.visa_text((0x070E, 0x0000, 0x000C), 0x609244) == "IF SV JUMP (PC, 0x609250)"
    assert v.visa_text((0x0702, 0x04FF, 0xFFDB), 0x6083A5) == "IF LT JUMP (PC, 0x608380) (DB)"


def test_disasm_prints_unknown_parcels_raw_and_stops_at_a_gap():
    sw = {0x10: 0x00C1, 0x11: 0x9FF2, 0x12: 0x1804, 0x13: 0x0060, 0x14: 0x82B3, 0x20: 0x0001}
    got = [(i.addr, i.text) for i in v.disasm(sw, 0x10, 0x30)]
    assert got == [(0x10, "?? 00c1"), (0x11, "DM(I7,M7) = R2"), (0x12, "CJUMP 0x6082b3 (DB)")]


# ---- the loader
def _ldr(*blocks):
    words = [0] * 384
    for tag, cnt, addr, body in blocks:
        words += [tag, cnt, addr] + body
    return struct.pack("<%dI" % (len(words) + 3), *words, 0, 0, 0)


def test_parse_entry2_parcel_order_counts_and_zero_fills():
    pm_word = 0x0F0000077AAC
    pm_body = list(struct.unpack("<3I", pm_word.to_bytes(6, "little") + (0).to_bytes(6, "little")))
    img = v.parse_entry2(_ldr((5, 1, 0x8C100, pm_body), (2, 2, 0x8C101, []), (4, 2, 0xE149A, [7, 8]),
                              (3, 3, 0x13AC4B, [0x0F000007, 0x7AACFFFF]),         # odd count: last half is padding
                              (1, 2, 0x13AC4E, []),
                              (10, 1, 0x300001, [0x00011901]), (1, 1, 0x300002, [])))
    assert img.pm == {0x8C100: pm_word, 0x8C101: 0, 0x8C102: 0}        # tag-2 zero fill: NOPs
    assert img.dm == {0xE149A: 7, 0xE149B: 8}
    assert {a: img.sw[a] for a in range(0x13AC4B, 0x13AC50)} == {0x13AC4B: 0x0F00, 0x13AC4C: 0x0007, 0x13AC4D: 0x7AAC,
                                                                  0x13AC4E: 0, 0x13AC4F: 0}
    assert 0x13AC50 not in img.sw
    assert [img.sw[a] for a in range(0x600002, 0x600006)] == [0x1901, 0x0001, 0, 0]


def test_parse_entry2_rejects_an_unknown_tag():
    with pytest.raises(ValueError, match="desync"):
        v.parse_entry2(_ldr((0x55, 0, 0, [])))


# ---- the stock file
@functools.lru_cache(maxsize=None)
def _img():
    path = os.environ.get("HX_STOMP_HXF")
    if not path:
        pytest.skip("HX_STOMP_HXF is not set")
    return v.load(path)


@functools.lru_cache(maxsize=None)
def _sweep():
    """Every VISA instruction, swept linearly through each contiguous run of parcels."""
    sw = _img().sw
    keys = sorted(sw)
    runs, start = [], keys[0]
    for a, b in zip(keys, keys[1:]):
        if b != a + 1:
            runs.append((start, a + 1))
            start = b
    runs.append((start, keys[-1] + 1))
    return [i for a, b in runs for i in v.disasm(sw, a, b)]


@pytest.mark.firmware
def test_stock_pm_code_reencodes_with_sasm():
    pm = _img().pm
    undecoded = []
    for a, w in pm.items():
        t = v.isa_text(w, a)
        if t is None:
            undecoded.append(a)
        else:
            assert w in sasm.encode(t, sasm.Ctx(pc=a)), (hex(a), t)
    assert sorted(undecoded) == [0x8EA83, 0x8EA84]          # data words after an RTI


@pytest.mark.firmware
def test_stock_pm_listing_has_no_holes():
    pm = _img().pm
    assert sorted(pm) == list(range(0x8C100, 0x8EE96))
    assert [i.text for i in v.disasm_pm(pm, 0x8C111, 0x8C117)] == ["R0 = DM(0x200000)"] + ["NOP"] * 4 + ["I12 = DM(M7,I6)"]


@pytest.mark.firmware
def test_stock_visa_sweep_lands_on_every_call_and_branch_target():
    ins = _sweep()
    starts = {i.addr for i in ins}
    calls = [i for i in ins if i.text.startswith("CJUMP 0x")]
    assert len(calls) > 2000
    outside = set()
    for c in calls:
        target = int(c.text.split()[1], 16)
        if target not in starts and target not in _img().pm:
            outside.add(target)
    assert outside == {0x8C0C3, 0x8C0EC}                    # PM code below Entry 2's tag-5 block
    pm_targets = 0
    for i in ins:
        m = re.search(r"\(PC, (0x[0-9a-f]+)\)|DO (0x[0-9a-f]+) UNTIL", i.text)
        if m:
            t = int(m.group(1) or m.group(2), 16)
            pm_targets += t in _img().pm
            assert t in starts or t in _img().pm, v.fmt(i)
    assert pm_targets > 800


@pytest.mark.firmware
def test_stock_visa_leaves_only_the_filler_raw():
    raw = {i.parcels for i in _sweep() if i.text.startswith("??")}
    assert raw == {(0x00C1,)}


@pytest.mark.firmware
def test_stock_sport_setup():
    got = [i.text for i in v.disasm(_img().sw, 0x60925B, 0x6092B8)]
    assert got[:3] == ["R2 = DM(0xe149a)", "NOP", "DM(0xc43) = R2"]
    assert got[24:27] == ["I4 = 0x13d29f1", "DM(0xc00) = I4", "I4 = 0xd29f1"]
    assert got[-4:] == ["JUMP (M14,I12) (DB)", "RFRAME", "NOP", "MODIFY(I7,-0xa)"]


@pytest.mark.firmware
def test_stock_blob0_buffer_size_patch_site():
    # patch_amp.expand_sharc_blob0_buffer's w[37192..37193]: word 11732 of the tag-3 block at 0x1707e0
    a = 0x1707E0 + 2 * 11732
    assert [i.text for i in v.disasm(_img().sw, a, a + 4)] == ["R0 = 0x77aac", "RFRAME"]


@pytest.mark.firmware
def test_cli(capsys):
    _img()
    v.main(["0x6082b3", "+3"])
    assert capsys.readouterr().out.split("\n")[0].endswith("MODIFY(I7,-0x18);")
