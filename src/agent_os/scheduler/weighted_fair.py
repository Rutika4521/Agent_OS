"""
Agent-OS Scheduler — Weighted Fair Scheduler

Implements deterministic deficit-based weighted fair scheduling (§24).
"""

from __future__ import annotations

from typing import List, Optional

from agent_os.kernel.agent_process import AgentProcess
from agent_os.kernel.state_machine import ProcessState


class WeightedFairScheduler:
    """
    Deficit-based weighted fair scheduler (§24).

    Each process has a deficit counter. On select_next():
    1. Add weight to each runnable process's deficit
    2. Select process with highest deficit
    3. Subtract 1 from selected process's deficit

    This ensures over time, processes receive scheduling
    proportional to their weight.
    """

    def __init__(self, settings=None):
        self._deficits: dict[int, float] = {}

    def add(self, process: AgentProcess) -> None:
        """Track a new process."""
        if process.process_id not in self._deficits:
            self._deficits[process.process_id] = 0.0

    def remove(self, process_id: int) -> None:
        """Stop tracking a process."""
        self._deficits.pop(process_id, None)

    def select_next(self, processes: List[AgentProcess]) -> Optional[AgentProcess]:
        """
        Select next process using deficit-based fair scheduling.

        Higher weight processes accumulate deficit faster,
        so they get selected more often.
        """
        runnable = [p for p in processes if p.state == ProcessState.READY]
        if not runnable:
            return None

        # Add weight to deficit for each runnable process
        for p in runnable:
            pid = p.process_id
            if pid not in self._deficits:
                self._deficits[pid] = 0.0
            self._deficits[pid] += p.weight

        # Select process with highest deficit
        best_process = None
        highest_deficit = -float("inf")

        for p in runnable:
            deficit = self._deficits[p.process_id]
            if deficit > highest_deficit:
                highest_deficit = deficit
                best_process = p
            elif deficit == highest_deficit:
                # Tie-break by lowest process_id
                if best_process is None or p.process_id < best_process.process_id:
                    best_process = p

        # Subtract 1 from selected process's deficit
        if best_process is not None:
            self._deficits[best_process.process_id] -= 1.0

        return best_process
