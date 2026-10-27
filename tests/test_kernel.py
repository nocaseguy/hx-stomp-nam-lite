"""The kernel in the SHARC simulator, one test per nam_lite.KernelCheck step.

The steps share one simulator run (~20 s): each carries on from the state the
ones before it left, so a failed step skips the rest. To test a new kernel
behaviour first, add a method to KernelCheck and its name to STEPS: it shows
up here as a failing test until the kernel does it.
"""
import pytest

import nam_lite

pytestmark = pytest.mark.slow


@pytest.fixture(scope="session")
def kernel_run(weights):
    asm, _ = nam_lite.build(weights)
    k = nam_lite.KernelCheck(asm, weights)
    results = {}
    for name in k.STEPS:
        try:
            getattr(k, name)()
            results[name] = None
        except nam_lite.CheckFailed as e:
            results[name] = str(e)
            break
    return results


@pytest.mark.parametrize("step", nam_lite.KernelCheck.STEPS)
def test_step(kernel_run, step):
    if step not in kernel_run:
        pytest.skip("an earlier step failed")
    assert kernel_run[step] is None, kernel_run[step]
