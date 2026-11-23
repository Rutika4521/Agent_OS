"""
Shared pytest fixtures for Agent-OS tests.
All agents here match the real Agent protocol (async step returning AgentStepResult).
"""
import os
import sys
from pathlib import Path

# Ensure src/ and project root are on sys.path
# src/  → for `import agent_os` (kernel package)
# ROOT  → for `import sdk` (sdk is a sub-package at project root)
_ROOT = Path(__file__).resolve().parent.parent
_SRC = str(_ROOT / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest
from agent_os.config.settings import Settings, reset_settings
from agent_os.metrics.events import EventManager
from agent_os.kernel.process_table import ProcessTable
from agent_os.kernel.process_manager import ProcessManager
from agent_os.kernel.state_machine import AgentStepResult, StepStatus


@pytest.fixture(autouse=True)
def reset_global_settings():
    """Reset settings singleton before every test."""
    reset_settings()
    yield
    reset_settings()


@pytest.fixture
def settings():
    return Settings()


@pytest.fixture
def event_manager():
    return EventManager()


@pytest.fixture
def process_table():
    return ProcessTable()


@pytest.fixture
def process_manager(process_table, event_manager, settings):
    return ProcessManager(process_table, event_manager, settings)


# ── Reusable agent stubs ──────────────────────────────────────────────────────

class DummyAgent:
    """Minimal agent that always completes on first step."""
    async def step(self, ctx):
        return AgentStepResult(status=StepStatus.COMPLETED, output="done")


class ContinueAgent:
    """Agent that always returns CONTINUE (runs forever unless preempted)."""
    async def step(self, ctx):
        return AgentStepResult(status=StepStatus.CONTINUE, output="working")


class WaitAgent:
    """Agent that returns WAIT on first step, COMPLETED on second."""
    def __init__(self):
        self._calls = 0

    async def step(self, ctx):
        self._calls += 1
        if self._calls == 1:
            return AgentStepResult(status=StepStatus.WAIT, output="waiting")
        return AgentStepResult(status=StepStatus.COMPLETED, output="done")


class FailingAgent:
    """Agent that raises on first step."""
    async def step(self, ctx):
        raise RuntimeError("Agent crashed")


@pytest.fixture
def dummy_agent():
    return DummyAgent()


@pytest.fixture
def continue_agent():
    return ContinueAgent()


@pytest.fixture
def wait_agent():
    return WaitAgent()


@pytest.fixture
def failing_agent():
    return FailingAgent()
