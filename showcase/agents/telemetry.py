"""
Telemetry Agent (Priority 2)

The lowest-priority background daemon.
Runs perpetually collecting system snapshots.

OS Features demonstrated:
  - Starvation prevention via AGING
    (Priority 2 would never run if Commander/Auditor keep arriving,
     but the aging mechanism increments its effective priority each tick
     until the OS finally grants it CPU time.)
  - Background daemon pattern (low priority, long-running)
  - Process Table polling (reads live OS state)
"""
from __future__ import annotations
from agent_os import AgentContext, AgentStepResult, StepStatus

MAX_TICKS = 25


class TelemetryAgent:
    """
    Passive background monitor. Priority 2 — proves starvation prevention.
    Collects system-wide stats every tick it manages to run.
    """

    def __init__(self, process_manager):
        self._pm        = process_manager
        self._tick      = 0
        self._skipped   = 0  # ticks it was READY but not scheduled (aging saved it)
        self.snapshots: list[dict] = []

    async def step(self, ctx: AgentContext) -> AgentStepResult:
        self._tick += 1

        all_procs   = await self._pm.list()
        total_tokens = sum(p.resource_usage.total_tokens for p in all_procs)
        total_steps  = sum(p.resource_usage.steps for p in all_procs)
        by_state     = {}
        for p in all_procs:
            by_state[p.state.value] = by_state.get(p.state.value, 0) + 1

        snapshot = {
            "tick":          self._tick,
            "processes":     len(all_procs),
            "total_tokens":  total_tokens,
            "total_steps":   total_steps,
            "by_state":      by_state,
        }
        self.snapshots.append(snapshot)

        if self._tick % 5 == 0:
            running   = by_state.get("RUNNING", 0)
            waiting   = by_state.get("WAITING", 0)
            failed    = by_state.get("FAILED", 0)
            done      = by_state.get("TERMINATED", 0) + by_state.get("COMPLETED", 0)
            print(
                f"  [Telemetry] Tick {self._tick:02d} | "
                f"procs={len(all_procs)} run={running} wait={waiting} "
                f"fail={failed} done={done} | "
                f"tokens={total_tokens} steps={total_steps}"
            )

        if self._tick >= MAX_TICKS:
            print(f"  [Telemetry] Completed {self._tick} monitoring ticks ✓")
            return AgentStepResult(
                status=StepStatus.COMPLETED,
                output={"ticks": self._tick, "snapshots": len(self.snapshots)},
            )

        return AgentStepResult(status=StepStatus.CONTINUE, output=snapshot)
