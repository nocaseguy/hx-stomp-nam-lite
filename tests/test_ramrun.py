"""The RAM run: web/ramrun.js against stand-in USB devices (tests/ramrun_fake.js), the numbers
src/ramboot/ramboot.h shares with tools/hxf_ram.py and web/ramrun.js, the built loader and hook
in tools/ramboot/ against their source, and the plan of a real build (needs a stock .hxf)."""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import hxf_ram

ROOT = Path(__file__).resolve().parent.parent
HEADER = (ROOT / "src/ramboot/ramboot.h").read_text()
JS = (ROOT / "web/ramrun.js").read_text()


def header(name):
    return int(re.search(rf"#define RB_{name}\s+(0x[0-9A-Fa-f]+|\d+)u", HEADER).group(1), 0)


def js(name):
    return int(re.search(rf"\b{name}: (0x[0-9A-Fa-f]+|\d+)", JS.split("var RB = {")[1].split("};")[0]).group(1), 0)


NAMES = {"VERSION": "RB_VERSION", "HOOK_BASE": "RB_HOOK_BASE", "STAGE_BASE": "RB_STAGE_BASE", "DESC": "RB_DESC",
         "FREE_END": "RB_FREE_END", "REQ_INFO": "REQ_INFO", "REQ_ADDR": "REQ_ADDR", "REQ_DATA": "REQ_DATA",
         "REQ_LEN": "REQ_LEN", "REQ_CRC": "REQ_CRC", "REQ_EMMC_CRC": "REQ_EMMC_CRC", "REQ_GO": "REQ_GO",
         "GO_KEY": "GO_KEY", "CHUNK": "CHUNK"}


@pytest.mark.parametrize("name", NAMES)
def test_shared_numbers(name):
    assert header(name) == js(name) == getattr(hxf_ram, NAMES[name])


@pytest.mark.skipif(shutil.which("arm-none-eabi-gcc") is None, reason="arm-none-eabi-gcc is not installed")
def test_built_files_match_source(tmp_path):
    out = tmp_path / "out"
    r = subprocess.run(["make", "-C", str(ROOT / "src/ramboot"), f"OUT={out}", f"B={tmp_path / 'b'}"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    for f in ("firmware-ramboot.dfu", "ramboot-hook.bin"):
        assert (out / f).read_bytes() == (ROOT / "tools/ramboot" / f).read_bytes(), f


def test_hook_header():
    hook = (ROOT / "tools/ramboot/ramboot-hook.bin").read_bytes()
    assert int.from_bytes(hook[0:4], "little") == hxf_ram.HOOK_MAGIC
    assert int.from_bytes(hook[4:8], "little") == 1


def fake(scenario):
    r = subprocess.run(["node", str(ROOT / "tests/ramrun_fake.js"), str(ROOT / "web/ramrun.js"), scenario],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


@needs_node
@pytest.mark.parametrize("scenario,asks", [
    ("full", ["dfu", "loader"]),                          # the browser asks for each new device
    ("dfu-allowed", ["dfu", "unask", "loader", "unask"]),  # it doesn't: no click needed
    ("from-dfu", ["loader"]),                             # started with Page Right
])
def test_run(scenario, asks):
    r = fake(scenario)
    assert r["errors"] == [] and r["ok"], r
    assert r["ask"] == asks
    assert r["dfuOk"] and r["dfuBlocks"] == [2048, 2048, 16]    # wTransferSize from the DFU descriptor
    assert r["memOk"] and r["go"]
    assert r["stages"][-3:] == ["loader", "upload", "start"]


@needs_node
def test_busy():
    r = fake("busy")
    assert not r["ok"] and r["code"] == "busy"


@needs_node
def test_emmc_not_stock():
    r = fake("emmc-bad")
    assert not r["ok"] and r["code"] == "emmc" and not r["go"] and r["loaderWrites"] == 0


@pytest.mark.firmware
def test_plan_of_the_build(tmp_path):
    stock = os.environ.get("HX_STOMP_HXF")
    if not stock:
        pytest.skip("HX_STOMP_HXF is not set")
    out = tmp_path / "out.hxf"
    r = subprocess.run([sys.executable, str(ROOT / "build.py"), stock, "-o", str(out), "--no-check"],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
    regions, checks, summary = hxf_ram.plan(str(out), stock)
    assert [i for i, *_ in summary["changed"]] == [2, 3, 4]
    assert summary["end"] <= hxf_ram.RB_STAGE_BASE
    assert sum(len(b) for _, b, _ in regions) < 4 << 20
