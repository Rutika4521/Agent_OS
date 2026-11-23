"""
Showcase Run-Server
===================

Starts the Agent-OS FastAPI server with the **Autonomous Incident Response**
showcase pipeline wired in as the demo handler.

When the user clicks ▶ Run Demo in the React dashboard, this server runs the
showcase agents (not the default examples/demo pipeline) so the UI sees all
7 showcase processes, their IPC messages, resource usage, and events in real time.

Usage
-----
    # Terminal 1 — start the server
    cd C:\\Users\\RUTIKA\\Desktop\\LY\\EDAI\\showcase
    python run_server.py

    # Terminal 2 — start the React UI
    cd "C:\\Users\\RUTIKA\\Desktop\\LY\\EDAI\\Agent OS\\agent-os\\frontend"
    npm run dev

    # Browser
    http://localhost:3000  →  click ▶ Run Demo
"""
from __future__ import annotations

import sys
from pathlib import Path

# ── 1. Add showcase root so 'agents' package is importable ────────────────────
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# ── 2. If NOT installed via pip, add the local agent-os sources to path ──────
#    (comment out these two lines if you've done `pip install agent-os-kernel`)
_AGENT_OS = _HERE.parent / "Agent OS" / "agent-os"
if _AGENT_OS.exists():
    _SRC = _AGENT_OS / "src"
    for p in (str(_SRC), str(_AGENT_OS)):
        if p not in sys.path:
            sys.path.insert(0, p)

# ── 3. Core agent-os imports ──────────────────────────────────────────────────
import asyncio

from agent_os.kernel.state_machine import ProcessState, StepStatus, WaitReason
from agent_os.supervisor.failure import FailureType
from agent_os.api.routes import _ks, set_demo_runner
from agent_os import AgentContext

# ── 4. Showcase agent imports ─────────────────────────────────────────────────
from agents.incident_commander import IncidentCommanderAgent
from agents.security_auditor   import SecurityAuditorAgent
from agents.bug_fixer          import BugFixerAgent
from agents.flaky_test_runner  import FlakyTestRunnerAgent
from agents.contended_workers  import ContendedWorkerA, ContendedWorkerB
from agents.telemetry          import TelemetryAgent


# ── 5. Showcase demo pipeline (injected into routes) ─────────────────────────

