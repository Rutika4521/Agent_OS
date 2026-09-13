"""Tests for ProcessTable."""

import pytest
from agent_os.kernel.process_table import ProcessTable
from agent_os.kernel.agent_process import AgentProcess
from agent_os.kernel.state_machine import ProcessState
from unittest.mock import AsyncMock


def make_process(pid, state=ProcessState.CREATED, parent_pid=None):
    """Create a minimal AgentProcess for testing."""
    agent = AsyncMock()
    return AgentProcess(
        process_id=pid,
        agent=agent,
        name=f"test-{pid}",
        state=state,
        parent_process_id=parent_pid,
    )


@pytest.mark.asyncio
async def test_allocate_pid_sequential():
    pt = ProcessTable()
    pid1 = await pt.allocate_pid()
    pid2 = await pt.allocate_pid()
    assert pid1 == 1
    assert pid2 == 2
    assert pid1 != pid2


@pytest.mark.asyncio
async def test_insert_and_get():
    pt = ProcessTable()
    process = make_process(1)
    await pt.insert(process)
    result = await pt.get(1)
    assert result is process


@pytest.mark.asyncio
async def test_insert_duplicate_raises():
    pt = ProcessTable()
    process = make_process(1)
    await pt.insert(process)
    with pytest.raises(ValueError):
        await pt.insert(process)


@pytest.mark.asyncio
async def test_remove():
    pt = ProcessTable()
    process = make_process(1)
    await pt.insert(process)
    removed = await pt.remove(1)
    assert removed is process
    assert await pt.get(1) is None


@pytest.mark.asyncio
async def test_list_all():
    pt = ProcessTable()
    await pt.insert(make_process(1))
    await pt.insert(make_process(2))
    all_procs = await pt.list_all()
    assert len(all_procs) == 2


@pytest.mark.asyncio
async def test_get_by_state():
    pt = ProcessTable()
    await pt.insert(make_process(1, state=ProcessState.CREATED))
    await pt.insert(make_process(2, state=ProcessState.READY))
    ready = await pt.get_by_state(ProcessState.READY)
    assert len(ready) == 1
    assert ready[0].process_id == 2


@pytest.mark.asyncio
async def test_get_runnable():
    pt = ProcessTable()
    await pt.insert(make_process(1, state=ProcessState.CREATED))
    await pt.insert(make_process(2, state=ProcessState.READY))
    await pt.insert(make_process(3, state=ProcessState.READY))
    runnable = await pt.get_runnable()
    assert len(runnable) == 2


@pytest.mark.asyncio
async def test_get_active():
    pt = ProcessTable()
    await pt.insert(make_process(1, state=ProcessState.READY))
    await pt.insert(make_process(2, state=ProcessState.TERMINATED))
    active = await pt.get_active()
    assert len(active) == 1
    assert active[0].process_id == 1


@pytest.mark.asyncio
async def test_count():
    pt = ProcessTable()
    assert await pt.count() == 0
    await pt.insert(make_process(1))
    assert await pt.count() == 1


@pytest.mark.asyncio
async def test_get_children():
    pt = ProcessTable()
    await pt.insert(make_process(1))
    await pt.insert(make_process(2, parent_pid=1))
    await pt.insert(make_process(3, parent_pid=1))
    children = await pt.get_children(1)
    assert len(children) == 2
    assert await pt.count_children(1) == 2
