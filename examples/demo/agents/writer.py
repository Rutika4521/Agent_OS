"""
Demo Agent: Writer

Priority 6 — medium priority.
Waits for synthesis from Analyst via IPC, then produces a
final formatted report in 2 steps. Heavy token consumer —
great for showing Resource Meters in the UI.
"""
from __future__ import annotations

from sdk.agent import AgentContext
from agent_os.kernel.state_machine import AgentStepResult, StepStatus


class WriterAgent:
    """
    2-step writer: draft → polish.
    Demonstrates high token consumption and IPC receive.
    """

    def __init__(self, ipc_manager):
        self._ipc = ipc_manager
        self._step = 0
        self._synthesis: str | None = None
        self._draft: str | None = None

    async def step(self, ctx: AgentContext) -> AgentStepResult:
        # Step 0: wait for IPC synthesis from Analyst
        if self._step == 0:
            msg = await self._ipc.receive(ctx.process_id)
            if msg is None:
                print(f"  [Writer] Waiting for analyst synthesis via IPC...")
                return AgentStepResult(status=StepStatus.WAIT, output="waiting for synthesis")

            self._synthesis = str(msg.payload)
            print(f"  [Writer] Received analyst synthesis ({len(self._synthesis)} chars)")

            # Step 1: Draft
            tokens = 620
            proc = ctx.data.get("process")
            if proc:
                proc.resource_usage.total_tokens += tokens
                proc.resource_usage.input_tokens += 200
                proc.resource_usage.output_tokens += 420
                proc.resource_usage.llm_calls += 1
                proc.resource_usage.steps += 1

            self._draft = (
                "=== RESEARCH INTELLIGENCE REPORT ===\n"
                f"Based on: {self._synthesis[:120]}...\n"
                "Draft complete. Pending review pass."
            )
            print(f"  [Writer] Step 1/2 — Draft written ({tokens} tokens)")
            self._step = 1
            return AgentStepResult(status=StepStatus.CONTINUE, output=self._draft)

        elif self._step == 1:
            # Step 2: Polish
            tokens = 390
            proc = ctx.data.get("process")
            if proc:
                proc.resource_usage.total_tokens += tokens
                proc.resource_usage.input_tokens += 100
                proc.resource_usage.output_tokens += 290
                proc.resource_usage.llm_calls += 1
                proc.resource_usage.steps += 1

            final = self._draft.replace("Pending review pass.", "FINAL VERSION READY.")
            print(f"  [Writer] Step 2/2 — Report polished ({tokens} tokens)")
            self._step = 2
            return AgentStepResult(status=StepStatus.COMPLETED, output=final)

        return AgentStepResult(status=StepStatus.COMPLETED, output=self._draft)