async def _showcase_demo_pipeline() -> None:
    """
    Runs the Autonomous Incident Response showcase agents inside the live
    Agent-OS kernel that the FastAPI server booted.

    The kernel state (_ks) is already populated by app.py's lifespan.
    We just spawn our agents into it and run the tick loop.
    UI polling (/processes, /events, /metrics) will see everything live.
    """
    _ks.demo_status = "running"
    print("[Showcase] Starting Autonomous Incident Response pipeline…")
    try:
        pm  = _ks.process_manager
        ipc = _ks.ipc_manager
        sup = _ks.supervisor

        pid_map: dict[str, int] = {}

        # ── Instantiate agents ────────────────────────────────────────────────
        commander  = IncidentCommanderAgent(ipc, pid_map)
        auditor    = SecurityAuditorAgent(ipc, pid_map)
        fixer      = BugFixerAgent(ipc, pid_map)
        flaky      = FlakyTestRunnerAgent()
        worker_a   = ContendedWorkerA()
        worker_b   = ContendedWorkerB()
        telemetry  = TelemetryAgent(pm)

        # ── Spawn into live OS process table ──────────────────────────────────
        p_cmd = await pm.spawn(commander,  name="IncidentCommander",  priority=10)
        p_aud = await pm.spawn(auditor,    name="SecurityAuditor",    priority=8)
        p_fix = await pm.spawn(fixer,      name="BugFixer",           priority=7)
        p_flk = await pm.spawn(flaky,      name="FlakyTestRunner",    priority=5, restart_policy="N_TIMES")
        p_wa  = await pm.spawn(worker_a,   name="ContendedWorkerA",   priority=6)
        p_wb  = await pm.spawn(worker_b,   name="ContendedWorkerB",   priority=6)
        p_tel = await pm.spawn(telemetry,  name="TelemetryAgent",     priority=2)

        # Fill IPC address book after PIDs are allocated
        pid_map["auditor"]   = p_aud.process_id
        pid_map["fixer"]     = p_fix.process_id
        pid_map["telemetry"] = p_tel.process_id

        print(
            f"[Showcase] Spawned 7 agents — PIDs "
            f"Commander={p_cmd.process_id}, Auditor={p_aud.process_id}, "
            f"Fixer={p_fix.process_id}, Flaky={p_flk.process_id}, "
            f"WorkerA={p_wa.process_id}, WorkerB={p_wb.process_id}, "
            f"Telemetry={p_tel.process_id}"
        )

        # ── Tick loop ─────────────────────────────────────────────────────────
        max_ticks = 400
        ticks = 0
        while ticks < max_ticks:
            ready = await pm.list(state=ProcessState.READY)
            if not ready:
                alive = []
                for s in (ProcessState.RUNNING, ProcessState.WAITING, ProcessState.BLOCKED):
                    alive.extend(await pm.list(state=s))
                if not alive:
                    break

            # Priority-descending: Commander(10) always runs before Telemetry(2)
            ready.sort(key=lambda p: p.priority, reverse=True)

            for proc in ready:
                pid = proc.process_id
                try:
                    await pm.set_state(pid, ProcessState.RUNNING)
                except Exception:
                    continue

                ctx = AgentContext(process_id=pid, data={"process": proc})
                try:
                    result = await proc.agent.step(ctx)
                except Exception as exc:
                    await pm.set_state(pid, ProcessState.FAILED)
                    await sup.handle_failure(pid, FailureType.AGENT_EXCEPTION, str(exc))
                    continue

                proc.resource_usage.steps += 1

                if result.status == StepStatus.COMPLETED:
                    await pm.set_state(pid, ProcessState.COMPLETED)
                    await pm.terminate(pid)

                elif result.status == StepStatus.FAILED:
                    await pm.set_state(pid, ProcessState.FAILED)
                    await sup.handle_failure(
                        pid, FailureType.AGENT_EXCEPTION,
                        result.error or "agent returned FAILED"
                    )

                elif result.status in (StepStatus.WAIT, StepStatus.YIELD):
                    # Agent is waiting for an IPC message — cycle back to READY
                    await pm.set_state(pid, ProcessState.WAITING, wait_reason=WaitReason.IPC)
                    await pm.set_state(pid, ProcessState.READY)

                elif result.status == StepStatus.BLOCK:
                    # Contended resource — show BLOCKED in UI, then auto-resolve
                    await pm.set_state(pid, ProcessState.WAITING, wait_reason=WaitReason.LOCK)
                    await asyncio.sleep(0.1)
                    await pm.set_state(pid, ProcessState.READY)

                else:  # CONTINUE
                    await pm.set_state(pid, ProcessState.READY)

                ticks += 1

            # Small delay so the UI's 600ms polling can observe mid-run states
            await asyncio.sleep(0.08)

        _ks.demo_status = "done"
        print(
            f"[Showcase] Pipeline complete — {ticks} ticks, "
            f"{len(await pm.list())} processes tracked."
        )

    except Exception as exc:
        _ks.demo_status = "error"
        print(f"[Showcase] Pipeline error: {exc}")
        raise


# ── 6. Register showcase pipeline with the routes module ─────────────────────
set_demo_runner(_showcase_demo_pipeline)

# ── 7. Import and start the FastAPI app ──────────────────────────────────────
from agent_os.api.app import app  # noqa: E402  (must come after sys.path setup)
import uvicorn  # noqa: E402

if __name__ == "__main__":
    print("=" * 60)
    print("  Agent-OS Showcase Server")
    print("  Autonomous Incident Response System")
    print("=" * 60)
    print("  API docs : http://localhost:8000/docs")
    print("  Health   : http://localhost:8000/health")
    print("  Demo     : POST http://localhost:8000/demo/run")
    print()
    print("  Open the React UI:  http://localhost:3000")
    print("  Then click  ▶ Run Demo  to start the showcase.")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
