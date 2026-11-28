"""
Agent-OS API Routes

All REST endpoints for managing processes, IPC, events, health, and demo.
"""
import asyncio
import sys
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel

from agent_os.kernel.state_machine import StepStatus, AgentStepResult, ProcessState
from agent_os.sdk.agent import AgentContext

router = APIRouter()


# ---------------------------------------------------------------------------
# Kernel state holder — populated by app.py lifespan
# ---------------------------------------------------------------------------

class KernelState:
    def __init__(self):
        self.process_manager   = None
        self.event_manager     = None
        self.metrics_collector = None
        self.ipc_manager       = None
        self.kernel            = None   # sdk.Kernel driving these subsystems (if any)
        # Demo components
        self.supervisor        = None
        self.demo_running      = False
        self.demo_status       = "idle"   # idle | running | done | error
        self.demo_report       = None


_ks = KernelState()


def set_kernel_state(process_manager, event_manager, metrics_collector, ipc_manager, kernel=None):
    _ks.process_manager   = process_manager
    _ks.event_manager     = event_manager
    _ks.metrics_collector = metrics_collector
    _ks.ipc_manager       = ipc_manager
    _ks.kernel            = kernel


def use_kernel(kernel) -> None:
    """Point every endpoint at a booted sdk.Kernel (processes, events, IPC, operator actions)."""
    set_kernel_state(kernel.pm, kernel.events, kernel.metrics, kernel.ipc, kernel=kernel)


def set_demo_components(supervisor, ipc_manager, event_manager, process_manager):
    _ks.supervisor = supervisor


def set_demo_runner(fn):
    """Allow external apps (e.g. the showcase) to override the demo pipeline function."""
    global _run_demo_pipeline
    _run_demo_pipeline = fn


def _get_pm():
    if not _ks.process_manager:
        raise HTTPException(status_code=503, detail="Kernel not initialized.")
    return _ks.process_manager


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ProcessCreateReq(BaseModel):
    name: Optional[str] = "api-agent"
    priority: int = 5

class MessageSendReq(BaseModel):
    payload: Any
    message_type: str = "DATA"

class IPCSendReq(BaseModel):
    sender_pid: int
    receiver_pid: int
    payload: Any


# ---------------------------------------------------------------------------
# NoOp agent for API-spawned processes
# ---------------------------------------------------------------------------

class NoOpAgent:
    """A placeholder agent created via the API."""
    async def step(self, context: AgentContext) -> AgentStepResult:
        return AgentStepResult(status=StepStatus.COMPLETED, output="NoOp agent completed.")


# ---------------------------------------------------------------------------
# Process serializer
# ---------------------------------------------------------------------------

def _serialize_process(p) -> dict:
    return {
        "process_id":    p.process_id,
        "name":          p.name,
        "state":         p.state.value,
        "priority":      p.priority,
        "weight":        p.weight,
        "restart_count": p.restart_count,
        "restart_policy": p.restart_policy,
        "waiting_for":   p.waiting_for.value if p.waiting_for else None,
        "creation_time": p.creation_time,
        "resource_usage": {
            "steps":        p.resource_usage.steps,
            "total_tokens": p.resource_usage.total_tokens,
            "llm_calls":    p.resource_usage.llm_calls,
            "tool_calls":   p.resource_usage.tool_calls,
            "input_tokens": p.resource_usage.input_tokens,
            "output_tokens":p.resource_usage.output_tokens,
        },
        "resource_limits": {
            "step_limit":  p.resource_limits.step_limit,
            "token_limit": p.resource_limits.token_limit,
        },
    }


# ---------------------------------------------------------------------------
# Process endpoints
# ---------------------------------------------------------------------------

@router.get("/processes", tags=["Processes"])
async def list_processes():
    pm = _get_pm()
    return [_serialize_process(p) for p in await pm.list()]


@router.post("/processes", tags=["Processes"])
async def create_process(req: ProcessCreateReq):
    pm = _get_pm()
    proc = await pm.spawn(NoOpAgent(), name=req.name, priority=req.priority)
    return _serialize_process(proc)


@router.get("/processes/{pid}", tags=["Processes"])
async def get_process(pid: int):
    pm = _get_pm()
    try:
        p = await pm.get(pid)
        return _serialize_process(p)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Process {pid} not found")


