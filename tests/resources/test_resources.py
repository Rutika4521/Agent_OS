"""Tests for ResourceManager (§26-§29)."""
import pytest
from agent_os.resources.manager import ResourceManager, ResourceLimitExceeded
from agent_os.resources.quota import ResourceLimits
from agent_os.resources.usage import ResourceUsage
from agent_os.kernel.agent_process import AgentProcess
from agent_os.config.settings import Settings
from unittest.mock import AsyncMock


def make_process(step_limit=100, token_limit=5000, llm_limit=50, tool_limit=20):
    return AgentProcess(
        process_id=1,
        agent=AsyncMock(),
        resource_limits=ResourceLimits(
            step_limit=step_limit, token_limit=token_limit,
            llm_call_limit=llm_limit, tool_call_limit=tool_limit,
            wall_time_limit=300, child_process_limit=10,
        ),
        resource_usage=ResourceUsage(),
    )


def test_can_execute_within_limits():
    rm = ResourceManager(Settings())
    p = make_process()
    assert rm.can_execute(p) is True


def test_can_execute_at_step_limit():
    rm = ResourceManager(Settings())
    p = make_process(step_limit=2)
    p.resource_usage.steps = 2
    assert rm.can_execute(p) is False


def test_consume_tokens():
    rm = ResourceManager(Settings())
    p = make_process(token_limit=100)
    rm.consume_tokens(p, 10, 20)
    assert p.resource_usage.input_tokens == 10
    assert p.resource_usage.output_tokens == 20
    assert p.resource_usage.total_tokens == 30


def test_token_limit_exceeded():
    rm = ResourceManager(Settings())
    p = make_process(token_limit=50)
    with pytest.raises(ResourceLimitExceeded):
        rm.consume_tokens(p, 30, 30)  # total = 60 > 50


def test_consume_step():
    rm = ResourceManager(Settings())
    p = make_process(step_limit=2)
    rm.consume_step(p)
    assert p.resource_usage.steps == 1
    rm.consume_step(p)
    assert p.resource_usage.steps == 2
    with pytest.raises(ResourceLimitExceeded):
        rm.consume_step(p)  # 3 > 2


def test_consume_llm_call_exceeded():
    rm = ResourceManager(Settings())
    p = make_process(llm_limit=1)
    rm.consume_llm_call(p)
    with pytest.raises(ResourceLimitExceeded):
        rm.consume_llm_call(p)


def test_consume_tool_call_exceeded():
    rm = ResourceManager(Settings())
    p = make_process(tool_limit=1)
    rm.consume_tool_call(p)
    with pytest.raises(ResourceLimitExceeded):
        rm.consume_tool_call(p)


def test_release_resources():
    rm = ResourceManager(Settings())
    p = make_process()
    rm.consume_step(p)
    rm.consume_tokens(p, 10, 10)
    rm.release_resources(p)
    assert p.resource_usage.steps == 0
    assert p.resource_usage.total_tokens == 0


def test_wall_time_exceeded():
    rm = ResourceManager(Settings())
    p = make_process()
    p.resource_limits.wall_time_limit = 10.0
    p.resource_usage.execution_time = 15.0
    assert rm.check_wall_time(p) is True
