"""The on-device QA tools (QA.md) without a unit: the USB handshake against the simulated stock
app, the preset blob, the recording scan, and (with a stock .hxf) what hx_smoke reads from an image."""
import math
import os
import struct
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
msgpack = pytest.importorskip("msgpack")
import hx_ctl  # noqa: E402
import hx_smoke  # noqa: E402


def test_dfu_reboot_dry_run():
    r = subprocess.run([sys.executable, "tools/hx_dfu_reboot.py", "--dry-run"], cwd=ROOT,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "DeviceResult: 0" in r.stdout


def test_smoke_lists_its_cases():
    r = subprocess.run([sys.executable, "tools/hx_smoke.py", "--list"], cwd=ROOT,
                       capture_output=True, text=True, timeout=60)
    names = [line.split()[0] for line in r.stdout.splitlines()]
    assert r.returncode == 0
    assert {"presets_list", "nam1", "nam3", "budget", "amp_limit", "nam_takeover"} <= set(names)


def test_preset_blob_round_trip():
    """A preset with one block encodes, decodes and keeps its block."""
    empty = [{19: 8, 20: None} for _ in range(20)]
    sec = {7: {}, 0: {22: empty}, 1: {}, 3: {}, 4: {}, 2: {}, 5: {}, 6: {}, 10: {}}
    hx_ctl.set_model(sec, 0, 0, 182, params=[1.0, 0, 12, 0.5, 0.0], kind=1)
    magic, back = hx_ctl.decode_preset(hx_ctl.encode_preset("l6-helix", sec))
    b = hx_ctl.blocks(back)[1][20]
    assert (b[24][25], b[9], b[11][4]) == (182, 1, [1.0, 0, 12, 0.5, 0.0])


def _wav(tmp_path, x, rate=48000):
    data = struct.pack(f"<{len(x)}f", *x)
    fmt = struct.pack("<HHIIHH", 3, 1, rate, rate * 4, 4, 32)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(data)) + data
    p = tmp_path / "rec.wav"
    p.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    return str(p)


def test_scan_finds_clicks_and_dropouts(tmp_path):
    sine = [0.3 * math.sin(2 * math.pi * 220 * k / 48000) for k in range(48000)]
    assert hx_smoke.scan(_wav(tmp_path, sine))[2:] == (0, 0, 0)
    bad = list(sine)
    bad[10000] += 0.5                                       # a click
    bad[20000:20032] = [0.0] * 32                           # a dropout
    _, _, rep, drops, clicks = hx_smoke.scan(_wav(tmp_path, bad))
    assert drops == 1 and clicks >= 1


@pytest.mark.firmware
def test_smoke_reads_the_built_image(tmp_path):
    stock = os.environ.get("HX_STOMP_HXF")
    if not stock:
        pytest.skip("HX_STOMP_HXF is not set")
    out = tmp_path / "nam.hxf"
    subprocess.run([sys.executable, "build.py", stock, "-o", str(out)], cwd=ROOT, check=True,
                   capture_output=True, timeout=1200)
    l6ia, _ = hx_smoke.patch_amp.load_l6ia_from_any(str(out))
    hx_smoke.set_profile(l6ia)
    assert hx_smoke.NAM["name"] == "donor_eq"
    costs = hx_smoke.table1_costs(l6ia)
    assert costs[555] == 2275
    cat = hx_smoke.stock_catalog(l6ia, costs)
    assert {"distortion", "delay", "reverb", "amp", "cab"} <= set(cat)
    assert hx_ctl.find_kind_and_params(hx_smoke._EMPTY, 182, factory=stock)[0] == 1
