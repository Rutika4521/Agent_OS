"""
Demo Agent: Orchestrator

Priority 10 — runs first every tick.
Broadcasts task assignments to all other agents via IPC
and tracks overall pipeline progress.
"""
from __future__ import annotations

from sdk.agent import AgentContext
from agent_os.kernel.state_machine import AgentStepResult, StepStatus


class OrchestratorAgent:
    """
    The top-priority coordinator.

    Step 1: Broadcast research task to ResearchAgent (IPC)
    Step 2: Broadcast analysis task to AnalystAgent (IPC)
    Step 3: Signal WriterAgent to compile final report
    """

    def __init__(self, ipc_manager, pid_map: dict):
        self._ipc = ipc_manager
        self._pid_map = pid_map   # filled in after all agents are spawned
        self._step = 0
        self.log: list[str] = []

    async def step(self, ctx: AgentContext) -> AgentStepResult:
        self._step += 1

        if self._step == 1:
            msg = "TASK: Research quantum computing and neural architecture search"
            await self._ipc.send(ctx.process_id, self._pid_map["researcher"], msg)
            self.log.append(f"[Orchestrator] → Researcher: assigned research task")
            print(f"  [Orchestrator] Sent research task to Researcher (PID {self._pid_map['researcher']})")
            return AgentStepResult(status=StepStatus.CONTINUE, output=msg)

        elif self._step == 2:
            msg = "TASK: Analyse research findings and extract key insights"
            await self._ipc.send(ctx.process_id, self._pid_map["analyst"], msg)
            self.log.append(f"[Orchestrator] → Analyst: assigned analysis task")
            print(f"  [Orchestrator] Sent analysis task to Analyst (PID {self._pid_map['analyst']})")
            return AgentStepResult(status=StepStatus.CONTINUE, output=msg)

        elif self._step == 3:
            msg = "TASK: Compile executive summary report"
            await self._ipc.send(ctx.process_id, self._pid_map["writer"], msg)
            self.log.append(f"[Orchestrator] → Writer: compile report")
            print(f"  [Orchestrator] Sent compile task to Writer (PID {self._pid_map['writer']})")
            return AgentStepResult(status=StepStatus.COMPLETED, output="Pipeline orchestration complete")

        return AgentStepResult(status=StepStatus.COMPLETED, output="done")
