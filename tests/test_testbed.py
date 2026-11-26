"""
Runs the full multi-agent testbed (testbed/) and turns every scenario into a test,
once on the testbed driver and once on the native sdk.Kernel.run() loop.

Known kernel bugs are xfail(strict=True): when someone fixes the bug the test
XPASSes and fails the suite, prompting removal of the marker.
"""
import asyncio
import sys
from pathlib import Path

import pytest

TESTBED = Path(__file__).resolve().parents[1] / "testbed"
sys.path.insert(0, str(TESTBED))

from kernel import TestbedKernel  # noqa: E402
from native import run_native  # noqa: E402
from runner import run_testbed  # noqa: E402
from scenarios import SCENARIOS  # noqa: E402

KNOWN_BUGS: dict[str, str] = {}   # scenario id -> reason (none open)


def _run(runtime: str) -> dict:
    if runtime == "native":
        _, rows = asyncio.run(run_native())
        return {r[0]: r[4] for r in rows}
    done = asyncio.run(run_testbed(TestbedKernel(verbose=False)))
    return {s.id: s.checks for s in done}


@pytest.fixture(scope="module", params=["driver", "native"])
def results(request):
    return _run(request.param)


@pytest.mark.parametrize(
    "sid",
    [pytest.param(s.id, id=f"{s.id}-{s.title}",
                  marks=[pytest.mark.xfail(reason=KNOWN_BUGS[s.id], strict=True)] if s.id in KNOWN_BUGS else [])
     for s in SCENARIOS],
)
def test_scenario(results, sid):
    failed = [f"{c.desc} ({c.evidence})" for c in results[sid] if not c.ok]
    assert not failed, "; ".join(failed)
