"""
Agent-OS Testbed — live dashboard mode.

    python testbed/run_server.py          # Terminal 1  (API on :8000)
    cd frontend && npm run dev            # Terminal 2  (UI on :3000)

Click ▶ Run Demo in the UI. The full testbed runs inside the live kernel (paced so
you can watch states change); the scorecard is printed in Terminal 1 and served at
GET /testbed/report.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

from kernel import TestbedKernel  # noqa: E402  (also puts src/ and repo root on sys.path)
from runner import report, run_testbed  # noqa: E402

from agent_os.api.app import app  # noqa: E402
from agent_os.api.routes import _ks, set_demo_runner  # noqa: E402

_last_report: dict = {"status": "not run yet — click ▶ Run Demo"}


async def _testbed_pipeline() -> None:
    global _last_report
    _ks.demo_status = "running"
    try:
        kernel = TestbedKernel(event_manager=_ks.event_manager,
                               process_manager=_ks.process_manager,
                               ipc_manager=_ks.ipc_manager,
                               pace=0.02)
        t0 = time.time()
        results = await run_testbed(kernel)
        _last_report = report(kernel, results, time.time() - t0)
        _ks.demo_status = "done"
    except Exception as exc:  # noqa: BLE001
        _ks.demo_status = "error"
        _last_report = {"status": "error", "error": repr(exc)}
        print(f"[Testbed] ERROR: {exc!r}")
        raise


set_demo_runner(_testbed_pipeline)


@app.get("/testbed/report", tags=["Testbed"])
async def testbed_report():
    return _last_report


if __name__ == "__main__":
    import uvicorn

    print("=" * 64)
    print("  Agent-OS Testbed Server — 32 scenarios, ~60 agents")
    print("  UI: http://localhost:3000  →  ▶ Run Demo")
    print("  Scorecard JSON: http://localhost:8000/testbed/report")
    print("=" * 64)
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
