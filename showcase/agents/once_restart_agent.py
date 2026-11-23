"""
Once-Restart Agent (Priority 6)

Uses the ONCE restart policy.
Fails on its first step. The Supervisor restarts it exactly once.
On the second run it succeeds. If it were to fail again, the Supervisor
would NOT restart it (ONCE = max 1 restart).

OS Features demonstrated:
  - restart_policy = "ONCE"
  - Supervisor: ONCE allows only 1 restart
  - FAILED → RESTARTING → READY → COMPLETED lifecycle
  - restart_count incremented to 1 and capped
"""
from __future__ import annotations
from agent_os import AgentContext, AgentStepResult, StepStatus


class OnceRestartAgent:
    """
    Fails on first run. Recovers cleanly after exactly one Supervisor restart.
    Policy ONCE: supervisor will restart it at most 1 time.
    """

    def __init__(self):
        self._step = 0

    async def step(self, ctx: AgentContext) -> AgentStepResult:
        self._step += 1
        proc = ctx.data.get("process")
        restart_count = proc.restart_count if proc else 0

        if restart_count == 0:
            print(f"  [OnceRestart] First run — simulating a transient error 💥")
            return AgentStepResult(
                status=StepStatus.FAILED,
                error="TransientError: external service unavailable (will recover once restarted)",
            )
        else:
            # Post-restart: succeed immediately
            print(f"  [OnceRestart] Post-restart run — recovered successfully ✓ "
                  f"(restart #{restart_count}, policy=ONCE)")
            return AgentStepResult(
                status=StepStatus.COMPLETED,
                output=f"Task completed after {restart_count} supervisor restart(s)",
            )
