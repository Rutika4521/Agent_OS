"""
Incident Commander Agent (Priority 10)

The highest-priority coordinator. Runs first every scheduling tick.
Dispatches tasks to the team via IPC, tracks SLA timers.

OS Features demonstrated:
  - Preemptive Priority Scheduling (always wins the scheduler)
  - IPC send (task assignments to Auditor, Fixer, Telemetry)
"""
from __future__ import annotations
from agent_os import AgentContext, AgentStepResult, StepStatus


class IncidentCommanderAgent:
    """
    Coordinates the incident response pipeline.
    Sends task assignments to: Auditor, Fixer, Telemetry.
    """

    ASSIGNMENTS = [
        ("auditor",   "TASK: Audit codebase for CVE-2024-9999 — SQL injection in /api/login"),
        ("fixer",     "TASK: Prepare patch scaffold for SQL injection vector"),
        ("telemetry", "TASK: Begin continuous system telemetry collection"),
    ]

    def __init__(self, ipc_manager, pid_map: dict):
        self._ipc     = ipc_manager
        self._pid_map = pid_map
        self._step    = 0
        self.log: list[str] = []

    async def step(self, ctx: AgentContext) -> AgentStepResult:
        if self._step >= len(self.ASSIGNMENTS):
            return AgentStepResult(
                status=StepStatus.COMPLETED,
                output="All incident assignments dispatched."
            )

        target, task = self.ASSIGNMENTS[self._step]
        pid = self._pid_map.get(target)
        if pid is not None:
            await self._ipc.send(ctx.process_id, pid, task)
            msg = f"[Commander] → {target.capitalize()} (PID {pid}): {task[:60]}..."
            self.log.append(msg)
            print(f"  {msg}")

        self._step += 1
        status = StepStatus.COMPLETED if self._step >= len(self.ASSIGNMENTS) else StepStatus.CONTINUE
        return AgentStepResult(status=status, output=task)
