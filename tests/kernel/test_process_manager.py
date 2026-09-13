"""Tests for ProcessManager (§16-§17)."""
import pytest
from agent_os.kernel.process_manager import ProcessManager, ProcessNotFound, ProcessLimitReached
from agent_os.kernel.process_table import ProcessTable
from agent_os.kernel.state_machine import ProcessState
from agent_os.metrics.events import EventManager
from agent_os.config.settings import Settings
from sdk.agent import AgentContext
from agent_os.kernel.state_machine import StepStatus, AgentStepResult


class SimpleAgent:
    async def step(self, ctx):
        return AgentStepResult(status=StepStatus.COMPLETED)


@pytest.fixture
def components():
    settings = Settings()
    em = EventManager()
    pt = ProcessTable()
    pm = ProcessManager(pt, em, settings)
    return pm, pt, em, settings


@pytest.mark.asyncio
async def test_spawn(components):
    pm, _, _, _ = components
    p = await pm.spawn(SimpleAgent(), name="test")
    assert p.process_id is not None
    assert p.name == "test"
    assert p.state == ProcessState.READY  # spawn transitions to READY


@pytest.mark.asyncio
async def test_spawn_auto_assigns_pid(components):
    pm, _, _, _ = components
    p1 = await pm.spawn(SimpleAgent())
    p2 = await pm.spawn(SimpleAgent())
    assert p1.process_id != p2.process_id


@pytest.mark.asyncio
async def test_spawn_applies_overrides(components):
    pm, _, _, _ = components
    p = await pm.spawn(SimpleAgent(), priority=9, weight=3)
    assert p.priority == 9
    assert p.weight == 3


@pytest.mark.asyncio
async def test_get_existing(components):
    pm, _, _, _ = components
    p = await pm.spawn(SimpleAgent())
    fetched = await pm.get(p.process_id)
    assert fetched.process_id == p.process_id


@pytest.mark.asyncio
async def test_get_missing(components):
    pm, _, _, _ = components
    with pytest.raises(ProcessNotFound):
        await pm.get(999)


@pytest.mark.asyncio
async def test_list(components):
    pm, _, _, _ = components
    await pm.spawn(SimpleAgent())
    await pm.spawn(SimpleAgent())
    all_procs = await pm.list()
    assert len(all_procs) == 2


@pytest.mark.asyncio
async def test_list_by_state(components):
    pm, _, _, _ = components
    await pm.spawn(SimpleAgent())
    await pm.spawn(SimpleAgent())
    ready = await pm.list(state=ProcessState.READY)
    assert len(ready) == 2


@pytest.mark.asyncio
async def test_cancel(components):
    pm, _, _, _ = components
    p = await pm.spawn(SimpleAgent())
    await pm.cancel(p.process_id)
    assert p.state == ProcessState.CANCELLED


@pytest.mark.asyncio
async def test_terminate(components):
    pm, _, _, _ = components
    p = await pm.spawn(SimpleAgent())
    await pm.terminate(p.process_id)
    assert p.state == ProcessState.TERMINATED


@pytest.mark.asyncio
async def test_pause_and_resume(components):
    pm, _, _, _ = components
    p = await pm.spawn(SimpleAgent())
    await pm.set_state(p.process_id, ProcessState.RUNNING)
    await pm.pause(p.process_id)
    assert p.state == ProcessState.WAITING
    await pm.resume(p.process_id)
    assert p.state == ProcessState.READY


@pytest.mark.asyncio
async def test_remove_terminated(components):
    pm, _, _, _ = components
    p = await pm.spawn(SimpleAgent())
    await pm.terminate(p.process_id)
    removed = await pm.remove(p.process_id)
    assert removed is p


@pytest.mark.asyncio
async def test_remove_non_terminated_raises(components):
    pm, _, _, _ = components
    p = await pm.spawn(SimpleAgent())
    with pytest.raises(ValueError):
        await pm.remove(p.process_id)


@pytest.mark.asyncio
async def test_spawn_global_limit(components):
    pm, _, _, settings = components
    settings.system.max_processes = 2
    await pm.spawn(SimpleAgent())
    await pm.spawn(SimpleAgent())
    with pytest.raises(ProcessLimitReached):
        await pm.spawn(SimpleAgent())
