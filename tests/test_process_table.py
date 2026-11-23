"""Tests for ProcessTable."""
import pytest
import pytest_asyncio
from agent_os.kernel.process_table import ProcessTable
from agent_os.kernel.agent_process import AgentProcess
from agent_os.kernel.state_machine import ProcessState, AgentStepResult, StepStatus
from agent_os.resources.quota import ResourceLimits
from agent_os.resources.usage import ResourceUsage


def _make_process(pid: int, state: ProcessState = ProcessState.READY) -> AgentProcess:
    class A:
        async def step(self, ctx): return AgentStepResult(status=StepStatus.COMPLETED)
    return AgentProcess(
        process_id=pid,
        agent=A(),
        name=f"p{pid}",
        state=state,
        priority=5,
        resource_limits=ResourceLimits(),
        resource_usage=ResourceUsage(),
    )


@pytest.mark.asyncio
async def test_allocate_pid_increments():
    pt = ProcessTable()
    p1 = await pt.allocate_pid()
    p2 = await pt.allocate_pid()
    assert p2 == p1 + 1


@pytest.mark.asyncio
async def test_insert_and_get():
    pt = ProcessTable()
    proc = _make_process(1)
    await pt.insert(proc)
    fetched = await pt.get(1)
    assert fetched is proc


@pytest.mark.asyncio
async def test_get_nonexistent_returns_none():
    pt = ProcessTable()
    assert await pt.get(999) is None


@pytest.mark.asyncio
async def test_remove_existing():
    pt = ProcessTable()
    proc = _make_process(1)
    await pt.insert(proc)
    removed = await pt.remove(1)
    assert removed is proc
    assert await pt.get(1) is None


@pytest.mark.asyncio
async def test_remove_nonexistent_returns_none():
    pt = ProcessTable()
    assert await pt.remove(99) is None


@pytest.mark.asyncio
async def test_list_all():
    pt = ProcessTable()
    for pid in [1, 2, 3]:
        await pt.insert(_make_process(pid))
    all_procs = await pt.list_all()
    assert len(all_procs) == 3


@pytest.mark.asyncio
async def test_get_by_state():
    pt = ProcessTable()
    await pt.insert(_make_process(1, ProcessState.READY))
    await pt.insert(_make_process(2, ProcessState.WAITING))
    await pt.insert(_make_process(3, ProcessState.READY))
    ready = await pt.get_by_state(ProcessState.READY)
    assert len(ready) == 2


@pytest.mark.asyncio
async def test_get_runnable():
    pt = ProcessTable()
    await pt.insert(_make_process(1, ProcessState.READY))
    await pt.insert(_make_process(2, ProcessState.WAITING))
    runnable = await pt.get_runnable()
    assert len(runnable) == 1
    assert runnable[0].process_id == 1


@pytest.mark.asyncio
async def test_count():
    pt = ProcessTable()
    assert await pt.count() == 0
    await pt.insert(_make_process(1))
    await pt.insert(_make_process(2))
    assert await pt.count() == 2


@pytest.mark.asyncio
async def test_count_by_state():
    pt = ProcessTable()
    await pt.insert(_make_process(1, ProcessState.READY))
    await pt.insert(_make_process(2, ProcessState.RUNNING))
    await pt.insert(_make_process(3, ProcessState.READY))
    assert await pt.count_by_state(ProcessState.READY) == 2
    assert await pt.count_by_state(ProcessState.RUNNING) == 1


@pytest.mark.asyncio
async def test_get_children():
    pt = ProcessTable()
    parent = _make_process(1)
    child1 = _make_process(2)
    child2 = _make_process(3)
    child1.parent_process_id = 1
    child2.parent_process_id = 1
    await pt.insert(parent)
    await pt.insert(child1)
    await pt.insert(child2)
    children = await pt.get_children(1)
    assert len(children) == 2
