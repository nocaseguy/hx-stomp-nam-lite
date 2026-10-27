"""ssim's number helpers."""
import json
from pathlib import Path

import pytest

import ssim


@pytest.mark.parametrize("x", [0.0, 1.0, -2.5, 0.1, 1e-30, 3.4e38])
def test_f2b_b2f_round_trip(x):
    assert ssim.f2b(ssim.b2f(ssim.f2b(x))) == ssim.f2b(x)


def test_f2b_overflow_is_infinity():
    assert ssim.f2b(1e300) == 0x7F800000
    assert ssim.f2b(-1e300) == 0xFF800000


def test_ftz_flushes_denormals_keeping_sign():
    assert ssim.ftz(0x00000001) == 0
    assert ssim.ftz(0x80000001) == 0x80000000
    assert ssim.ftz(0x3F800000) == 0x3F800000


@pytest.mark.parametrize("v, n", [(0, 32), (1, 31), (0x80000000, 0), (0x00010000, 15)])
def test_clz32(v, n):
    assert ssim.clz32(v) == n


@pytest.mark.parametrize("v, bits, want", [(0x7F, 8, 127), (0x80, 8, -128), (0xFFFF, 16, -1)])
def test_sx(v, bits, want):
    assert ssim.sx(v, bits) == want


def test_recips_is_close_to_one_over_x():
    for x in (1.0, 1.5, 3.0, 100.0, -0.25):
        r = ssim.b2f(ssim.recips_hw(ssim.f2b(x)))
        assert r == pytest.approx(1 / x, rel=1 / 128)
