"""
Budget Buster Agent (Priority 9)

Spawned with a hard token_limit of 800.
Burns 300 tokens per step — hits the limit on step 3 (900 total).
The tick loop enforces the limit at the kernel level and emits RESOURCE_LIMIT.

OS Features demonstrated:
  - Hard resource quota enforcement (token_limit)
  - RESOURCE_LIMIT event emitted by kernel
  - Process preempted / terminated by OS — not by agent code
  - ResourceLimits.token_limit field
"""
from __future__ import annotations
from agent_os import AgentContext, AgentStepResult, StepStatus

BURN_PER_STEP = 300  # tokens per step
TOKEN_LIMIT   = 800  # set on the process after spawn


class BudgetBusterAgent:
    """
    Intentionally burns tokens above its assigned limit.
    The kernel tick loop detects the breach and terminates this process
    before step 4 can run — proving the OS enforces budgets, not the agent.
    """

    STEPS = [
        "Fetching training corpus from S3 (300 tokens)",
        "Running embedding model on 10,000 documents (300 tokens)",
        "Generating vector index — this will exceed the budget! (300 tokens)",
        "THIS STEP SHOULD NEVER RUN — kernel should have preempted us",
    ]

    def __init__(self):
        self._step = 0

    async def step(self, ctx: AgentContext) -> AgentStepResult:
        self._step += 1
        label = self.STEPS[min(self._step - 1, len(self.STEPS) - 1)]

        # Burn tokens — kernel tick loop will catch the limit breach
        proc = ctx.data.get("process")
        if proc:
            proc.resource_usage.total_tokens  += BURN_PER_STEP
            proc.resource_usage.input_tokens  += BURN_PER_STEP // 3
            proc.resource_usage.output_tokens += BURN_PER_STEP * 2 // 3
            proc.resource_usage.llm_calls     += 1

        print(f"  [BudgetBuster] Step {self._step} — {label}")
        print(f"  [BudgetBuster] Running total: {proc.resource_usage.total_tokens if proc else '?'} tokens "
              f"(limit: {TOKEN_LIMIT})")

        return AgentStepResult(status=StepStatus.CONTINUE, output=label)
