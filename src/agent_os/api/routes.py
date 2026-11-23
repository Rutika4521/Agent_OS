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
from sdk.agent import AgentContext

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
        # Demo components
        self.supervisor        = None
        self.demo_running      = False
        self.demo_status       = "idle"   # idle | running | done | error


_ks = KernelState()


def set_kernel_state(process_manager, event_manager, metrics_collector, ipc_manager):
    _ks.process_manager   = process_manager
    _ks.event_manager     = event_manager
    _ks.metrics_collector = metrics_collector
    _ks.ipc_manager       = ipc_manager


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
        await pm.cancel(pid)
        return {"status": "cancelled", "process_id": pid}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/processes/{pid}/terminate", tags=["Processes"])
async def terminate_process(pid: int):
    pm = _get_pm()
    try:
        await pm.terminate(pid)
        return {"status": "terminated", "process_id": pid}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/processes/{pid}/pause", tags=["Processes"])
async def pause_process(pid: int):
    pm = _get_pm()
    try:
        await pm.pause(pid)
        return {"status": "paused", "process_id": pid}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/processes/{pid}/resume", tags=["Processes"])
async def resume_process(pid: int):
    pm = _get_pm()
    try:
        await pm.resume(pid)
        return {"status": "resumed", "process_id": pid}
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
    events = await _ks.event_manager.get_history(limit=limit)
    if event_type:
        events = [e for e in events if e.event_type.value == event_type]
    if process_id is not None:
        events = [e for e in events if e.process_id == process_id]
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
    """Background task: spawn & run the full demo inside the live kernel."""
    _ks.demo_status = "running"
    try:
        _ROOT = Path(__file__).resolve().parents[3]
        _DEMO = _ROOT / "examples" / "demo"
        if str(_DEMO) not in sys.path:
            sys.path.insert(0, str(_DEMO))

        from agents.orchestrator import OrchestratorAgent
        from agents.researcher   import ResearchAgent
        from agents.analyst      import AnalystAgent
        from agents.writer       import WriterAgent
        from agents.fault_agent  import FaultAgent
        from agents.monitor      import MonitorAgent
        from agent_os.kernel.state_machine import WaitReason
        from agent_os.supervisor.failure   import FailureType

        pm  = _ks.process_manager
        ipc = _ks.ipc_manager
        sup = _ks.supervisor

        pid_map: dict[str, int] = {}

        # Instantiate agents
        _orch  = OrchestratorAgent(ipc, pid_map)
        _res   = ResearchAgent(ipc, pid_map)
        _ana   = AnalystAgent(ipc, pid_map)
        _wri   = WriterAgent(ipc)
        _flt   = FaultAgent()
        _mon   = MonitorAgent(pm)

        # Spawn
        p_orch = await pm.spawn(_orch, name="Orchestrator", priority=10)
        p_res  = await pm.spawn(_res,  name="Researcher",   priority=8)
        p_ana  = await pm.spawn(_ana,  name="Analyst",      priority=7)
        p_wri  = await pm.spawn(_wri,  name="Writer",       priority=6)
        p_flt  = await pm.spawn(_flt,  name="FaultAgent",   priority=5, restart_policy="N_TIMES")
        p_mon  = await pm.spawn(_mon,  name="Monitor",      priority=3)

        pid_map["researcher"] = p_res.process_id
        pid_map["analyst"]    = p_ana.process_id
        pid_map["writer"]     = p_wri.process_id
        pid_map["monitor"]    = p_mon.process_id

        # Run loop — priority-ordered, with supervisor integration
        max_ticks = 300
        ticks = 0
        while ticks < max_ticks:
            ready = await pm.list(state=ProcessState.READY)
            if not ready:
                alive = []
                for s in (ProcessState.RUNNING, ProcessState.WAITING, ProcessState.BLOCKED):
                    alive.extend(await pm.list(state=s))
                if not alive:
                    break

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
                    error = result.error or "Agent reported failure"
                    await sup.handle_failure(pid, FailureType.AGENT_EXCEPTION, error)
                elif result.status in (StepStatus.WAIT, StepStatus.YIELD):
                    await pm.set_state(pid, ProcessState.WAITING, wait_reason=WaitReason.IPC)
                    await pm.set_state(pid, ProcessState.READY)
                else:
                    await pm.set_state(pid, ProcessState.READY)

                ticks += 1

            await asyncio.sleep(0.08)   # small delay so UI polling can see mid-run states

        _ks.demo_status = "done"
        print("[Agent-OS Demo] Pipeline complete.")

    except Exception as e:
        _ks.demo_status = "error"
        print(f"[Agent-OS Demo] Error: {e}")
        raise


@router.post("/demo/run", tags=["Demo"])
async def run_demo(background_tasks: BackgroundTasks):
    """
    Trigger the Research Intelligence Pipeline demo.
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
    return {"status": "reset", "message": "All processes cleared. Ready to run demo again."}
