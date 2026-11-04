"""The RAM run: web/ramrun.js against stand-in USB devices (tests/ramrun_fake.js), the numbers
src/ramboot/ramboot.h shares with tools/hxf_ram.py and web/ramrun.js, the built loader and hook
in tools/ramboot/ against their source, and the plan of a real build (needs a stock .hxf)."""
import json
import os
import re
import shutil
import struct
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


class Timeout(Exception):
    pass


class FakeStomp:
    """A running HX Stomp's update service, as tests/ramrun_fake.js's Line6 plays it, for hxf_ram.Stream."""

    def __init__(self, result=0):
        self.result, self.q, self.seq, self.host_seq, self.rx, self.stage = result, [], 0, 0, b"", 0
        self.errors, self.entered = [], False

    def check(self, cond, what):
        if not cond:
            self.errors.append(what)

    def queue(self, flags, data=b"", syn=False):
        self.seq = (self.seq + 1) & 255
        body = (bytes([0, 0, 0, 2]) if syn else b"") + struct.pack("<2I", (flags << 24) | (self.seq << 8), 0x200)
        body += bytes(data)
        msg = struct.pack("<2I", ((2 if syn else 1) << 28) | (2 << 26) | len(body), 0x03EF | (0x1001 << 16)) + body
        self.q.append(msg + bytes(-len(msg) % 4))

    def read(self, ep, size, timeout):
        if not self.q:
            raise Timeout
        return self.q.pop(0)

    def write(self, ep, b, timeout):
        self.check(len(b) % 4 == 0, "OUT not padded to 4")
        w0, w1 = struct.unpack_from("<2I", b)
        kind, length, p = w0 >> 28, w0 & 0xFFFF, 8
        self.check((w0 >> 26) & 3 == 2, "transport version")
        self.check(w1 == 0x1001 | (0x3EF << 16), "addresses")
        if kind == 2:
            self.check(struct.unpack_from("<I", b, 8)[0] >> 16 == 512, "SYN mtu")
            p = 12
        s0 = struct.unpack_from("<I", b, p)[0]
        flags, seq = s0 >> 24, (s0 >> 8) & 255
        self.check(seq == (self.host_seq + 1) & 255, f"host sequence {seq}")
        self.host_seq = seq
        if flags & 0x01:
            self.check(flags == 0x21, "SYN flags")
            self.queue(0x01, syn=True)
            return
        if not flags & 0x04:
            return
        self.rx += b[p + 8: 8 + length]
        while True:
            if self.stage == 0 and len(self.rx) >= 9:
                self.check(self.rx[:9] == bytes([0, 0, 3, 0, 1, 0, 0, 0, 3]), "select service 3")
                self.rx, self.stage = self.rx[9:], 1
            elif self.stage == 1 and len(self.rx) >= 10:
                self.rx, self.stage = self.rx[10:], 2
                self.queue(0x04, [0, 0, 3, 0, 2, 0, 0, 0, 0, 0])
            elif self.stage == 2 and len(self.rx) >= 4:
                cmd, self.rx = self.rx[:4], self.rx[4:]
                self.check(cmd[0] == 0xAA, "command marker")
                if cmd[3] == 1:
                    self.queue(0x04, [1, 4, 4, 4])
                elif cmd[3] == 3:
                    self.queue(0x04, bytes(36))
                elif cmd[3] == 2:
                    self.queue(0x04, struct.pack("<i", self.result))
                    self.entered = True
            else:
                break


@pytest.mark.parametrize("result", [0, -1])
def test_enter_update_mode(result):
    dev = FakeStomp(result)
    st = hxf_ram.Stream(dev, 1, 0x81, 512, Timeout)
    if result < 0:
        with pytest.raises(SystemExit, match="refused update mode"):
            hxf_ram.enter_update_mode(st)
    else:
        hxf_ram.enter_update_mode(st)
    assert dev.errors == [] and dev.entered


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
