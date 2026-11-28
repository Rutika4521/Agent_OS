"""
Agent-OS SDK — Public API (installed package version)

Import everything you need from here:

    import agent_os

    @agent_os.register(priority=7, name="Planner")
    class PlannerAgent:
        async def run(self, task: str) -> str:
            return f"Plan for {task}"

    async def main():
        kernel = agent_os.Kernel()
        await kernel.boot()
        await kernel.spawn_registered()
        await kernel.run()

    asyncio.run(main())
"""
from __future__ import annotations

# Decorator & registry
from agent_os.sdk.registry import (
    register,
    get_registry,
    clear_registry,
    registered_count,
    AgentRegistration,
)

# Wrapper
from agent_os.sdk.wrapper import AutoWrapper

# Kernel bootstrap
from agent_os.sdk.kernel import Kernel, KernelNotBootedError

# Agent protocol & context
from agent_os.sdk.agent import Agent, AgentContext

# Core OS types re-exported for convenience
from agent_os.kernel.state_machine import (
    AgentStepResult,
    StepStatus,
    WaitReason,
    ProcessState,
)

__all__ = [
    "register",
    "get_registry",
    "clear_registry",
    "registered_count",
    "AgentRegistration",
    "AutoWrapper",
    "Kernel",
    "KernelNotBootedError",
    "Agent",
    "AgentContext",
    "AgentStepResult",
    "StepStatus",
    "WaitReason",
    "ProcessState",
]
