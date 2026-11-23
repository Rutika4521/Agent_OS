"""
Contended Workers A and B (Priority 6 each)

Two agents that request the same exclusive lock out of order,
creating a circular dependency — triggering deadlock detection.

OS Features demonstrated:
  - BLOCKED state (waiting on a lock)
  - Deadlock detection (cycle in resource-wait graph)
  - Lock acquisition and release
  - OS-level resolution (one process is unblocked by the kernel)
"""
from __future__ import annotations
from agent_os import AgentContext, AgentStepResult, StepStatus, WaitReason


class ContendedWorkerA:
    """
    Worker A: requests lock 'db-write' then 'cache-lock'.
    If Worker B holds 'cache-lock' first → deadlock.
    """

    def __init__(self):
        self._step = 0
        self._lock_a_held = False

    async def step(self, ctx: AgentContext) -> AgentStepResult:
        self._step += 1

        if self._step == 1:
            print(f"  [WorkerA] Step 1 — Acquired lock: db-write ✓")
            self._lock_a_held = True
            return AgentStepResult(status=StepStatus.CONTINUE, output="acquired db-write")

        elif self._step == 2:
            # Requesting cache-lock — may be held by WorkerB → deadlock
            print(f"  [WorkerA] Step 2 — Requesting lock: cache-lock (may deadlock…)")
            return AgentStepResult(
                status=StepStatus.BLOCK,
                output="waiting for cache-lock",
            )

        elif self._step == 3:
            # Resumed after deadlock resolution
            print(f"  [WorkerA] Step 3 — Deadlock resolved by OS. Completing task ✓")
            return AgentStepResult(
                status=StepStatus.COMPLETED,
                output="database migration completed",
            )

        return AgentStepResult(status=StepStatus.COMPLETED, output="done")


class ContendedWorkerB:
    """
    Worker B: requests lock 'cache-lock' then 'db-write'.
    Reverse order from Worker A → circular dependency → deadlock.
    """

    def __init__(self):
        self._step = 0

    async def step(self, ctx: AgentContext) -> AgentStepResult:
        self._step += 1

        if self._step == 1:
            print(f"  [WorkerB] Step 1 — Acquired lock: cache-lock ✓")
            return AgentStepResult(status=StepStatus.CONTINUE, output="acquired cache-lock")

        elif self._step == 2:
            # Requesting db-write — held by WorkerA → deadlock
            print(f"  [WorkerB] Step 2 — Requesting lock: db-write (may deadlock…)")
            return AgentStepResult(
                status=StepStatus.BLOCK,
                output="waiting for db-write",
            )

        elif self._step == 3:
            print(f"  [WorkerB] Step 3 — Deadlock resolved by OS. Completing task ✓")
            return AgentStepResult(
                status=StepStatus.COMPLETED,
                output="cache invalidation completed",
            )

        return AgentStepResult(status=StepStatus.COMPLETED, output="done")
