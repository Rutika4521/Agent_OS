"""Tests for CheckpointManager."""
import pytest
from agent_os.memory.checkpoint import CheckpointManager, Checkpoint
from agent_os.kernel.state_machine import ProcessState
from agent_os.metrics.events import EventManager, EventType


@pytest.fixture
def checkpoint_manager(event_manager):
    return CheckpointManager(event_manager)


@pytest.mark.asyncio
async def test_create_checkpoint_returns_checkpoint(checkpoint_manager):
    ck = await checkpoint_manager.create(
        process_id=1,
        process_state=ProcessState.READY,
        agent_state={"step": 3, "memory": "abc"},
    )
    assert isinstance(ck, Checkpoint)
    assert ck.process_id == 1
    assert ck.agent_state["step"] == 3


@pytest.mark.asyncio
async def test_create_emits_event(checkpoint_manager, event_manager):
    await checkpoint_manager.create(
        process_id=1,
        process_state=ProcessState.READY,
    )
    types = [e.event_type for e in await event_manager.get_history()]
    assert EventType.CHECKPOINT_CREATED in types


@pytest.mark.asyncio
async def test_restore_by_checkpoint_id(checkpoint_manager):
    ck = await checkpoint_manager.create(
        process_id=1,
        process_state=ProcessState.READY,
        agent_state={"v": 1},
    )
    restored = await checkpoint_manager.restore(ck.checkpoint_id)
    assert restored is not None
    assert restored.agent_state["v"] == 1


@pytest.mark.asyncio
async def test_restore_returns_none_for_unknown_id(checkpoint_manager):
    result = await checkpoint_manager.restore("nonexistent-id")
    assert result is None


@pytest.mark.asyncio
async def test_list_for_process(checkpoint_manager):
    await checkpoint_manager.create(process_id=1, process_state=ProcessState.READY, agent_state={"a": 1})
    await checkpoint_manager.create(process_id=1, process_state=ProcessState.READY, agent_state={"a": 2})
    await checkpoint_manager.create(process_id=2, process_state=ProcessState.READY, agent_state={"b": 1})
    records = await checkpoint_manager.list_for_process(process_id=1)
    assert len(records) == 2
    assert all(r.process_id == 1 for r in records)


@pytest.mark.asyncio
async def test_multiple_processes_isolated(checkpoint_manager):
    ck1 = await checkpoint_manager.create(process_id=1, process_state=ProcessState.READY, agent_state={"x": "p1"})
    ck2 = await checkpoint_manager.create(process_id=2, process_state=ProcessState.READY, agent_state={"x": "p2"})
    r1 = await checkpoint_manager.restore(ck1.checkpoint_id)
    r2 = await checkpoint_manager.restore(ck2.checkpoint_id)
    assert r1.agent_state["x"] == "p1"
    assert r2.agent_state["x"] == "p2"


@pytest.mark.asyncio
async def test_list_for_process_empty(checkpoint_manager):
    records = await checkpoint_manager.list_for_process(99)
    assert records == []
