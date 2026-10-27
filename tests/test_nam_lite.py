"""The model data nam_lite.py lays out, and the .wav nam2ir.py writes (no simulator)."""
import math
import struct
import subprocess
import sys
from pathlib import Path

import pytest

import nam2ir
import nam_lite
import nam_pack
import ssim

ROOT = Path(__file__).resolve().parent.parent


def floats(words):
    return [ssim.b2f(v) for v in words]


def test_placeholder_is_an_a2_lite_model(weights):
    assert len(weights) == nam_lite.N_WEIGHTS
    assert weights == nam_lite.placeholder()        # seeded: the same every run


def test_stream_is_weights_then_silence_state(weights):
    st = nam_lite.stream(weights)
    assert len(st) == nam_lite.N_WEIGHTS + nam_lite.C * (1 + len(nam_pack.KERNEL))
    assert sorted(st[:nam_lite.N_WEIGHTS]) == sorted(weights)


def test_ir_samples_header_and_size(weights):
    s = floats(nam_lite.ir_samples(weights))
    assert len(s) == nam_lite.IR_SAMPLES
    assert s[:3] == [0.5, -0.5, 3.0]
    assert s[4] == nam_lite.N_WEIGHTS / 1024
    assert s[-1] == 0                               # no tail fade in HX Edit


def test_ir_samples_within_hx_edit_limit(weights):
    assert max(abs(x) for x in floats(nam_lite.ir_samples(weights))) < nam_lite.IR_LIMIT


def test_ir_samples_scale_is_exact():
    w = [40.0] * 3 + nam_lite.placeholder()[3:]     # a peak over 15.5
    s = floats(nam_lite.ir_samples(w))
    e = math.log2(s[3])
    assert e == int(e) and e > 0
    st = nam_lite.stream(w)
    assert [x * s[3] for x in s[8: 8 + len(st)]] == [ssim.b2f(ssim.f2b(x)) for x in st]


def test_silence_state_is_finite(weights):
    hs, xs = nam_lite.silence(weights)
    assert all(math.isfinite(v) for v in hs + [v for x in xs for v in x])


@pytest.mark.parametrize("kind, f0", nam_lite.EQ_BANDS)
def test_eq_flat_at_0_db(kind, f0):
    b0, b1, b2, na1, na2 = nam_lite.eq_coefficients(kind, f0, 0.0)
    assert (b0, b1, b2) == pytest.approx((1.0, -na1, -na2))


@pytest.mark.parametrize("kind, f0, at", [("low", 100.0, 0.0), ("high", 2500.0, math.pi), ("peak", 650.0, None)])
def test_eq_gain(kind, f0, at):
    """+12 dB where the band acts: DC for the low shelf, Nyquist for the high, f0 for the peak."""
    b0, b1, b2, na1, na2 = nam_lite.eq_coefficients(kind, f0, 12.0)
    w = 2 * math.pi * f0 / 48000 if at is None else at
    z = complex(math.cos(w), -math.sin(w))
    h = (b0 + b1 * z + b2 * z * z) / (1 - na1 * z - na2 * z * z)
    assert 20 * math.log10(abs(h)) == pytest.approx(12.0, abs=0.01)


def test_eq_table_size():
    assert len(nam_lite.eq_table()) == 4 * 101 * 5


def test_fade_table_is_equal_power():
    t = floats(nam_lite.fade_table())
    assert t[0] == 0 and t[16] == 1 and t[17] == 1
    for k in range(17):
        assert t[k] ** 2 + t[16 - k] ** 2 == pytest.approx(1, abs=1e-6)


def test_build_fits_memory(weights):
    _, used = nam_lite.build(weights)
    assert used["block 2 to"] <= nam_lite.B2_END
    assert used["block 3 to"] <= nam_lite.EQ_C
    assert used["DDR2 to"] <= nam_lite.DDR2_END


def test_nam2ir_writes_the_ir_samples(tmp_path, nam_file, weights):
    out = tmp_path / "m.wav"
    r = subprocess.run([sys.executable, str(ROOT / "tools/nam2ir.py"), str(nam_file()), "-o", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    b = out.read_bytes()
    assert b[:4] == b"RIFF" and b[8:12] == b"WAVE"
    fmt, ch, rate = struct.unpack_from("<HHI", b, 20)
    assert (fmt, ch, rate) == (3, 1, 48000)          # IEEE float, mono, 48 kHz
    assert list(struct.unpack_from("<2048I", b, 44)) == nam_lite.ir_samples(weights)


def test_problems_none_for_a2_lite(nam_file):
    assert nam2ir.problems(str(nam_file())) == []
    assert nam2ir.problems(str(nam_file(slimmable=True))) == []


@pytest.mark.parametrize("layer, says", [
    ({"dilations": [1] * 23}, "dilations"),
    ({"kernel_sizes": [3] * 23}, "kernel sizes"),
    ({"gating_mode": ["gated"] * 23}, "gated"),
    ({"activation": [{"type": "Tanh"}] * 23}, "Tanh"),
])
def test_problems_found(nam_file, layer, says):
    assert any(says in p for p in nam2ir.problems(str(nam_file(**layer))))
