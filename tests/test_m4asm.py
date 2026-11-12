"""tools/m4asm.py's check of each adr: Apple clang takes an adr's offset mod 4096, with no word, when its label is out of reach."""
import os

import pytest

import m4asm

CLANG = pytest.mark.skipif(not os.path.exists(m4asm.CLANG), reason='no clang')


def module(tmp_path, body, name='m.s'):
    p = tmp_path / name
    p.write_text('.syntax unified\n.thumb\n' + body)
    return str(p)


def plain(src, monkeypatch):
    """src's .text as clang gives it, with no marks."""
    with monkeypatch.context() as m:
        m.setattr(m4asm, 'mark_adr', lambda text, src: (text, []))
        return m4asm.assemble_module(src)[0]


@CLANG
@pytest.mark.parametrize('gap', [0x1008, 0x2008, 0x20008])
@pytest.mark.parametrize('op', ['adr', 'adr.w'])
def test_an_adr_out_of_reach_fails_the_build(tmp_path, gap, op):
    src = module(tmp_path, f'f:\n    {op} r1, far\n    bx lr\n.space {gap - 6}\nfar:\n    .space 4\n')
    with pytest.raises(SystemExit, match=r"m\.s:4: the adr to far is .* out of an adr's reach"):
        m4asm.assemble_module(src)


@CLANG
def test_an_adr_back_out_of_reach_fails_the_build(tmp_path):
    src = module(tmp_path, 'near:\n    .space 0x1010\nf:\n    adr.w r1, near\n    bx lr\n')
    with pytest.raises(SystemExit, match="the adr to near"):
        m4asm.assemble_module(src)


@CLANG
def test_adrs_in_reach_assemble_as_clang_does_with_no_marks_left(tmp_path, monkeypatch):
    src = module(tmp_path, '''f:
    adr r1, near
    adr.w r2, far @ a comment
2:  adr.w r3, near + 4
    it eq
    adreq r0, near
    bx lr
.space 0xf00
.align 2
near:
    .space 8
far:
    .space 4
back:
    adr.w r0, f
''')
    code, symbols = m4asm.assemble_module(src)
    assert code == plain(src, monkeypatch)
    assert set(symbols) == {'f', 'near', 'far', 'back'}


@CLANG
def test_an_adr_in_a_macro_is_refused(tmp_path):
    src = module(tmp_path, '.macro M\n    adr r0, x\n.endm\nx:\n    M\n')
    with pytest.raises(SystemExit, match='inside a .macro'):
        m4asm.assemble_module(src)


def test_marks_go_before_each_adr_after_any_label():
    text, adrs = m4asm.mark_adr('a:  adr.w r1, b - 8 @ x\n    ldr r0, =adr_table\n3:  ADR r2, c\n', 'm.s')
    assert text == 'a:  m4asm_adr_0: adr.w r1, b - 8 @ x\n    ldr r0, =adr_table\n3:  m4asm_adr_1: ADR r2, c\n'
    assert adrs == [(0, 'b', -8, 1), (1, 'c', 0, 3)]


def test_hx_clang_names_the_clang(tmp_path, monkeypatch):
    clang = tmp_path / 'my-clang'
    clang.write_text('#!/bin/sh\n')
    clang.chmod(0o755)
    monkeypatch.setenv('HX_CLANG', str(clang))
    assert m4asm.find_clang() == str(clang)
    monkeypatch.setenv('PATH', str(tmp_path))
    monkeypatch.setenv('HX_CLANG', 'my-clang')
    assert m4asm.find_clang() == str(clang)


def test_apple_clang_comes_before_path(tmp_path, monkeypatch):
    monkeypatch.delenv('HX_CLANG', raising=False)
    monkeypatch.setattr(m4asm.os.path, 'exists', lambda p: p == m4asm.APPLE_CLANG)
    monkeypatch.setattr(m4asm.shutil, 'which', lambda name: '/usr/bin/clang')
    assert m4asm.find_clang() == m4asm.APPLE_CLANG


def test_clang_on_path_without_apple_clang(monkeypatch):
    monkeypatch.delenv('HX_CLANG', raising=False)
    monkeypatch.setattr(m4asm.os.path, 'exists', lambda p: False)
    monkeypatch.setattr(m4asm.shutil, 'which', lambda name: f'/usr/bin/{name}')
    assert m4asm.find_clang() == '/usr/bin/clang'


def test_no_clang_says_how_to_get_one(tmp_path, monkeypatch):
    monkeypatch.delenv(m4asm.CACHE, raising=False)
    monkeypatch.setattr(m4asm, 'CLANG', str(tmp_path / 'none'))
    with pytest.raises(SystemExit, match='no clang at .*none: install it .*HX_CLANG'):
        m4asm.assemble_module(module(tmp_path, 'bx lr\n'))


@pytest.mark.parametrize('line', ['.balign 16, 0', '.align 4, 0', '.p2align 4, 0x0', 'x: .balign 8, 0, 7', '.balign 16,0 @ pad'])
def test_an_alignment_filled_with_0_fails_the_build(tmp_path, line):
    src = module(tmp_path, f'f:\n    bx lr\n{line}\n')
    with pytest.raises(SystemExit, match=r"m\.s:5: an alignment filled with 0"):
        m4asm.assemble_module(src)


@CLANG
@pytest.mark.parametrize('line', ['.balign 4', '.balignl 16, 0', '.balign 16, 0xff', '.org f + 16, 0'])
def test_other_alignments_assemble(tmp_path, line):
    assert m4asm.assemble_module(module(tmp_path, f'f:\n    bx lr\n    nop\n{line}\n'))[0][:4] == b'\x70\x47\x00\xbf'
