"""
Runs the Orbital Research Lab (showcase_full/) on the native agent_os.Kernel
and turns every scenario into a test.

Scenarios that document a known Agent-OS bug are xfail(strict=True): once the
bug is fixed they XPASS, the suite fails, and the marker should be removed.
"""
import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

SHOWCASE = Path(__file__).resolve().parents[1] / "showcase_full"
sys.path.insert(0, str(SHOWCASE))

from lab.harness import SCENARIOS  # noqa: E402
import lab.missions  # noqa: E402,F401

# Load showcase_full/run.py by path: the repo root also has a run.py.
_spec = importlib.util.spec_from_file_location("showcase_full_run", SHOWCASE / "run.py")
_runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_runner)
run_all = _runner.run_all


@pytest.fixture(scope="module")
def results():
    missions = asyncio.run(run_all())
    return {s.id: s for r in missions for s in r.scenarios}


@pytest.mark.parametrize(
    "sid",
    [pytest.param(s.id, id=f"{s.id}-{s.title}",
                  marks=[pytest.mark.xfail(reason=s.known_bug, strict=True)] if s.known_bug else [])
     for s in SCENARIOS],
)
def test_scenario(results, sid):
    failed = [f"{c.desc} ({c.evidence})" for c in results[sid].checks if not c.ok]
    assert results[sid].checks and not failed, "; ".join(failed)
