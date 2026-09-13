"""
Agent-OS Kernel — Process Table

Centralized process registry (§18).
Conceptually similar to an OS process table: PID -> AgentProcess.
"""

from __future__ import annotations

import asyncio
from typing import Iterator

from agent_os.kernel.agent_process import AgentProcess
from agent_os.kernel.state_machine import ProcessState


class ProcessTable:
    """
    Centralized process table mapping PID to AgentProcess (§18).

    Supports lookup, insertion, removal, iteration,
    runnable process retrieval, and state-based filtering.
    Concurrent access is protected with an asyncio Lock.
    """

    def __init__(self):
        self._processes: dict[int, AgentProcess] = {}
        self._next_pid: int = 1
        self._lock = asyncio.Lock()

    async def allocate_pid(self) -> int:
        """Allocate the next available PID."""
        async with self._lock:
            pid = self._next_pid
            self._next_pid += 1
            return pid

    async def insert(self, process: AgentProcess) -> None:
        """Insert a process into the table."""
        async with self._lock:
            if process.process_id in self._processes:
                raise ValueError(
                    f"Process with PID {process.process_id} already exists"
                )
            self._processes[process.process_id] = process

    async def remove(self, process_id: int) -> AgentProcess | None:
        """Remove and return a process from the table."""
        async with self._lock:
            return self._processes.pop(process_id, None)

    async def get(self, process_id: int) -> AgentProcess | None:
        """Look up a process by PID."""
        async with self._lock:
            return self._processes.get(process_id)

    async def list_all(self) -> list[AgentProcess]:
        """Return all processes."""
        async with self._lock:
            return list(self._processes.values())

    async def get_by_state(self, state: ProcessState) -> list[AgentProcess]:
        """Return all processes in the given state."""
        async with self._lock:
            return [
                p for p in self._processes.values()
                if p.state == state
            ]

    async def get_runnable(self) -> list[AgentProcess]:
        """Return all READY processes eligible for scheduling."""
        return await self.get_by_state(ProcessState.READY)

    async def get_active(self) -> list[AgentProcess]:
        """Return all processes in active (non-terminal) states."""
        async with self._lock:
            terminal = {
                ProcessState.COMPLETED,
                ProcessState.CANCELLED,
                ProcessState.TERMINATED,
            }
            return [
                p for p in self._processes.values()
                if p.state not in terminal
            ]

    async def count(self) -> int:
        """Return total number of registered processes."""
        async with self._lock:
            return len(self._processes)

    async def count_by_state(self, state: ProcessState) -> int:
        """Return count of processes in the given state."""
        async with self._lock:
            return sum(
                1 for p in self._processes.values()
                if p.state == state
            )

    async def get_children(self, parent_pid: int) -> list[AgentProcess]:
        """Return all children of a given parent process."""
        async with self._lock:
            return [
                p for p in self._processes.values()
                if p.parent_process_id == parent_pid
            ]

    async def count_children(self, parent_pid: int) -> int:
        """Return number of children for a parent process."""
        async with self._lock:
            return sum(
                1 for p in self._processes.values()
                if p.parent_process_id == parent_pid
            )
