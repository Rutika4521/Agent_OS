"""
Demo Agent: Monitor

Priority 3 — lowest priority background daemon.
Runs every tick, collecting and printing system-wide stats.
Demonstrates a long-running background agent that never blocks
higher-priority agents.
"""
from __future__ import annotations

from sdk.agent import AgentContext
from agent_os.kernel.state_machine import AgentStepResult, StepStatus, ProcessState


class MonitorAgent:
    """
    Lightweight background monitor.
    Reads the process table each tick and prints a summary.
    Runs for a fixed number of ticks then self-completes.
    """
    MAX_TICKS = 20

    def __init__(self, process_manager):
        self._pm = process_manager
        self._tick = 0
        self.snapshots: list[dict] = []

    async def step(self, ctx: AgentContext) -> AgentStepResult:
        self._tick += 1

        # Collect live stats
        all_procs = await self._pm.list()
        state_counts: dict[str, int] = {}
        total_tokens = 0
        total_steps = 0

        for p in all_procs:
            state_counts[p.state.value] = state_counts.get(p.state.value, 0) + 1
            total_tokens += p.resource_usage.total_tokens
            total_steps += p.resource_usage.steps

        snapshot = {
            "tick": self._tick,
            "process_count": len(all_procs),
            "state_counts": state_counts,
            "total_tokens": total_tokens,
            "total_steps": total_steps,
        }
        self.snapshots.append(snapshot)

        # Only print every 3 ticks to reduce noise
        if self._tick % 3 == 0:
            running = state_counts.get("RUNNING", 0)
            ready = state_counts.get("READY", 0)
            waiting = state_counts.get("WAITING", 0)
            completed = state_counts.get("COMPLETED", 0) + state_counts.get("TERMINATED", 0)
            print(
                f"  [Monitor] Tick {self._tick:02d} | "
                f"Processes: {len(all_procs)} | "
                f"RUNNING={running} READY={ready} WAITING={waiting} DONE={completed} | "
                f"Tokens: {total_tokens} Steps: {total_steps}"
            )

        if self._tick >= self.MAX_TICKS:
            print(f"  [Monitor] Completed after {self._tick} monitoring ticks.")
            return AgentStepResult(
                status=StepStatus.COMPLETED,
                output={"ticks": self._tick, "snapshots": len(self.snapshots)},
            )

        return AgentStepResult(status=StepStatus.CONTINUE, output=snapshot)
