"""
Agent-OS — Top-level public API

When users write `import agent_os`, they get both:
  - The SDK decorator API:  register, Kernel, AutoWrapper
  - The OS types:           ProcessState, StepStatus, AgentStepResult, WaitReason

Usage:
    import agent_os

    @agent_os.register(priority=7, name="MyAgent")
    class MyAgent:
        async def run(self) -> str:
            return "done"

    async def main():
        kernel = agent_os.Kernel()
        await kernel.boot()
        await kernel.spawn_registered()
        await kernel.run()

    asyncio.run(main())
"""
from __future__ import annotations

from agent_os.sdk.registry import (
    register,
    get_registry,
    clear_registry,
    registered_count,
    AgentRegistration,
)
from agent_os.sdk.wrapper import AutoWrapper
from agent_os.sdk.kernel import Kernel, KernelNotBootedError
from agent_os.sdk.agent import Agent, AgentContext

# Core OS types — always available
from agent_os.kernel.state_machine import (
    AgentStepResult,
    StepStatus,
    WaitReason,
    ProcessState,
)

__all__ = [
    # SDK
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
    # OS types
    "AgentStepResult",
    "StepStatus",
    "WaitReason",
    "ProcessState",
]
