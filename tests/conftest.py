import json

import pytest

import nam_lite


def nam_json(weights, slimmable=False, **layer):
    """A .nam file's text: a 3-channel A2 Lite WaveNet (made up, no capture in the repo)."""
    lc = {"channels": nam_lite.C, "kernel_sizes": list(nam_lite.nam_pack.KERNEL),
          "dilations": list(nam_lite.nam_pack.DILATION),
          "activation": [{"type": "LeakyReLU", "negative_slope": 0.01}] * 23, "gating_mode": ["none"] * 23}
    lc.update(layer)
    m = {"architecture": "WaveNet", "config": {"layers": [lc]}, "weights": list(weights), "sample_rate": 48000}
    if slimmable:
        big = {"architecture": "WaveNet", "config": {"layers": [dict(lc, channels=8)]}, "weights": [0.0]}
        m = {"architecture": "SlimmableContainer", "config": {"submodels": [{"model": big}, {"model": m}]}}
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
