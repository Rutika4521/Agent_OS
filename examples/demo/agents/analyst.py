"""
Demo Agent: Analyst

Priority 7 — medium-high priority.
Waits for IPC message from Researcher (demonstrates WAITING state),
then performs 3-step analysis cycle.
Sends synthesis to Writer on completion.
"""
from __future__ import annotations

from sdk.agent import AgentContext
from agent_os.kernel.state_machine import AgentStepResult, StepStatus, WaitReason

ANALYSIS_PHASES = [
    ("Pattern Extraction",    200),
    ("Insight Synthesis",     350),
    ("Recommendation Framing", 180),
]


class AnalystAgent:
    """
    3-phase analyst — demonstrates IPC receive and context usage.
    """

    def __init__(self, ipc_manager, pid_map: dict):
        self._ipc = ipc_manager
        self._pid_map = pid_map
        self._phase = 0
        self._research_data: str | None = None
        self._insights: list[str] = []

    async def step(self, ctx: AgentContext) -> AgentStepResult:
        # Phase 0: wait for IPC message from Researcher
        if self._phase == 0:
            msg = await self._ipc.receive(ctx.process_id)
            if msg is None:
                # Nothing yet — yield back to scheduler (demonstrates WAIT)
                print(f"  [Analyst] Waiting for research data via IPC...")
                return AgentStepResult(status=StepStatus.WAIT, output="waiting for IPC")

            self._research_data = str(msg.payload)
            print(f"  [Analyst] Received research data ({len(self._research_data)} chars)")
            self._phase = 1

        if self._phase > len(ANALYSIS_PHASES):
            return AgentStepResult(status=StepStatus.COMPLETED, output=self._insights)

        idx = self._phase - 1
        if idx >= len(ANALYSIS_PHASES):
            # Forward insights to Writer
            synthesis = " | ".join(self._insights)
            await self._ipc.send(ctx.process_id, self._pid_map["writer"], synthesis)
            print(f"  [Analyst] Sent synthesis → Writer")
            return AgentStepResult(status=StepStatus.COMPLETED, output=synthesis)

        phase_name, tokens = ANALYSIS_PHASES[idx]

        proc = ctx.data.get("process")
        if proc:
            proc.resource_usage.total_tokens += tokens
            proc.resource_usage.input_tokens += tokens // 3
            proc.resource_usage.output_tokens += tokens * 2 // 3
            proc.resource_usage.llm_calls += 1
            proc.resource_usage.steps += 1

        insight = f"[Analysis:{phase_name}] Processed {tokens} tokens."
        self._insights.append(insight)
        print(f"  [Analyst] Phase {self._phase}/{len(ANALYSIS_PHASES)} — {phase_name} ({tokens} tokens)")

        self._phase += 1

        if self._phase > len(ANALYSIS_PHASES):
            synthesis = " | ".join(self._insights)
            await self._ipc.send(ctx.process_id, self._pid_map["writer"], synthesis)
            print(f"  [Analyst] Sent synthesis → Writer")
            return AgentStepResult(status=StepStatus.COMPLETED, output=synthesis)

        return AgentStepResult(status=StepStatus.CONTINUE, output=insight)
