"""
Exponential Backoff Agent (Priority 4)

Uses the EXPONENTIAL_BACKOFF restart policy.
Fails multiple times. Each restart happens after an exponentially growing delay.
After the final successful restart it completes.

OS Features demonstrated:
  - restart_policy = "EXPONENTIAL_BACKOFF"
  - RestartManager.get_backoff_delay(restart_count) governs the wait
  - Multiple RESTART_STARTED / RESTART_COMPLETED events in event log
  - restart_count increments: 0 → 1 → 2 → complete
"""
from __future__ import annotations
from agent_os import AgentContext, AgentStepResult, StepStatus

# Agent fails on run 0 and run 1, succeeds on run 2+
FAIL_RUNS = {0, 1}


class ExponentialBackoffAgent:
    """
    Simulates a flaky external API call with exponential retry.
    Fails twice, then succeeds — proving the EXPONENTIAL_BACKOFF policy works.
    """

    def __init__(self):
        self._step = 0

    async def step(self, ctx: AgentContext) -> AgentStepResult:
        self._step += 1
        proc = ctx.data.get("process")
        restart_count = proc.restart_count if proc else 0

        if restart_count in FAIL_RUNS:
            delay_hint = 2 ** restart_count  # illustrative — actual delay by RestartManager
            print(
                f"  [ExpBackoff] Run #{restart_count} — FAILED 💥 "
                f"(next backoff ≈ {delay_hint}s, policy=EXPONENTIAL_BACKOFF)"
            )
            return AgentStepResult(
                status=StepStatus.FAILED,
                error=f"APITimeoutError: attempt {restart_count + 1} failed — retrying with backoff",
            )

        # Succeeded after exponential backoff retries
        print(
            f"  [ExpBackoff] Run #{restart_count} — ✓ SUCCEEDED after "
            f"{restart_count} backoff restart(s)"
        )
        return AgentStepResult(
            status=StepStatus.COMPLETED,
            output=f"External API responded successfully on attempt {restart_count + 1}",
        )
