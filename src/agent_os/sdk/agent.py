"""
Agent-OS SDK — Agent Interface

Defines the generic Agent protocol and AgentContext (§8, §10).
Applications implement the Agent protocol to define agent behavior.
Agent-OS manages execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from agent_os.kernel.state_machine import AgentStepResult


@dataclass
class AgentContext:
    """
    Context provided to an agent during step execution (§10).

    The context must not directly expose internal kernel objects.
    Agents interact through controlled interfaces.
    """
    process_id: int
    data: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Agent(Protocol):
    """
    Generic agent interface (§8).

    An agent performs bounded execution steps.
    The scheduler controls execution at step boundaries.
    """

    async def step(self, context: AgentContext) -> AgentStepResult:
        """
        Execute a single bounded step.

        Returns:
            AgentStepResult indicating step outcome.
        """
        ...
