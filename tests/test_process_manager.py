"""Tests for ProcessManager — spawn, lifecycle, cancel, terminate, pause, resume."""
import pytest
from agent_os.kernel.state_machine import ProcessState, AgentStepResult, StepStatus
from agent_os.kernel.process_manager import ProcessLimitReached, ProcessNotFound
from tests.conftest import DummyAgent, ContinueAgent


@pytest.mark.asyncio
async def test_spawn_returns_process_in_ready_state(process_manager):
    agent = DummyAgent()
    proc = await process_manager.spawn(agent, name="test", priority=5)
    assert proc.state == ProcessState.READY
    assert proc.name == "test"
    assert proc.priority == 5
    assert proc.process_id >= 1


@pytest.mark.asyncio
async def test_spawn_auto_assigns_name(process_manager):
    proc = await process_manager.spawn(DummyAgent())
    assert proc.name.startswith("process-")


@pytest.mark.asyncio
async def test_spawn_invalid_agent_raises(process_manager):
    with pytest.raises(TypeError):
        await process_manager.spawn(object())


@pytest.mark.asyncio
async def test_spawn_emits_created_and_ready_events(process_manager, event_manager):
    await process_manager.spawn(DummyAgent(), name="x")
    types = [e.event_type.value for e in await event_manager.get_history()]
    assert "PROCESS_CREATED" in types
    assert "PROCESS_READY" in types


@pytest.mark.asyncio
async def test_get_existing_process(process_manager):
    proc = await process_manager.spawn(DummyAgent())
    fetched = await process_manager.get(proc.process_id)
    assert fetched.process_id == proc.process_id


@pytest.mark.asyncio
async def test_get_nonexistent_raises(process_manager):
    with pytest.raises(ProcessNotFound):
        await process_manager.get(9999)


@pytest.mark.asyncio
async def test_list_all_processes(process_manager):
    await process_manager.spawn(DummyAgent())
    await process_manager.spawn(DummyAgent())
    procs = await process_manager.list()
    assert len(procs) == 2


@pytest.mark.asyncio
async def test_list_filtered_by_state(process_manager):
    await process_manager.spawn(DummyAgent())
    await process_manager.spawn(DummyAgent())
    ready = await process_manager.list(state=ProcessState.READY)
    assert len(ready) == 2
    running = await process_manager.list(state=ProcessState.RUNNING)
    assert len(running) == 0


@pytest.mark.asyncio
async def test_set_state_valid_transition(process_manager):
    proc = await process_manager.spawn(DummyAgent())
    await process_manager.set_state(proc.process_id, ProcessState.RUNNING)
    updated = await process_manager.get(proc.process_id)
    assert updated.state == ProcessState.RUNNING


@pytest.mark.asyncio
async def test_set_state_invalid_transition_raises(process_manager):
    from agent_os.kernel.state_machine import InvalidStateTransition
    proc = await process_manager.spawn(DummyAgent())
    with pytest.raises(InvalidStateTransition):
        await process_manager.set_state(proc.process_id, ProcessState.COMPLETED)


@pytest.mark.asyncio
async def test_cancel_ready_process(process_manager):
    proc = await process_manager.spawn(DummyAgent())
    await process_manager.cancel(proc.process_id)
    updated = await process_manager.get(proc.process_id)
    assert updated.state == ProcessState.CANCELLED


@pytest.mark.asyncio
async def test_terminate_cancelled_process(process_manager):
    proc = await process_manager.spawn(DummyAgent())
    await process_manager.cancel(proc.process_id)
    await process_manager.terminate(proc.process_id)
    updated = await process_manager.get(proc.process_id)
    assert updated.state == ProcessState.TERMINATED


@pytest.mark.asyncio
async def test_pause_running_process(process_manager):
    proc = await process_manager.spawn(DummyAgent())
    await process_manager.set_state(proc.process_id, ProcessState.RUNNING)
    await process_manager.pause(proc.process_id)
    updated = await process_manager.get(proc.process_id)
    assert updated.state == ProcessState.WAITING


@pytest.mark.asyncio
async def test_resume_waiting_process(process_manager):
    proc = await process_manager.spawn(DummyAgent())
    await process_manager.set_state(proc.process_id, ProcessState.RUNNING)
    await process_manager.set_state(proc.process_id, ProcessState.WAITING)
    await process_manager.resume(proc.process_id)
    updated = await process_manager.get(proc.process_id)
    assert updated.state == ProcessState.READY


@pytest.mark.asyncio
async def test_remove_terminated_process(process_manager):
    proc = await process_manager.spawn(DummyAgent())
    await process_manager.cancel(proc.process_id)
    await process_manager.terminate(proc.process_id)
    removed = await process_manager.remove(proc.process_id)
    assert removed is not None
    with pytest.raises(ProcessNotFound):
        await process_manager.get(proc.process_id)


@pytest.mark.asyncio
async def test_remove_non_terminated_raises(process_manager):
    proc = await process_manager.spawn(DummyAgent())
    with pytest.raises(ValueError):
        await process_manager.remove(proc.process_id)


@pytest.mark.asyncio
async def test_multiple_pids_are_unique(process_manager):
    procs = [await process_manager.spawn(DummyAgent()) for _ in range(5)]
    pids = [p.process_id for p in procs]
    assert len(set(pids)) == 5


@pytest.mark.asyncio
async def test_spawn_sets_resource_limits(process_manager):
    proc = await process_manager.spawn(DummyAgent())
    assert proc.resource_limits is not None
    assert proc.resource_limits.token_limit > 0
