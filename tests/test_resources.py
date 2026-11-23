"""Tests for ResourceManager — limits, consumption, exceptions."""
import pytest
from agent_os.resources.manager import ResourceManager, ResourceLimitExceeded
from agent_os.resources.quota import ResourceLimits
from agent_os.resources.usage import ResourceUsage
from agent_os.kernel.agent_process import AgentProcess
from agent_os.kernel.state_machine import ProcessState, AgentStepResult, StepStatus


def _make_proc(token_limit=1000, step_limit=100, llm_call_limit=50):
    class A:
        async def step(self, ctx): return AgentStepResult(status=StepStatus.COMPLETED)
    limits = ResourceLimits(
        token_limit=token_limit,
        step_limit=step_limit,
        llm_call_limit=llm_call_limit,
    )
    return AgentProcess(
        process_id=1,
        agent=A(),
        name="p",
        state=ProcessState.READY,
        priority=5,
        resource_limits=limits,
        resource_usage=ResourceUsage(),
    )


@pytest.fixture
def rm(settings):
    return ResourceManager(settings)


def test_can_execute_fresh_process(rm):
    proc = _make_proc()
    assert rm.can_execute(proc) is True


def test_can_execute_false_when_steps_exceeded(rm):
    proc = _make_proc(step_limit=3)
    proc.resource_usage.steps = 3
    assert rm.can_execute(proc) is False


def test_can_execute_false_when_tokens_exceeded(rm):
    proc = _make_proc(token_limit=100)
    proc.resource_usage.total_tokens = 100
    assert rm.can_execute(proc) is False


def test_consume_step_increments_counter(rm):
    proc = _make_proc()
    rm.consume_step(proc)
    assert proc.resource_usage.steps == 1


def test_consume_step_raises_when_limit_exceeded(rm):
    proc = _make_proc(step_limit=1)
    rm.consume_step(proc)
    with pytest.raises(ResourceLimitExceeded):
        rm.consume_step(proc)


def test_consume_tokens_increments_counter(rm):
    proc = _make_proc()
    rm.consume_tokens(proc, 30, 20)
    assert proc.resource_usage.total_tokens == 50


def test_consume_tokens_raises_when_limit_exceeded(rm):
    proc = _make_proc(token_limit=10)
    with pytest.raises(ResourceLimitExceeded):
        rm.consume_tokens(proc, 100, 100)


def test_consume_llm_call_increments(rm):
    proc = _make_proc()
    rm.consume_llm_call(proc)
    assert proc.resource_usage.llm_calls == 1


def test_consume_llm_call_raises_when_exceeded(rm):
    proc = _make_proc(llm_call_limit=1)
    rm.consume_llm_call(proc)
    with pytest.raises(ResourceLimitExceeded):
        rm.consume_llm_call(proc)


def test_release_resources_resets_usage(rm):
    proc = _make_proc()
    proc.resource_usage.steps = 5
    proc.resource_usage.total_tokens = 100
    rm.release_resources(proc)
    assert proc.resource_usage.steps == 0
    assert proc.resource_usage.total_tokens == 0


def test_resource_limits_from_config():
    from agent_os.config.settings import Settings
    s = Settings()
    limits = ResourceLimits.from_config(s.process_defaults.resources)
    assert limits.token_limit > 0
    assert limits.step_limit > 0
