"""
Flaky Test Runner Agent (Priority 5)

Intentionally crashes on its first run to trigger Supervisor auto-restart.
After restart: recovers and completes successfully.

OS Features demonstrated:
  - FAILED process state
  - Supervisor detection + N_TIMES restart policy
  - RESTARTING → READY state transition (visible in Scheduler Timeline)
  - restart_count increments (visible in Process Table)
"""
from __future__ import annotations
from agent_os import AgentContext, AgentStepResult, StepStatus


class FlakyTestRunnerAgent:
    """
    Simulates an agent that depends on an external CI/CD service.
    First run: crashes on step 2 (simulated network timeout).
    After supervisor restart: runs to completion.
    """

    def __init__(self):
        self._step = 0

    async def step(self, ctx: AgentContext) -> AgentStepResult:
        self._step += 1
        proc = ctx.data.get("process")
        restart_count = proc.restart_count if proc else 0

        if restart_count == 0:
            # First run — crash on step 2
            if self._step == 1:
                print(f"  [FlakyRunner] Step 1 — Connecting to CI/CD pipeline… OK")
                return AgentStepResult(status=StepStatus.CONTINUE, output="connected")
            elif self._step == 2:
                print(f"  [FlakyRunner] Step 2 — NETWORK TIMEOUT 💥 (simulated)")
                return AgentStepResult(
                    status=StepStatus.FAILED,
                    output=None,
                    error="ConnectionError: CI/CD service unreachable (timeout after 30s)",
                )
        else:
            # Post-restart: complete successfully
            if self._step <= 3:
                print(f"  [FlakyRunner] Post-restart step {self._step} — recovered ✓ (restart #{restart_count})")
                return AgentStepResult(status=StepStatus.CONTINUE, output=f"step {self._step} ok")
            print(f"  [FlakyRunner] All tests PASSED after {restart_count} supervisor restart(s) ✓")
            return AgentStepResult(
                status=StepStatus.COMPLETED,
                output=f"42/42 tests passed (recovered after {restart_count} restart)",
            )

        return AgentStepResult(status=StepStatus.COMPLETED, output="done")