@router.post("/processes/{pid}/cancel", tags=["Processes"])
async def cancel_process(pid: int):
    pm = _get_pm()
    try:
        if _ks.kernel is not None:
            # Kernel path: reclaim locks/memory, CANCELLED → TERMINATED, orphan policy.
            await _ks.kernel.cancel(pid)
        else:
            await pm.cancel(pid)
            await pm.terminate(pid)
        return {"status": "cancelled", "process_id": pid, "state": (await pm.get(pid)).state.value}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/processes/{pid}/terminate", tags=["Processes"])
async def terminate_process(pid: int):
    pm = _get_pm()
    try:
        if _ks.kernel is not None:
            await _ks.kernel.cancel(pid)
        else:
            await pm.terminate(pid)
        return {"status": "terminated", "process_id": pid}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/processes/{pid}/pause", tags=["Processes"])
async def pause_process(pid: int):
    pm = _get_pm()
    try:
        if _ks.kernel is not None:
            await _ks.kernel.pause(pid)
        else:
            await pm.pause(pid)
        state = (await pm.get(pid)).state.value
        if state not in ("WAITING", "BLOCKED"):
            raise HTTPException(status_code=409, detail=f"Process {pid} is {state}; it cannot be paused")
        return {"status": "paused", "process_id": pid, "state": state}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/processes/{pid}/resume", tags=["Processes"])
async def resume_process(pid: int):
    pm = _get_pm()
    try:
        if _ks.kernel is not None:
            await _ks.kernel.resume(pid)
        else:
            await pm.resume(pid)
        return {"status": "resumed", "process_id": pid, "state": (await pm.get(pid)).state.value}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# IPC endpoints
# ---------------------------------------------------------------------------

