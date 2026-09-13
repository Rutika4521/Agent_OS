"""
Agent-OS Scheduler — Priority Scheduler

Implements priority-based scheduling with aging support (§21).
The scheduler only sees execution metadata, never agent semantics.
"""

from __future__ import annotations

import time
from typing import List, Optional

from agent_os.kernel.agent_process import AgentProcess
from agent_os.kernel.state_machine import ProcessState
from agent_os.config.settings import get_settings
from agent_os.scheduler.aging import AgingPolicy


class PriorityScheduler:
    """
    Priority scheduler that selects the process with the highest
    effective priority (§21).

    effective_priority = base_priority + aging_bonus - resource_penalty

    Tie-break: lowest process_id.
    """

    def __init__(self, settings=None):
        s = settings or get_settings()
        self._aging_enabled = s.scheduler.aging.enabled
        self._aging_policy = AgingPolicy(settings=s)

    def add(self, process: AgentProcess) -> None:
        """No-op for priority scheduler (stateless selection)."""
        pass

    def remove(self, process_id: int) -> None:
        """No-op for priority scheduler."""
        pass

    def select_next(self, processes: List[AgentProcess]) -> Optional[AgentProcess]:
        """
        Select the process with the highest effective priority.

        Only READY processes are eligible.
        """
        runnable = [p for p in processes if p.state == ProcessState.READY]
        if not runnable:
            return None

        now = time.time()
        best_process = None
        highest_priority = -float("inf")

        for p in runnable:
            base_priority = p.priority

            # Calculate aging bonus from time spent in READY
            aging_bonus = 0
            if self._aging_enabled and p.ready_since is not None:
                wait_time = now - p.ready_since
                aging_bonus = self._aging_policy.calculate_bonus(wait_time)

            resource_penalty = 0  # placeholder for future resource-based penalty

            effective_priority = base_priority + aging_bonus - resource_penalty

            if effective_priority > highest_priority:
                highest_priority = effective_priority
                best_process = p
            elif effective_priority == highest_priority:
                if best_process is None or p.process_id < best_process.process_id:
                    best_process = p

        return best_process
