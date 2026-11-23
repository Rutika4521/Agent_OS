"""
Demo Agent: FaultAgent

Priority 5 — demonstrates Supervisor restart behaviour.
Intentionally fails on step 2, triggering the Supervisor
to restart it. Recovers and completes on the 2nd run.
"""
from __future__ import annotations

from sdk.agent import AgentContext
from agent_os.kernel.state_machine import AgentStepResult, StepStatus


class FaultAgent:
    """
    A deliberately fragile agent.

    Run 1: step 1 OK → step 2 FAILS (raises exception)
    Supervisor detects FAILED state → restarts → restart_count increments
    Run 2: completes normally (demonstrates recovery)
    """

    def __init__(self):
        self._step = 0
        self._total_runs = 0

    async def step(self, ctx: AgentContext) -> AgentStepResult:
        self._step += 1
        self._total_runs += 1

        proc = ctx.data.get("process")
        restart_count = proc.restart_count if proc else 0

        if restart_count == 0:
            # First run — fail on step 2
            if self._step == 1:
                print(f"  [FaultAgent] Step 1 — initializing... OK")
                return AgentStepResult(status=StepStatus.CONTINUE, output="init ok")

            elif self._step == 2:
                print(f"  [FaultAgent] Step 2 — SIMULATING CRASH 💥")
                # Returning FAILED status to trigger supervisor
                return AgentStepResult(
                    status=StepStatus.FAILED,
                    output=None,
                    error="Simulated failure: external API timeout",
                )

        else:
            # After restart — run successfully
            if self._step <= 2:
                print(f"  [FaultAgent] Post-restart step {self._step} — recovered ✓ (restart #{restart_count})")
                return AgentStepResult(status=StepStatus.CONTINUE, output=f"recovered step {self._step}")

            print(f"  [FaultAgent] Completed after {restart_count} restart(s) ✓")
            return AgentStepResult(status=StepStatus.COMPLETED, output="recovered and completed")

        return AgentStepResult(status=StepStatus.COMPLETED, output="done")
