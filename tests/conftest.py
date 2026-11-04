import json
import re

import pytest

import nam_lite


def nam_json(weights, slimmable=False, metadata=None, **layer):
    """A .nam file's text: a 3-channel A2 Lite WaveNet (made up, no capture in the repo)."""
    lc = {"channels": nam_lite.C, "kernel_sizes": list(nam_lite.nam_pack.KERNEL),
          "dilations": list(nam_lite.nam_pack.DILATION),
          "activation": [{"type": "LeakyReLU", "negative_slope": 0.01}] * 23, "gating_mode": ["none"] * 23}
    lc.update(layer)
    m = {"architecture": "WaveNet", "config": {"layers": [lc]}, "weights": list(weights), "sample_rate": 48000}
    if slimmable:
        big = {"architecture": "WaveNet", "config": {"layers": [dict(lc, channels=8)]}, "weights": [0.0]}
        m = {"architecture": "SlimmableContainer", "config": {"submodels": [{"model": big}, {"model": m}]}}
    if metadata is not None:
        m["metadata"] = metadata
    return json.dumps(m)


@pytest.fixture(scope="session")
def weights():
    return nam_lite.placeholder()


@pytest.fixture
def nam_file(tmp_path, weights):
    """make(weights=None, name="m.nam", **options) -> path of a .nam written from nam_json()."""
    def make(w=None, name="m.nam", **kw):
        p = tmp_path / name
        p.write_text(nam_json(weights if w is None else w, **kw))
        return p
    return make


@pytest.fixture
def m4emu():
    """tests/m4emu.py, or a skip without unicorn; importing it here rather than at the top keeps a file's other tests running."""
    pytest.importorskip("unicorn", reason="no unicorn (pip install unicorn)")
    import m4emu
    return m4emu


def pytest_collection_modifyitems(config, items):
    """Upstream NAM A2 Lite tests (marked nam) are skipped unless the -m expression names nam, e.g. pytest -m nam."""
    if re.search(r"\bnam\b", config.getoption("markexpr") or ""):
        return
    skip = pytest.mark.skip(reason="upstream NAM test: run with -m nam")
    for item in items:
        if "nam" in item.keywords:
            item.add_marker(skip)
