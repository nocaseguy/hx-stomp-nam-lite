"""The whole build from the stock 3.80.0 .hxf (not in the repo: point HX_STOMP_HXF
and/or HX_STOMP_XL_HXF at your copy). The build is deterministic, so the output's
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

# Both units: the 4-knob NAM A2 Lite in Amp > NAM on MM4 Frequency Shifter's ID 461 (build.py's
# STEPS), the kernel without its tone stack (--no-tone), DSP cost 2220. The HX Stomp's is the image
# that ran on an HX Stomp from RAM (the on-device smoke suite); the XL's has not run on an XL.
BUILT_MD5 = {
    "HX_STOMP_HXF": "dcb425f111c0667f9c03e5779173ae35",
    "HX_STOMP_XL_HXF": "109caca26065425c5e21f5da8d63e774",     # not run on an XL
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

