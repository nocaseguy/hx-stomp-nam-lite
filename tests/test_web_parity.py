"""web/nam2ir-core.js writes the same bytes as tools/nam2ir.py, and refuses the same captures."""
import json
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import nam_json

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

NODE = """
const core = require(process.argv[1]);
const fs = require("fs");
try {
  const r = core.convert(fs.readFileSync(process.argv[2], "utf8"));
  fs.writeFileSync(process.argv[3], r.wav);
  process.stdout.write(JSON.stringify({ok: true}));
} catch (e) {
  process.stdout.write(JSON.stringify({ok: false, error: e.message}));
}
"""


def js_convert(src, out):
    r = subprocess.run(["node", "-e", NODE, str(ROOT / "web/nam2ir-core.js"), str(src), str(out)],
                       capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def py_convert(src, out):
    return subprocess.run([sys.executable, str(ROOT / "tools/nam2ir.py"), str(src), "-o", str(out)],
                          capture_output=True, text=True)


@pytest.mark.parametrize("big, slimmable", [(False, False), (True, False), (False, True)],
                         ids=["plain", "scaled 2^e", "slimmable"])
def test_same_bytes(tmp_path, nam_file, weights, big, slimmable):
    # big: rechannel weights of 40 (a peak over 15.5: the samples / 2^e); they see 0 in silence
    src = nam_file([40.0] * 3 + weights[3:] if big else weights, slimmable=slimmable)
    r = py_convert(src, tmp_path / "py.wav")
    assert r.returncode == 0, r.stderr
    assert js_convert(src, tmp_path / "js.wav") == {"ok": True}
    assert (tmp_path / "js.wav").read_bytes() == (tmp_path / "py.wav").read_bytes()


@pytest.mark.parametrize("dbu", [12.2, 18.0, 3.7, 15])
def test_same_bytes_with_level(tmp_path, nam_file, weights, dbu):
    # a capture that gives its input level: both put it in word 5, the weights as they are
    src = nam_file(metadata={"input_level_dbu": dbu})
    r = py_convert(src, tmp_path / "py.wav")
    assert r.returncode == 0, r.stderr
    assert f"input level {dbu:g} dBu" in r.stdout
    assert js_convert(src, tmp_path / "js.wav") == {"ok": True}
    py = (tmp_path / "py.wav").read_bytes()
    assert (tmp_path / "js.wav").read_bytes() == py
    plain = nam_file(name="plain.nam")
    assert py_convert(plain, tmp_path / "plain.wav").returncode == 0
    words = struct.unpack("<2048f", py[44:])
    assert words[5] == pytest.approx(10 ** (-dbu / 20), rel=1e-6)
    other = struct.unpack("<2048f", (tmp_path / "plain.wav").read_bytes()[44:])
    assert words[:5] + words[6:] == other[:5] + other[6:]


@pytest.mark.parametrize("metadata", [None, {}, {"input_level_dbu": None}, {"input_level_dbu": "15"},
                                      {"input_level_dbu": True}], ids=["none", "empty", "null", "string", "bool"])
def test_no_level_no_trim(tmp_path, nam_file, metadata):
    # no usable input_level_dbu: both leave the weights as they are
    src = nam_file(metadata=metadata)
    r = py_convert(src, tmp_path / "py.wav")
    assert r.returncode == 0, r.stderr
    assert "input level none" in r.stdout
    assert js_convert(src, tmp_path / "js.wav") == {"ok": True}
    plain = nam_file(name="plain.nam")
    assert py_convert(plain, tmp_path / "plain.wav").returncode == 0
    assert (tmp_path / "js.wav").read_bytes() == (tmp_path / "py.wav").read_bytes() == (tmp_path / "plain.wav").read_bytes()


@pytest.mark.parametrize("layer", [
    {"dilations": [1] * 23},
    {"kernel_sizes": [3] * 23},
    {"gating_mode": ["none"] * 22 + ["gated"]},
    {"activation": [{"type": "Tanh"}] * 23},
], ids=["dilations", "kernel sizes", "gated", "activation"])
def test_both_refuse(tmp_path, weights, layer):
    src = tmp_path / "bad.nam"
    src.write_text(nam_json(weights, **layer))
    assert py_convert(src, tmp_path / "py.wav").returncode != 0
    assert js_convert(src, tmp_path / "js.wav")["ok"] is False


def test_both_refuse_wrong_weight_count(tmp_path, weights):
    src = tmp_path / "bad.nam"
    src.write_text(nam_json(weights[:-1]))
    assert py_convert(src, tmp_path / "py.wav").returncode != 0
    assert js_convert(src, tmp_path / "js.wav")["ok"] is False


@pytest.mark.parametrize("loud", [-16.7, -28.3, -9.0, -50.0], ids=["-16.7", "-28.3", "-9", "too quiet"])
def test_same_bytes_with_loudness(tmp_path, nam_file, loud):
    # a capture that gives its loudness: both put 10^((-18 - loudness)/20) in word 6 (0 when the
    # word cannot hold it), and nothing else changes
    src = nam_file(metadata={"loudness": loud})
    r = py_convert(src, tmp_path / "py.wav")
    assert r.returncode == 0, r.stderr
    assert js_convert(src, tmp_path / "js.wav") == {"ok": True}
    py = (tmp_path / "py.wav").read_bytes()
    assert (tmp_path / "js.wav").read_bytes() == py
    words = struct.unpack("<2048f", py[44:])
    assert words[6] == (0.0 if loud < -42 else pytest.approx(10 ** ((-18 - loud) / 20), rel=1e-6))
    off = py_convert(src, tmp_path / "off.wav")
    assert "loudness left out" not in off.stdout
    plain = subprocess.run([sys.executable, str(ROOT / "tools/nam2ir.py"), str(src), "-o", str(tmp_path / "raw.wav"),
                            "--no-loudness"], capture_output=True, text=True)
    assert plain.returncode == 0 and "loudness left out (--no-loudness)" in plain.stdout
    other = struct.unpack("<2048f", (tmp_path / "raw.wav").read_bytes()[44:])
    assert words[:6] + words[7:] == other[:6] + other[7:] and other[6] == 0.0


@pytest.mark.parametrize("where", ["file", "model"])
def test_both_refuse_other_sample_rate(tmp_path, weights, where):
    d = json.loads(nam_json(weights))
    if where == "file":
        d = {"architecture": "SlimmableContainer", "sample_rate": 44100,
             "config": {"submodels": [{"model": d}]}}
    else:
        d["sample_rate"] = 44100.0
    src = tmp_path / "bad.nam"
    src.write_text(json.dumps(d))
    assert py_convert(src, tmp_path / "py.wav").returncode != 0
    assert js_convert(src, tmp_path / "js.wav")["ok"] is False


@pytest.mark.parametrize("layer", [
    {"conv_pre_film": {"active": True}},
    {"bottleneck": 2},
    {"head1x1": {"active": True}},
    {"layer1x1": {"active": False}},
    {"secondary_activation": [{"type": "Tanh"}] * 23},
    {"activation": [{"type": "LeakyReLU", "negative_slope": 0.2}] * 23},
], ids=["film", "bottleneck", "head1x1", "layer1x1", "secondary", "slope"])
def test_both_refuse_not_a2_shape(tmp_path, weights, layer):
    src = tmp_path / "bad.nam"
    src.write_text(nam_json(weights, **layer))
    assert py_convert(src, tmp_path / "py.wav").returncode != 0
    assert js_convert(src, tmp_path / "js.wav")["ok"] is False
