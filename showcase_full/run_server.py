"""
Orbital Research Lab — live dashboard server.

    python showcase_full/run_server.py        # Terminal 1  (API on :8000)
    cd frontend && npm run dev                # Terminal 2  (UI on :3000)

Click ▶ Run Demo: all 9 missions (~110 agents, 62 scenarios) run on native
agent_os.Kernel instances inside this server, paced so you can watch them.
Live scorecard: GET http://localhost:8000/demo/report
(`python run.py server` runs the same thing — this is the default demo.)
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for p in (HERE.parent / "src", HERE.parent):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

from agent_os.api.app import app  # noqa: E402

if __name__ == "__main__":
    import uvicorn

    print("=" * 66)
    print("  Agent-OS · Orbital Research Lab — 9 missions, 62 scenarios")
    print("  UI: http://localhost:3000  →  ▶ Run Demo")
    print("  Live scorecard: http://localhost:8000/demo/report")
    print("=" * 66)
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
