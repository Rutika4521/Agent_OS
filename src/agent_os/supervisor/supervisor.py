"""
Agent-OS Supervisor — Process supervision and failure handling (§45-§49).
"""

from __future__ import annotations

from typing import Any

from agent_os.kernel.process_manager import ProcessManager, ProcessNotFound
from agent_os.kernel.state_machine import ProcessState
from agent_os.metrics.events import EventManager, EventType
from agent_os.supervisor.failure import FailureRecord, FailureType
from agent_os.supervisor.restart import RestartManager, RestartPolicy


class Supervisor:
    """
    Supervises agent processes: detects failures, classifies them,
    and applies restart policies (§45-§49).
    """

    def __init__(
        self,
        process_manager: ProcessManager,
        restart_manager: RestartManager,
        event_manager: EventManager,
        checkpoint_manager: Any = None,
    ):
        self._process_manager = process_manager
        self._restart_manager = restart_manager
        self._event_manager = event_manager
        self._checkpoint_manager = checkpoint_manager
        self._failure_records: list[FailureRecord] = []

    async def handle_failure(
        self,
        process_id: int,
        failure_type: FailureType,
        error: str,
        context: dict | None = None,
    ) -> None:
        """
        Handle a process failure (§48).

        1. Create FailureRecord
        2. Record failure in restart_manager
        3. Check if restart is allowed
        4. If yes: restart (FAILED -> RESTARTING -> READY)
        5. If no: terminate (FAILED -> TERMINATED)
        """
        record = FailureRecord(
            process_id=process_id,
            failure_type=failure_type,
            error_message=error,
            context=context or {},
        )
        self._failure_records.append(record)
        self._restart_manager.record_failure(process_id)

        try:
            process = await self._process_manager.get(process_id)
        except ProcessNotFound:
            return

        # Determine restart policy
        policy_str = process.restart_policy
        try:
            policy = RestartPolicy(policy_str)
        except ValueError:
            policy = RestartPolicy.NEVER

        can_restart = self._restart_manager.can_restart(
            process_id, policy, process.restart_count
        )

        process.failure_count += 1

        if can_restart:
            await self._event_manager.emit(
                EventType.RESTART_STARTED,
                process_id=process_id,
                metadata={"failure_type": failure_type.value, "restart_count": process.restart_count},
            )

            if process.state == ProcessState.FAILED:
                await self._process_manager.set_state(process_id, ProcessState.RESTARTING)
                await self._process_manager.set_state(process_id, ProcessState.READY)

            process.restart_count += 1

            await self._event_manager.emit(
                EventType.RESTART_COMPLETED,
                process_id=process_id,
                metadata={"restart_count": process.restart_count},
            )
        else:
            if process.state == ProcessState.FAILED:
                await self._process_manager.set_state(process_id, ProcessState.TERMINATED)

    async def restart(self, process_id: int) -> bool:
        """Attempt to restart a failed process. Returns True if restarted."""
        try:
            process = await self._process_manager.get(process_id)
        except ProcessNotFound:
            return False

        policy_str = process.restart_policy
        try:
            policy = RestartPolicy(policy_str)
        except ValueError:
            return False

        if not self._restart_manager.can_restart(process_id, policy, process.restart_count):
            return False

        process.failure_count += 1
        await self._event_manager.emit(
            EventType.RESTART_STARTED, process_id=process_id
        )

        if process.state == ProcessState.FAILED:
            await self._process_manager.set_state(process_id, ProcessState.RESTARTING)
            await self._process_manager.set_state(process_id, ProcessState.READY)

        process.restart_count += 1
        await self._event_manager.emit(
            EventType.RESTART_COMPLETED, process_id=process_id
        )
        return True

    async def get_failures(self, process_id: int | None = None) -> list[FailureRecord]:
        """Get failure records, optionally filtered by process ID."""
        if process_id is None:
            return list(self._failure_records)
        return [r for r in self._failure_records if r.process_id == process_id]