@router.post("/processes/{pid}/messages", tags=["IPC"])
async def send_message_to_pid(pid: int, req: MessageSendReq):
    if not _ks.ipc_manager:
        raise HTTPException(status_code=503, detail="IPC Manager not configured")
    try:
        msg = await _ks.ipc_manager.send(
            sender_pid=0,
            receiver_pid=pid,
            payload=req.payload,
        )
        return {"status": "sent", "message_id": msg.message_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/processes/{pid}/messages", tags=["IPC"])
async def get_messages(pid: int):
    if not _ks.ipc_manager:
        raise HTTPException(status_code=503, detail="IPC Manager not configured")
    msg = await _ks.ipc_manager.receive(pid)
    if not msg:
        return {"message": None}
    return {
        "message_id":     msg.message_id,
        "sender_pid":     msg.sender_pid,
        "receiver_pid":   msg.receiver_pid,
        "payload":        msg.payload,
        "delivery_status":msg.delivery_status,
    }


@router.post("/ipc/send", tags=["IPC"])
async def ipc_send(req: IPCSendReq):
    """Send a message between any two PIDs."""
    if not _ks.ipc_manager:
        raise HTTPException(status_code=503, detail="IPC Manager not configured")
    try:
        msg = await _ks.ipc_manager.send(
            sender_pid=req.sender_pid,
            receiver_pid=req.receiver_pid,
            payload=req.payload,
        )
        return {"status": "sent", "message_id": msg.message_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/ipc/receive/{pid}", tags=["IPC"])
async def ipc_receive(pid: int):
    """Peek at the next queued message for a PID."""
    if not _ks.ipc_manager:
        raise HTTPException(status_code=503, detail="IPC Manager not configured")
    msg = await _ks.ipc_manager.receive(pid)
    if not msg:
        return {"message": None}
    return {
        "message_id":     msg.message_id,
        "sender_pid":     msg.sender_pid,
        "receiver_pid":   msg.receiver_pid,
        "payload":        msg.payload,
        "delivery_status":msg.delivery_status,
    }


# ---------------------------------------------------------------------------
# Events & Metrics
# ---------------------------------------------------------------------------

@router.get("/events", tags=["Observability"])
async def get_events(
    event_type: Optional[str] = None,
    process_id: Optional[int] = None,
    limit: int = Query(200, ge=1, le=1000),
):
    if not _ks.event_manager:
        raise HTTPException(status_code=503, detail="Event manager not configured")
    # Filter BEFORE applying the limit, otherwise rare events (deadlocks, locks)
    # fall outside the window of the most recent N events and are never returned.
    # event_type accepts a comma-separated list, e.g. DEADLOCK_DETECTED,LOCK_ACQUIRED
    events = await _ks.event_manager.get_history(process_id=process_id)
    if event_type:
        wanted = {t.strip() for t in event_type.split(",") if t.strip()}
        events = [e for e in events if e.event_type.value in wanted]
    events = events[-limit:]
    return [
        {
            "event_id":   e.event_id,
            "event_type": e.event_type.value,
            "process_id": e.process_id,
            "timestamp":  e.timestamp,
            "metadata":   e.metadata,
        }
        for e in events
    ]


@router.get("/metrics", tags=["Observability"])
async def get_metrics():
    pm = _ks.process_manager
    if not pm:
        return {}
    procs = await pm.list()
    total_tokens = sum(p.resource_usage.total_tokens for p in procs)
    total_steps  = sum(p.resource_usage.steps for p in procs)
    total_llm    = sum(p.resource_usage.llm_calls for p in procs)
    by_state = {}
    for p in procs:
        by_state[p.state.value] = by_state.get(p.state.value, 0) + 1
    events = await _ks.event_manager.get_history(limit=1000) if _ks.event_manager else []
    return {
        "total_processes": len(procs),
        "total_tokens":    total_tokens,
        "total_steps":     total_steps,
        "total_llm_calls": total_llm,
        "total_events":    len(events),
        "by_state":        by_state,
        "demo_status":     _ks.demo_status,
    }


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@router.get("/health", tags=["System"])
async def health_check():
    pm = _ks.process_manager
    if not pm:
        return {"status": "booting", "process_count": 0, "demo_status": "idle"}
    procs = await pm.list()
    return {
        "status":        "healthy",
        "process_count": len(procs),
        "demo_status":   _ks.demo_status,
    }


# ---------------------------------------------------------------------------
# Demo endpoint — runs the full Research Intelligence Pipeline
# inside the live server kernel so the UI sees everything in real time
# ---------------------------------------------------------------------------

async def _run_demo_pipeline():
    """Background task: run the Orbital Research Lab (showcase_full/) on the live server.

    Nine missions, each on its own native agent_os.Kernel, ~110 agents and 62
    scenarios. The routes follow the run live; the scorecard is at GET /demo/report.
    """
    _ks.demo_status = "running"
    _ks.demo_report = {"status": "running", "current_mission": "booting"}
    try:
        _ROOT = Path(__file__).resolve().parents[3]
        _SHOWCASE = _ROOT / "showcase_full"
        if str(_SHOWCASE) not in sys.path:
            sys.path.insert(0, str(_SHOWCASE))
        from live import run_live

        def publish(report):
            _ks.demo_report = report

        report = await run_live(_ks, pace=0.02, publish=publish)
        _ks.demo_status = "done" if report["counts"]["FAIL"] == 0 else "error"
    except Exception as e:
        _ks.demo_status = "error"
        _ks.demo_report = {"status": "error", "error": repr(e)}
        print(f"[Agent-OS Demo] Error: {e!r}")
        raise


@router.get("/demo/report", tags=["Demo"])
async def demo_report():
    """Scorecard of the running / last demo: per-scenario outcome and evidence."""
    return _ks.demo_report or {"status": "idle"}


@router.post("/demo/run", tags=["Demo"])
async def run_demo(background_tasks: BackgroundTasks):
    """
    Trigger the Orbital Research Lab demo (showcase_full/: 9 missions, 62 scenarios).
    Runs in the background — poll /processes and /events to see live data.
    """
    if _ks.demo_status == "running":
        return {"status": "already_running", "message": "Demo is already in progress"}

    _ks.demo_status = "running"
    background_tasks.add_task(_run_demo_pipeline)
    return {
        "status":  "started",
        "message": "Demo pipeline started. Poll /processes and /events to see live data.",
    }


@router.get("/demo/status", tags=["Demo"])
async def demo_status():
    """Check whether a demo pipeline is running."""
    pm = _ks.process_manager
    procs = await pm.list() if pm else []
    return {
        "demo_status":   _ks.demo_status,
        "process_count": len(procs),
    }


@router.post("/demo/reset", tags=["Demo"])
async def reset_demo():
    """Clear all processes and event history so the demo can be re-run."""
    if _ks.demo_status == "running":
        raise HTTPException(status_code=409, detail="Demo is still running. Wait for it to finish.")

    pm  = _ks.process_manager
    em  = _ks.event_manager

    if pm:
        procs = await pm.list()
        for p in procs:
            try:
                if p.state not in (ProcessState.TERMINATED,):
                    await pm.terminate(p.process_id)
            except Exception:
                pass
        for p in procs:
            try:
                await pm.remove(p.process_id)
            except Exception:
                pass

    if em:
        await em.clear_history()

    _ks.demo_status = "idle"
    _ks.demo_report = None
    return {"status": "reset", "message": "All processes cleared. Ready to run demo again."}
