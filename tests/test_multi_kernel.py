"""The multi-block kernel (tools/sharc/nam_multi.py) in the SHARC simulator, with its
model of chained external-port DMA: each block bit for bit with nam_a2.asm on its own
model and input trim, model changes, takeover of a removed block's slot, DMA failure."""
import pytest

import nam_multi

pytestmark = pytest.mark.slow


@pytest.mark.parametrize("slots", [3, 2])
def test_kernel(weights, slots):
    asm, lay = nam_multi.build(weights, slots)
    ok, res, _ = nam_multi.check(asm, lay, weights)
    assert ok, res
    assert res["worst"] <= 36000
