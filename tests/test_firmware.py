"""The whole build from the stock 3.80.0 .hxf (not in the repo: point HX_STOMP_HXF,
HX_STOMP_XL_HXF and/or HX_EFFECTS_HXF at your copy). The build is deterministic, so the output's
MD5 is pinned: a change to any byte of the firmware fails here until BUILT_MD5
is updated on purpose."""
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.firmware

# Both units: the ten-knob NAM A2 Lite with its tone stack in Amp > NAM on Xenomorph Fuzz Mono's ID 555
# (build.py's STEPS), the kernel's --mid-sweep, DSP cost 2275. The HX Stomp's is the image that ran on an
# HX Stomp from RAM (the on-device smoke suite, every EQ band measured); the XL's has not run on an XL.
BUILT_MD5 = {
    "HX_STOMP_HXF": "e6431a5f2ba4d86f1f7f9300506a1101",
    "HX_STOMP_XL_HXF": "a53e185be36fb4e8feedb5f2b89a1505",     # not run on an XL
    "HX_EFFECTS_HXF": "3a5b47d995c4af2319690bb4a6e8bd2f",      # Distortion > Mono (tools/effects.py); ran on an HX Effects
}


@pytest.mark.parametrize("env", BUILT_MD5)
def test_build(tmp_path, env):
    stock = os.environ.get(env)
    if not stock:
        pytest.skip(f"{env} is not set")
    out = tmp_path / "out.hxf"
    r = subprocess.run([sys.executable, str(ROOT / "build.py"), stock, "-o", str(out), "--no-check"],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ALL OK" in r.stdout
    assert hashlib.md5(out.read_bytes()).hexdigest() == BUILT_MD5[env]

