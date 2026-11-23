"""
Tests for sdk/kernel.py — Kernel bootstrap
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]   # tests/ → project root
sys.path.insert(0, str(_ROOT / "src"))         # for `agent_os` package
sys.path.insert(0, str(_ROOT))                 # for `sdk` package

import pytest
import asyncio
from sdk.kernel import Kernel, KernelNotBootedError
from sdk.registry import register, clear_registry
from sdk.agent import AgentContext
from agent_os.kernel.state_machine import AgentStepResult, StepStatus, ProcessState
from agent_os.config.settings import Settings


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_registry():
    clear_registry()
    yield
    clear_registry()


@pytest.fixture
async def kernel():
    k = Kernel()
    await k.boot()
    yield k
    await k.shutdown()


# ── Minimal one-step agent for testing ────────────────────────────────────────

class OneShotAgent:
    """Completes in one step."""
    def __init__(self, label: str = ""):
        self.label = label
        self.ran = False

    async def step(self, ctx: AgentContext) -> AgentStepResult:
        self.ran = True
        return AgentStepResult(status=StepStatus.COMPLETED, output=self.label)


class TwoStepAgent:
    """Needs two ticks to complete."""
    def __init__(self):
        self.tick = 0

    async def step(self, ctx: AgentContext) -> AgentStepResult:
        self.tick += 1
        if self.tick >= 2:
            return AgentStepResult(status=StepStatus.COMPLETED, output="done")
        return AgentStepResult(status=StepStatus.CONTINUE, output="continuing")


class FailingAgent:
    """Always raises an exception in step()."""
    async def step(self, ctx: AgentContext) -> AgentStepResult:
        raise RuntimeError("Deliberate test failure")


# ── Boot / shutdown tests ─────────────────────────────────────────────────────

class TestBoot:
    @pytest.mark.asyncio
    async def test_boot_sets_booted(self):
        k = Kernel()
        assert not k._booted
        await k.boot()
        assert k._booted
        await k.shutdown()

    @pytest.mark.asyncio
    async def test_boot_idempotent(self):
        k = Kernel()
        await k.boot()
        await k.boot()  # second call should be no-op
        assert k._booted
        await k.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_resets_booted(self):
        k = Kernel()
        await k.boot()
        await k.shutdown()
        assert not k._booted

    @pytest.mark.asyncio
    async def test_shutdown_before_boot_is_safe(self):
        k = Kernel()
        await k.shutdown()  # should not raise

    @pytest.mark.asyncio
    async def test_custom_settings_accepted(self):
        settings = Settings()
        k = Kernel(settings=settings)
        await k.boot()
        assert k.settings is settings
        await k.shutdown()


class TestSubsystemProperties:
    @pytest.mark.asyncio
    async def test_pm_accessible(self, kernel):
        from agent_os.kernel.process_manager import ProcessManager
        assert isinstance(kernel.pm, ProcessManager)

    @pytest.mark.asyncio
    async def test_ipc_accessible(self, kernel):
        from agent_os.ipc.ipc_manager import IPCManager
        assert isinstance(kernel.ipc, IPCManager)

    @pytest.mark.asyncio
    async def test_events_accessible(self, kernel):
        from agent_os.metrics.events import EventManager
        assert isinstance(kernel.events, EventManager)

    @pytest.mark.asyncio
    async def test_supervisor_accessible(self, kernel):
        from agent_os.supervisor.supervisor import Supervisor
        assert isinstance(kernel.supervisor, Supervisor)

    @pytest.mark.asyncio
    async def test_metrics_accessible(self, kernel):
        from agent_os.metrics.collector import MetricsCollector
        assert isinstance(kernel.metrics, MetricsCollector)

    @pytest.mark.asyncio
    async def test_property_before_boot_raises(self):
        k = Kernel()
        with pytest.raises(KernelNotBootedError):
            _ = k.pm

    @pytest.mark.asyncio
    async def test_ipc_before_boot_raises(self):
        k = Kernel()
        with pytest.raises(KernelNotBootedError):
            _ = k.ipc


class TestSpawn:
    @pytest.mark.asyncio
    async def test_spawn_single_agent(self, kernel):
        agent = OneShotAgent("hello")
        proc = await kernel.spawn(agent, name="Test")
        assert proc.name == "Test"
        assert proc.state == ProcessState.READY

    @pytest.mark.asyncio
    async def test_spawn_returns_agent_process(self, kernel):
        from agent_os.kernel.agent_process import AgentProcess
        proc = await kernel.spawn(OneShotAgent())
        assert isinstance(proc, AgentProcess)

    @pytest.mark.asyncio
    async def test_spawn_with_priority(self, kernel):
        proc = await kernel.spawn(OneShotAgent(), priority=9)
        assert proc.priority == 9

    @pytest.mark.asyncio
    async def test_spawn_without_step_raises(self, kernel):
        class BadAgent:
            pass
        with pytest.raises(TypeError):
            await kernel.spawn(BadAgent())

    @pytest.mark.asyncio
    async def test_spawn_before_boot_raises(self):
        k = Kernel()
        with pytest.raises(KernelNotBootedError):
            await k.spawn(OneShotAgent())


class TestSpawnRegistered:
    @pytest.mark.asyncio
    async def test_spawn_registered_empty_registry(self, kernel):
        processes = await kernel.spawn_registered()
        assert processes == []

    @pytest.mark.asyncio
    async def test_spawn_registered_single_agent(self, kernel):
        @register(name="Reg1")
        class Reg1:
            async def run(self) -> str:
                return "r1"

        processes = await kernel.spawn_registered()
        assert len(processes) == 1
        assert processes[0].name == "Reg1"

    @pytest.mark.asyncio
    async def test_spawn_registered_multiple_agents(self, kernel):
        @register(name="Alpha", priority=8)
        class AlphaAgent:
            async def run(self) -> str:
                return "alpha"

        @register(name="Beta", priority=4)
        class BetaAgent:
            async def run(self) -> str:
                return "beta"

        processes = await kernel.spawn_registered()
        assert len(processes) == 2
        names = {p.name for p in processes}
        assert names == {"Alpha", "Beta"}

    @pytest.mark.asyncio
    async def test_spawn_registered_priority_applied(self, kernel):
        @register(name="HighPri", priority=9)
        class HighPriAgent:
            async def run(self) -> str:
                return "high"

        processes = await kernel.spawn_registered()
        assert processes[0].priority == 9

    @pytest.mark.asyncio
    async def test_spawn_registered_with_steps(self, kernel):
        @register(name="Stepped", steps=[{"args": ["x"]}, {"args": ["y"]}])
        class SteppedAgent:
            async def run(self, val: str) -> str:
                return val

        processes = await kernel.spawn_registered()
        assert len(processes) == 1

    @pytest.mark.asyncio
    async def test_spawn_registered_with_init_args(self, kernel):
        @register(name="InitAgent", init_args=["hello"])
        class InitAgent:
            def __init__(self, greeting: str):
                self.greeting = greeting

            async def run(self) -> str:
                return self.greeting

        processes = await kernel.spawn_registered()
        assert len(processes) == 1


class TestRunLoop:
    @pytest.mark.asyncio
    async def test_run_empty_process_table(self, kernel):
        # Should return immediately
        await kernel.run()

    @pytest.mark.asyncio
    async def test_run_completes_one_shot_agent(self, kernel):
        agent = OneShotAgent("ok")
        proc = await kernel.spawn(agent, name="OneShot")
        await kernel.run()
        assert agent.ran

    @pytest.mark.asyncio
    async def test_run_completes_two_step_agent(self, kernel):
        agent = TwoStepAgent()
        await kernel.spawn(agent, name="TwoStep")
        await kernel.run()
        assert agent.tick == 2

    @pytest.mark.asyncio
    async def test_run_completes_multiple_agents(self, kernel):
        agents = [OneShotAgent(f"agent-{i}") for i in range(3)]
        for i, a in enumerate(agents):
            await kernel.spawn(a, name=f"A{i}")
        await kernel.run()
        assert all(a.ran for a in agents)

    @pytest.mark.asyncio
    async def test_run_handles_failing_agent(self, kernel):
        """A failing agent should not crash the run loop."""
        failing = FailingAgent()
        ok = OneShotAgent("ok")
        await kernel.spawn(failing, name="Failing")
        await kernel.spawn(ok, name="OK")
        await kernel.run()
        # The ok agent should still complete
        assert ok.ran

    @pytest.mark.asyncio
    async def test_run_with_registered_agents(self, kernel):
        executed = []

        @register(name="TrackedAgent")
        class TrackedAgent:
            async def run(self) -> str:
                executed.append("ran")
                return "done"

        await kernel.spawn_registered()
        await kernel.run()
        assert executed == ["ran"]

    @pytest.mark.asyncio
    async def test_run_respects_max_steps_safety(self, kernel):
        """max_steps should prevent infinite loops."""
        class InfiniteAgent:
            async def step(self, ctx: AgentContext) -> AgentStepResult:
                return AgentStepResult(status=StepStatus.CONTINUE, output=None)

        await kernel.spawn(InfiniteAgent(), name="Infinite")
        # With max_steps=5 it should stop after 5 ticks, not loop forever
        await kernel.run(max_steps=5)  # no assertion needed — just must not hang
