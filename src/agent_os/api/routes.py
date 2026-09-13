from typing import Any, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sdk.agent import Agent, AgentContext
from agent_os.kernel.state_machine import StepStatus, AgentStepResult
from agent_os.kernel.process_manager import ProcessNotFound

router = APIRouter()

class KernelState:
    def __init__(self):
        self.process_manager = None
        self.event_manager = None
        self.metrics_collector = None
        self.ipc_manager = None

_kernel_state = KernelState()

def set_kernel_state(process_manager, event_manager, metrics_collector, ipc_manager):
    _kernel_state.process_manager = process_manager
    _kernel_state.event_manager = event_manager
    _kernel_state.metrics_collector = metrics_collector
    _kernel_state.ipc_manager = ipc_manager

class ProcessCreateReq(BaseModel):
    name: Optional[str] = None

class MessageSendReq(BaseModel):
    payload: Any
    message_type: str = "DATA"

class NoOpAgent(Agent):
    async def step(self, context: AgentContext) -> AgentStepResult:
        return AgentStepResult(status=StepStatus.COMPLETED)

def _get_pm():
    if not _kernel_state.process_manager:
        raise HTTPException(status_code=500, detail="Kernel not initialized")
    return _kernel_state.process_manager

@router.post("/processes")
async def create_process(req: ProcessCreateReq):
    pm = _get_pm()
    agent = NoOpAgent()
    pid = await pm.create_process(agent, name=req.name)
    process = await pm.get_process(pid)
    return {"process_id": pid, "name": process.name, "state": process.state_machine.state.name}

@router.get("/processes")
async def list_processes():
    pm = _get_pm()
    if hasattr(pm, 'list_processes'):
        processes = await pm.list_processes()
    else:
        # fallback if process_table is exposed
        processes = pm.process_table.get_all()
    
    return [
        {
            "process_id": p.process_id,
            "name": p.name,
            "state": p.state_machine.state.name,
            "priority": p.priority,
            "weight": p.weight
        } for p in processes
    ]

@router.get("/processes/{pid}")
async def get_process(pid: int):
    pm = _get_pm()
    try:
        p = await pm.get_process(pid)
        return {
            "process_id": p.process_id,
            "name": p.name,
            "state": p.state_machine.state.name,
            "priority": p.priority,
            "weight": p.weight,
            "resource_usage": p.resource_usage.to_dict() if hasattr(p, 'resource_usage') else {},
            "creation_time": getattr(p, 'creation_time', None)
        }
    except ProcessNotFound:
        raise HTTPException(status_code=404, detail="Process not found")

@router.post("/processes/{pid}/cancel")
async def cancel_process(pid: int):
    pm = _get_pm()
    try:
        await pm.cancel_process(pid)
        return {"status": "cancelling"}
    except ProcessNotFound:
        raise HTTPException(status_code=404, detail="Process not found")

@router.post("/processes/{pid}/terminate")
async def terminate_process(pid: int):
    pm = _get_pm()
    try:
        await pm.terminate_process(pid)
        return {"status": "terminated"}
    except ProcessNotFound:
        raise HTTPException(status_code=404, detail="Process not found")

@router.post("/processes/{pid}/pause")
async def pause_process(pid: int):
    pm = _get_pm()
    try:
        await pm.pause_process(pid)
        return {"status": "paused"}
    except ProcessNotFound:
        raise HTTPException(status_code=404, detail="Process not found")

@router.post("/processes/{pid}/resume")
async def resume_process(pid: int):
    pm = _get_pm()
    try:
        await pm.resume_process(pid)
        return {"status": "resumed"}
    except ProcessNotFound:
        raise HTTPException(status_code=404, detail="Process not found")

@router.post("/processes/{pid}/messages")
async def send_message(pid: int, req: MessageSendReq):
    if not _kernel_state.ipc_manager:
        raise HTTPException(status_code=500, detail="IPC Manager not configured")
    try:
        # system process sender = 0
        await _kernel_state.ipc_manager.send_message(
            sender_pid=0,
            receiver_pid=pid,
            payload=req.payload,
            message_type=req.message_type
        )
        return {"status": "sent"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/processes/{pid}/messages")
async def get_messages(pid: int):
    if not _kernel_state.ipc_manager:
        raise HTTPException(status_code=500, detail="IPC Manager not configured")
    try:
        messages = await _kernel_state.ipc_manager.get_messages(pid)
        return [{"sender_pid": m.sender_pid, "message_type": m.message_type, "payload": m.payload} for m in messages]
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/metrics")
async def get_metrics():
    if not _kernel_state.metrics_collector:
        raise HTTPException(status_code=500, detail="Metrics collector not configured")
    return _kernel_state.metrics_collector.get_all_metrics()

@router.get("/events")
async def get_events(
    event_type: Optional[str] = None,
    process_id: Optional[int] = None,
    limit: int = Query(100, ge=1)
):
    if not _kernel_state.event_manager:
        raise HTTPException(status_code=500, detail="Event manager not configured")
    
    events = await _kernel_state.event_manager.get_history(limit=limit)
    if event_type:
        events = [e for e in events if e.event_type.name == event_type or e.event_type.value == event_type]
    if process_id is not None:
        events = [e for e in events if e.process_id == process_id]
    
    return events

@router.get("/health")
async def health_check():
    pm = _kernel_state.process_manager
    count = 0
    if pm:
        if hasattr(pm, 'list_processes'):
            count = len(await pm.list_processes())
        else:
            count = len(pm.process_table.get_all())
    return {"status": "healthy", "process_count": count}
