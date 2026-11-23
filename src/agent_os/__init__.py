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

import sys as _sys
from pathlib import Path as _Path

# ── Auto-discover and add the project root so `sdk` is importable as a package.
# This file lives at:  <project_root>/src/agent_os/__init__.py
# So parents[2] == project root  (agent_os/ → src/ → project root)
_PROJECT_ROOT = str(_Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in _sys.path:
    _sys.path.insert(0, _PROJECT_ROOT)

# SDK public API
from sdk.registry import (       # noqa: E402
    register,
    get_registry,
    clear_registry,
    registered_count,
    AgentRegistration,
)
from sdk.wrapper import AutoWrapper        # noqa: E402
from sdk.kernel import Kernel, KernelNotBootedError  # noqa: E402
from sdk.agent import Agent, AgentContext  # noqa: E402

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
