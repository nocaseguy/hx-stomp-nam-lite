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

# The HX Stomp's is hx-stomp-kit's `kit.py build ... nam-a2-lite --ir-title` byte for byte. Its
# kernel is that of the image (then preset ID 148, "NAM Lite Multi") that ran on an HX Stomp
# from RAM (two blocks, two captures, the IR names in the titles), plus the Polarity knob.
BUILT_MD5 = {
    "HX_STOMP_HXF": "a54ace94a6a8f1ded17513cf7d0019fd",
    "HX_STOMP_XL_HXF": "e109ba3062277e62e2f53112abed2d77",     # no IR-name title; not run on an XL
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


def test_ir_title_refuses_the_xl(tmp_path):
    stock = os.environ.get("HX_STOMP_XL_HXF")
    if not stock:
        pytest.skip("HX_STOMP_XL_HXF is not set")
    r = subprocess.run([sys.executable, str(ROOT / "tools/patch_amp.py"), "ir-title", stock,
                        str(tmp_path / "out.hxf"), "--preset-id", "148"], capture_output=True, text=True)
    assert r.returncode != 0 and "HX Stomp only" in r.stderr
    assert not (tmp_path / "out.hxf").exists()
