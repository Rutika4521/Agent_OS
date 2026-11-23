"""
Demo Agent: Researcher

Priority 8 — high priority research worker.
Performs 4-step research cycle, burning tokens visibly,
then sends findings to Analyst via IPC.
"""
from __future__ import annotations

from sdk.agent import AgentContext
from agent_os.kernel.state_machine import AgentStepResult, StepStatus

TOPICS = [
    "Quantum Computing Fundamentals",
    "Neural Architecture Search (NAS)",
    "Large Language Models and Transformers",
    "Agent Operating Systems",
]

# Simulated token cost per research step
TOKENS_PER_STEP = [320, 450, 510, 280]


class ResearchAgent:
    """
    4-step research agent.
    Each step researches one topic and accumulates findings.
    On completion, sends full report to Analyst via IPC.
    """

    def __init__(self, ipc_manager, pid_map: dict):
        self._ipc = ipc_manager
        self._pid_map = pid_map
        self._step = 0
        self._findings: list[str] = []

    async def step(self, ctx: AgentContext) -> AgentStepResult:
        if self._step >= len(TOPICS):
            return AgentStepResult(status=StepStatus.COMPLETED, output=self._findings)

        topic = TOPICS[self._step]
        tokens = TOKENS_PER_STEP[self._step]

        # Simulate resource burn: update usage directly on the process
        proc = ctx.data.get("process")
        if proc:
            proc.resource_usage.total_tokens += tokens
            proc.resource_usage.input_tokens += tokens // 2
            proc.resource_usage.output_tokens += tokens // 2
            proc.resource_usage.llm_calls += 1
            proc.resource_usage.steps += 1

        finding = f"[Research] Topic '{topic}': {tokens} tokens consumed, findings gathered."
        self._findings.append(finding)
        print(f"  [Researcher] Step {self._step + 1}/4 — {topic} ({tokens} tokens)")

        self._step += 1

        # On last step, forward all findings to analyst
        if self._step >= len(TOPICS):
            summary = " | ".join(self._findings)
            await self._ipc.send(ctx.process_id, self._pid_map["analyst"], summary)
            print(f"  [Researcher] Sent {len(self._findings)} findings → Analyst")
            return AgentStepResult(status=StepStatus.COMPLETED, output=summary)

        return AgentStepResult(status=StepStatus.CONTINUE, output=finding)
