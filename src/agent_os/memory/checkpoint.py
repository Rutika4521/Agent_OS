"""Agent-OS Memory — Checkpointing."""
import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from agent_os.kernel.state_machine import ProcessState
from agent_os.metrics.events import EventManager, EventType

@dataclass
class Checkpoint:
    checkpoint_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    process_id: int = 0
    process_state: ProcessState = ProcessState.CREATED
    context_id: str = ""
    context_version: int = 0
    resource_usage: dict[str, Any] = field(default_factory=dict)
    agent_state: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

class CheckpointManager:
    def __init__(self, event_manager: EventManager | None = None):
        self._checkpoints: dict[str, Checkpoint] = {}
        self._event_manager = event_manager
    
    async def create(
        self,
        process_id: int,
        process_state: ProcessState,
        context_id: str = "",
        context_version: int = 0,
        resource_usage: dict | None = None,
        agent_state: dict | None = None,
    ) -> Checkpoint:
        checkpoint = Checkpoint(
            process_id=process_id,
            process_state=process_state,
            context_id=context_id,
            context_version=context_version,
            resource_usage=resource_usage or {},
            agent_state=agent_state or {},
        )
        self._checkpoints[checkpoint.checkpoint_id] = checkpoint
        if self._event_manager:
            await self._event_manager.emit(
                EventType.CHECKPOINT_CREATED,
                process_id=process_id,
                metadata={"checkpoint_id": checkpoint.checkpoint_id},
            )
        return checkpoint
    
    async def restore(self, checkpoint_id: str) -> Checkpoint | None:
        return self._checkpoints.get(checkpoint_id)
    
    async def list_for_process(self, process_id: int) -> list[Checkpoint]:
        return [c for c in self._checkpoints.values() if c.process_id == process_id]
