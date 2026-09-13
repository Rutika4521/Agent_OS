import pytest
from dataclasses import dataclass
from typing import Any, Optional

@dataclass
class AgentStepResult:
    is_done: bool
    output: Any = None
    error: Optional[str] = None

class SimpleAgent:
    def step(self, context=None):
        return AgentStepResult(is_done=True, output="success")

class FailingAgent:
    def step(self, context=None):
        raise ValueError("Agent failed")

class WaitingAgent:
    def step(self, context=None):
        return AgentStepResult(is_done=False, output="waiting")

class InfiniteAgent:
    def step(self, context=None):
        return AgentStepResult(is_done=False, output="working")

@pytest.fixture
def simple_agent():
    return SimpleAgent()

@pytest.fixture
def failing_agent():
    return FailingAgent()

@pytest.fixture
def waiting_agent():
    return WaitingAgent()

@pytest.fixture
def infinite_agent():
    return InfiniteAgent()
