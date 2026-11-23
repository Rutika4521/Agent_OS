"""
Long Running Agent (Priority 5)

A multi-step background worker designed to be PAUSED, RESUMED, and eventually
CANCELLED mid-execution by the orchestrator in main.py / run_server.py.

OS Features demonstrated:
  - pm.pause(pid)  → RUNNING → WAITING (WaitReason.SLEEP)
  - pm.resume(pid) → WAITING → READY
  - pm.cancel(pid) → RUNNING → CANCELLING → CANCELLED → TERMINATED
  - PROCESS_WAITING, PROCESS_CANCELLED events in event log
"""
from __future__ import annotations
from agent_os import AgentContext, AgentStepResult, StepStatus

MAX_STEPS = 50   # intentionally long so pause/cancel can interrupt it


class LongRunningAgent:
    """
    Simulates a long batch processing job (e.g., nightly report generation).
    The orchestrator will pause it, then resume it, then cancel it
    at different ticks to demonstrate all three kernel operations.
    """

    def __init__(self):
        self._step = 0

    async def step(self, ctx: AgentContext) -> AgentStepResult:
        self._step += 1
        progress = int((self._step / MAX_STEPS) * 100)

        if self._step % 5 == 0:
            print(f"  [LongRunner] Step {self._step:02d}/{MAX_STEPS} — progress {progress}%")

        if self._step >= MAX_STEPS:
            print(f"  [LongRunner] All {MAX_STEPS} steps completed ✓")
            return AgentStepResult(
                status=StepStatus.COMPLETED,
                output=f"Batch job done — {self._step} steps processed",
            )

        return AgentStepResult(
            status=StepStatus.CONTINUE,
            output={"step": self._step, "progress_pct": progress},
        )
