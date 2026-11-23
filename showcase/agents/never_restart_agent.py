"""
Critical Fail Agent (Priority 8)

Uses the NEVER restart policy.
When it fails, the Supervisor terminates it immediately — no retry.
Demonstrates that Agent-OS gives full control over restart behaviour.

OS Features demonstrated:
  - restart_policy = "NEVER"
  - Supervisor: NEVER → FAILED → TERMINATED immediately
  - Failure blast radius is still contained (other agents unaffected)
  - Distinct from N_TIMES / ONCE / EXPONENTIAL_BACKOFF
"""
from __future__ import annotations
from agent_os import AgentContext, AgentStepResult, StepStatus


class CriticalFailAgent:
    """
    A 'critical' process whose failure must NOT be masked by an auto-restart.
    Real-world analogy: a data-integrity check that must halt on any anomaly.
    Policy NEVER: one failure → permanent termination.
    """

    def __init__(self):
        self._step = 0

    async def step(self, ctx: AgentContext) -> AgentStepResult:
        self._step += 1

        if self._step == 1:
            print(f"  [CriticalFail] Step 1 — running data integrity validation…")
            return AgentStepResult(status=StepStatus.CONTINUE, output="integrity check started")

        elif self._step == 2:
            print(f"  [CriticalFail] Step 2 — CHECKSUM MISMATCH 🛑 (policy=NEVER, no restart allowed)")
            return AgentStepResult(
                status=StepStatus.FAILED,
                error="ChecksumMismatch: database index corrupted — escalating to ops team",
            )

        # This step should never be reached — NEVER policy means no restart
        return AgentStepResult(status=StepStatus.COMPLETED, output="unreachable")
