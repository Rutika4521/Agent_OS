"""Tests for Memory/Context Management (§30-§35)."""
import pytest
from agent_os.memory.context_manager import ContextManager
from agent_os.memory.checkpoint import CheckpointManager
from agent_os.kernel.state_machine import ProcessState
from agent_os.metrics.events import EventManager
from agent_os.config.settings import Settings


@pytest.mark.asyncio
async def test_create_context():
    cm = ContextManager(Settings(), EventManager())
    ctx_id = await cm.create(process_id=1)
    assert ctx_id is not None


@pytest.mark.asyncio
async def test_add_and_get_page():
    cm = ContextManager(Settings(), EventManager())
    ctx_id = await cm.create(process_id=1)
    page = await cm.add_page(ctx_id, process_id=1, content="test data")
    assert page is not None
    assert page.content == "test data"
    assert page.loaded is True

    fetched = await cm.get_page(ctx_id, page.index)
    assert fetched is not None
    assert fetched.content == "test data"


@pytest.mark.asyncio
async def test_swap_out_and_in():
    cm = ContextManager(Settings(), EventManager())
    ctx_id = await cm.create(process_id=1)
    page = await cm.add_page(ctx_id, process_id=1, content="swappable")

    # Swap out
    await cm.swap_out(ctx_id, page.index)
    # Note: get_page auto-swaps in, so check internal state directly
    raw_pages = cm._contexts[ctx_id]
    assert raw_pages[page.index].loaded is False

    # Swap in
    await cm.swap_in(ctx_id, page.index)
    restored = await cm.get_page(ctx_id, page.index)
    assert restored.loaded is True
    assert restored.content == "swappable"


@pytest.mark.asyncio
async def test_update_page():
    cm = ContextManager(Settings(), EventManager())
    ctx_id = await cm.create(process_id=1)
    page = await cm.add_page(ctx_id, process_id=1, content="original")
    await cm.update_page(ctx_id, page.index, "updated")
    fetched = await cm.get_page(ctx_id, page.index)
    assert fetched.content == "updated"


@pytest.mark.asyncio
async def test_remove_context():
    cm = ContextManager(Settings(), EventManager())
    ctx_id = await cm.create(process_id=1)
    await cm.add_page(ctx_id, process_id=1, content="data")
    await cm.remove(ctx_id)
    # After removal, get_page should return None
    page = await cm.get_page(ctx_id, 0)
    assert page is None


@pytest.mark.asyncio
async def test_checkpoint_create_and_restore():
    ckpt = CheckpointManager(EventManager())
    cp = await ckpt.create(
        process_id=1,
        process_state=ProcessState.RUNNING,
        context_id="ctx-1",
        context_version=1,
        resource_usage={"steps": 5},
        agent_state={"key": "value"},
    )
    assert cp.checkpoint_id is not None
    assert cp.process_id == 1

    restored = await ckpt.restore(cp.checkpoint_id)
    assert restored is not None
    assert restored.process_id == 1
    assert restored.agent_state == {"key": "value"}


@pytest.mark.asyncio
async def test_checkpoint_list_for_process():
    ckpt = CheckpointManager()
    await ckpt.create(process_id=1, process_state=ProcessState.RUNNING)
    await ckpt.create(process_id=1, process_state=ProcessState.WAITING)
    await ckpt.create(process_id=2, process_state=ProcessState.RUNNING)
    p1_checkpoints = await ckpt.list_for_process(1)
    assert len(p1_checkpoints) == 2
