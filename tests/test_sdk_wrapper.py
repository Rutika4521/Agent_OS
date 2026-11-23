"""
Tests for sdk/wrapper.py — AutoWrapper
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]   # tests/ → project root
sys.path.insert(0, str(_ROOT / "src"))         # for `agent_os` package
sys.path.insert(0, str(_ROOT))                 # for `sdk` package

import pytest
from sdk.wrapper import AutoWrapper
from sdk.agent import AgentContext
from agent_os.kernel.state_machine import AgentStepResult, StepStatus


# ── Helper agents ─────────────────────────────────────────────────────────────

class RunAgent:
    """Standard agent with async run()."""
    def __init__(self):
        self.called_with = []

    async def run(self, topic: str = "default") -> str:
        self.called_with.append(topic)
        return f"result:{topic}"


class ExecuteAgent:
    """Agent using execute() instead of run()."""
    async def execute(self, x: int = 0) -> int:
        return x * 2


class CallableAgent:
    """Callable agent using __call__."""
    async def __call__(self) -> str:
        return "callable-result"


class SyncAgent:
    """Agent with a synchronous run() method."""
    async def run(self) -> str:
        return "sync-result"


class BrokenAgent:
    """Agent whose run() always raises."""
    async def run(self) -> str:
        raise ValueError("intentional failure")


class NoMethodAgent:
    """Agent with no detectable step method."""
    def helper(self):
        pass


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.fixture
def ctx():
    return AgentContext(process_id=1)


class TestAutoDetect:
    def test_detects_run(self):
        w = AutoWrapper(RunAgent())
        assert w._method_name == "run"

    def test_detects_execute(self):
        w = AutoWrapper(ExecuteAgent())
        assert w._method_name == "execute"

    def test_detects_call(self):
        w = AutoWrapper(CallableAgent())
        assert w._method_name == "__call__"

    def test_explicit_method_override(self):
        agent = RunAgent()
        w = AutoWrapper(agent, method="run")
        assert w._method_name == "run"

    def test_missing_method_raises(self):
        with pytest.raises(AttributeError, match="has no method"):
            AutoWrapper(RunAgent(), method="nonexistent")

    def test_no_detectable_method_raises(self):
        with pytest.raises(AttributeError, match="Cannot auto-detect"):
            AutoWrapper(NoMethodAgent())


class TestSingleStep:
    @pytest.mark.asyncio
    async def test_single_step_returns_completed(self, ctx):
        w = AutoWrapper(RunAgent(), steps=[{"args": ["hello"]}])
        result = await w.step(ctx)
        assert result.status == StepStatus.COMPLETED
        assert result.output == "result:hello"

    @pytest.mark.asyncio
    async def test_default_no_args_single_step(self, ctx):
        w = AutoWrapper(RunAgent())
        result = await w.step(ctx)
        assert result.status == StepStatus.COMPLETED
        assert result.output == "result:default"

    @pytest.mark.asyncio
    async def test_callable_agent(self, ctx):
        w = AutoWrapper(CallableAgent())
        result = await w.step(ctx)
        assert result.status == StepStatus.COMPLETED
        assert result.output == "callable-result"

    @pytest.mark.asyncio
    async def test_sync_agent_method(self, ctx):
        w = AutoWrapper(SyncAgent())
        result = await w.step(ctx)
        assert result.status == StepStatus.COMPLETED
        assert result.output == "sync-result"


class TestMultiStep:
    @pytest.mark.asyncio
    async def test_multi_step_continue_then_completed(self, ctx):
        w = AutoWrapper(RunAgent(), steps=[
            {"args": ["A"]},
            {"args": ["B"]},
            {"args": ["C"]},
        ])
        r1 = await w.step(ctx)
        assert r1.status == StepStatus.CONTINUE
        assert r1.output == "result:A"

        r2 = await w.step(ctx)
        assert r2.status == StepStatus.CONTINUE
        assert r2.output == "result:B"

        r3 = await w.step(ctx)
        assert r3.status == StepStatus.COMPLETED
        assert r3.output == "result:C"

    @pytest.mark.asyncio
    async def test_extra_step_after_completion(self, ctx):
        w = AutoWrapper(RunAgent(), steps=[{"args": ["X"]}])
        await w.step(ctx)          # COMPLETED
        result = await w.step(ctx) # Called again
        assert result.status == StepStatus.COMPLETED
        assert result.output == "result:X"  # last_output preserved

    @pytest.mark.asyncio
    async def test_step_index_increments(self, ctx):
        w = AutoWrapper(RunAgent(), steps=[{"args": ["a"]}, {"args": ["b"]}])
        assert w.step_index == 0
        await w.step(ctx)
        assert w.step_index == 1
        await w.step(ctx)
        assert w.step_index == 2


class TestKwargs:
    @pytest.mark.asyncio
    async def test_kwargs_passed(self, ctx):
        agent = RunAgent()
        w = AutoWrapper(agent, steps=[{"kwargs": {"topic": "science"}}])
        result = await w.step(ctx)
        assert result.output == "result:science"
        assert agent.called_with == ["science"]


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_exception_returns_failed(self, ctx):
        w = AutoWrapper(BrokenAgent())
        result = await w.step(ctx)
        assert result.status == StepStatus.FAILED
        assert result.output is None
        assert "intentional failure" in result.error

    @pytest.mark.asyncio
    async def test_custom_on_result(self, ctx):
        def always_wait(result, idx):
            return StepStatus.WAIT

        w = AutoWrapper(RunAgent(), on_result=always_wait)
        result = await w.step(ctx)
        assert result.status == StepStatus.WAIT


class TestProperties:
    def test_inner_returns_original_agent(self):
        agent = RunAgent()
        w = AutoWrapper(agent)
        assert w.inner is agent

    def test_step_index_starts_at_zero(self):
        w = AutoWrapper(RunAgent())
        assert w.step_index == 0
