"""
Agent-OS Kernel — Process Manager

Manages the full lifecycle of agent processes (§16-§17).
All process lifecycle modifications pass through this manager.
"""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Any

from agent_os.config.settings import Settings, get_settings
from agent_os.kernel.agent_process import AgentProcess
from agent_os.kernel.process_table import ProcessTable
from agent_os.kernel.state_machine import (
    InvalidStateTransition,
    ProcessState,
    StateMachine,
    WaitReason,
)
from agent_os.metrics.events import EventManager, EventType
from agent_os.resources.quota import ResourceLimits
from agent_os.resources.usage import ResourceUsage


class ProcessLimitReached(Exception):
    """Raised when the global or per-parent process limit is reached."""
    pass


class ProcessNotFound(Exception):
    """Raised when a requested process does not exist."""
    pass


class ProcessManager:
    """
    Manages process lifecycle (§16-§17).

    Provides spawn, get, list, set_state, cancel, terminate,
    pause, resume, and remove operations.

    The application does not manually allocate PIDs or register processes.
    """

    def __init__(
        self,
        process_table: ProcessTable,
        event_manager: EventManager,
        settings: Settings | None = None,
    ):
        self._table = process_table
        self._events = event_manager
        self._settings = settings or get_settings()

    @property
    def process_table(self) -> ProcessTable:
        return self._table

    async def spawn(
        self,
        agent: Any,
        *,
        name: str = "",
        priority: int | None = None,
        weight: int | None = None,
        resource_limits: ResourceLimits | None = None,
        capabilities: list[str] | None = None,
        parent_process_id: int | None = None,
        restart_policy: str | None = None,
    ) -> AgentProcess:
        """
        Create and register a new agent process (§16).

        Flow:
            Validate agent → Allocate PID → Load OS defaults →
            Apply optional overrides → Create AgentProcess →
            Register process → Emit PROCESS_CREATED → Set READY

        Args:
            agent: An object implementing the Agent protocol.
            name: Optional process name.
            priority: Override default priority.
            weight: Override default weight.
            resource_limits: Override default resource limits.
            capabilities: Override default capabilities.
            parent_process_id: Parent process PID for hierarchy.
            restart_policy: Override default restart policy.

        Returns:
            The created AgentProcess in READY state.

        Raises:
            ProcessLimitReached: When global or parent limit is exceeded.
            TypeError: When agent doesn't implement the required interface.
        """
        defaults = self._settings.process_defaults

        # Check global process limit
        total = await self._table.count()
        if total >= self._settings.system.max_processes:
            raise ProcessLimitReached(
                f"Global process limit reached: {self._settings.system.max_processes}"
            )

        # Check parent child limit
        if parent_process_id is not None:
            parent = await self._table.get(parent_process_id)
            if parent is not None:
                child_count = await self._table.count_children(parent_process_id)
                if child_count >= parent.resource_limits.child_process_limit:
                    raise ProcessLimitReached(
                        f"Child process limit reached for PID {parent_process_id}: "
                        f"{parent.resource_limits.child_process_limit}"
                    )

        # Validate agent has step method
        if not hasattr(agent, 'step') or not callable(getattr(agent, 'step')):
            raise TypeError(
                "Agent must implement the Agent protocol with an async step() method"
            )

        # Allocate PID
        pid = await self._table.allocate_pid()

        # Build resource limits from defaults + overrides
        if resource_limits is None:
            resource_limits = ResourceLimits.from_config(defaults.resources)

        # Create process with defaults + overrides
        process = AgentProcess(
            process_id=pid,
            agent=agent,
            name=name or f"process-{pid}",
            state=ProcessState.CREATED,
            priority=priority if priority is not None else defaults.priority,
            weight=weight if weight is not None else defaults.weight,
            resource_limits=resource_limits,
            resource_usage=ResourceUsage(),
            capabilities=capabilities if capabilities is not None else list(self._settings.security.default_capabilities),
            parent_process_id=parent_process_id,
            restart_policy=restart_policy or defaults.restart_policy,
            creation_time=time.time(),
        )

        # Register in table
        await self._table.insert(process)

        # Emit creation event
        await self._events.emit(
            EventType.PROCESS_CREATED,
            process_id=pid,
            metadata={"name": process.name, "priority": process.priority},
        )

        # Transition to READY
        await self.set_state(pid, ProcessState.READY)

        return process

    async def get(self, process_id: int) -> AgentProcess:
        """
        Get a process by PID.

        Raises:
            ProcessNotFound: If the process does not exist.
        """
        process = await self._table.get(process_id)
        if process is None:
            raise ProcessNotFound(f"Process {process_id} not found")
        return process

    async def list(
        self,
        state: ProcessState | None = None,
    ) -> list[AgentProcess]:
        """List all processes, optionally filtered by state."""
        if state is not None:
            return await self._table.get_by_state(state)
        return await self._table.list_all()

    async def set_state(
        self,
        process_id: int,
        new_state: ProcessState,
        wait_reason: WaitReason | None = None,
    ) -> None:
        """
        Transition a process to a new state.

        Validates the transition through the state machine.
        Emits the appropriate event.

        Raises:
            ProcessNotFound: If the process does not exist.
            InvalidStateTransition: If the transition is invalid.
        """
        process = await self.get(process_id)
        old_state = process.state

        # Validate transition
        StateMachine.transition(old_state, new_state)

        # Update process
        process.state = new_state
        process.waiting_for = wait_reason if new_state in (
            ProcessState.WAITING, ProcessState.BLOCKED
        ) else None

        # Track timestamps
        now = time.time()
        if new_state == ProcessState.RUNNING:
            process.start_time = now
            process.last_scheduled_time = now
            process.ready_since = None
        elif new_state == ProcessState.READY:
            process.ready_since = now
        elif new_state in (ProcessState.COMPLETED, ProcessState.CANCELLED):
            process.completion_time = now

        # Map state to event type
        state_event_map = {
            ProcessState.READY: EventType.PROCESS_READY,
            ProcessState.RUNNING: EventType.PROCESS_STARTED,
            ProcessState.WAITING: EventType.PROCESS_WAITING,
            ProcessState.BLOCKED: EventType.PROCESS_BLOCKED,
            ProcessState.COMPLETED: EventType.PROCESS_COMPLETED,
            ProcessState.FAILED: EventType.PROCESS_FAILED,
            ProcessState.CANCELLED: EventType.PROCESS_CANCELLED,
            ProcessState.TERMINATED: EventType.PROCESS_TERMINATED,
        }

        event_type = state_event_map.get(new_state)
        if event_type:
            await self._events.emit(
                event_type,
                process_id=process_id,
                metadata={
                    "old_state": old_state.value,
                    "new_state": new_state.value,
                    "wait_reason": wait_reason.value if wait_reason else None,
                },
            )

    async def cancel(self, process_id: int) -> None:
        """
        Initiate cooperative cancellation of a process (§50).

        For RUNNING/WAITING/BLOCKED: → CANCELLING → CANCELLED
        For READY: → RUNNING → CANCELLING → CANCELLED
        """
        process = await self.get(process_id)

        if process.state == ProcessState.READY:
            # READY can only transition to RUNNING first
            await self.set_state(process_id, ProcessState.RUNNING)
            await self.set_state(process_id, ProcessState.CANCELLING)
            await self.set_state(process_id, ProcessState.CANCELLED)
        elif process.state in (
            ProcessState.RUNNING,
            ProcessState.WAITING,
            ProcessState.BLOCKED,
        ):
            await self.set_state(process_id, ProcessState.CANCELLING)
            await self.set_state(process_id, ProcessState.CANCELLED)
        elif process.state == ProcessState.CANCELLING:
            await self.set_state(process_id, ProcessState.CANCELLED)

    async def terminate(self, process_id: int) -> None:
        """
        Terminate a process, moving to TERMINATED (§50, §62).

        Can be called from COMPLETED, CANCELLED, FAILED,
        WAITING, or BLOCKED states.
        """
        process = await self.get(process_id)

        terminable = {
            ProcessState.COMPLETED,
            ProcessState.CANCELLED,
            ProcessState.FAILED,
            ProcessState.WAITING,
            ProcessState.BLOCKED,
        }

        if process.state in terminable:
            await self.set_state(process_id, ProcessState.TERMINATED)
        elif process.state in (ProcessState.READY, ProcessState.RUNNING):
            # Must cancel first
            await self.cancel(process_id)
            await self.set_state(process_id, ProcessState.TERMINATED)

    async def pause(self, process_id: int) -> None:
        """
        Pause a running process by moving it to WAITING.

        Only RUNNING processes can be paused.
        """
        process = await self.get(process_id)
        if process.state == ProcessState.RUNNING:
            await self.set_state(
                process_id,
                ProcessState.WAITING,
                wait_reason=WaitReason.SLEEP,
            )

    async def resume(self, process_id: int) -> None:
        """
        Resume a waiting/blocked process to READY.
        """
        process = await self.get(process_id)
        if process.state in (ProcessState.WAITING, ProcessState.BLOCKED):
            await self.set_state(process_id, ProcessState.READY)

    async def remove(self, process_id: int) -> AgentProcess | None:
        """
        Remove a terminated process from the table.

        Only TERMINATED processes can be removed.

        Raises:
            ValueError: If the process is not terminated.
        """
        process = await self._table.get(process_id)
        if process is None:
            return None
        if process.state != ProcessState.TERMINATED:
            raise ValueError(
                f"Cannot remove process {process_id} in state {process.state.value}. "
                "Only TERMINATED processes can be removed."
            )
        return await self._table.remove(process_id)
