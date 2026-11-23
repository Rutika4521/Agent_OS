"""Tests for ContextManager — create, add_page, swap, eviction."""
import pytest
from agent_os.memory.context_manager import ContextManager
from agent_os.metrics.events import EventManager, EventType
from agent_os.config.settings import Settings


@pytest.fixture
def cm(settings, event_manager):
    mgr = ContextManager(settings, event_manager)
    mgr.max_loaded_pages = 10
    return mgr


@pytest.mark.asyncio
async def test_create_returns_context_id(cm):
    ctx_id = await cm.create(process_id=1)
    assert isinstance(ctx_id, str)
    assert len(ctx_id) > 0


@pytest.mark.asyncio
async def test_add_page_returns_page(cm):
    ctx_id = await cm.create(process_id=1)
    page = await cm.add_page(ctx_id, process_id=1, content="hello")
    assert page.content == "hello"
    assert page.process_id == 1


@pytest.mark.asyncio
async def test_add_page_to_nonexistent_context_raises(cm):
    with pytest.raises(ValueError):
        await cm.add_page("nonexistent", process_id=1, content="x")


@pytest.mark.asyncio
async def test_load_returns_all_pages(cm):
    ctx_id = await cm.create(process_id=1)
    await cm.add_page(ctx_id, 1, "page0")
    await cm.add_page(ctx_id, 1, "page1")
    pages = await cm.load(ctx_id)
    assert len(pages) == 2


@pytest.mark.asyncio
async def test_load_nonexistent_raises(cm):
    with pytest.raises(ValueError):
        await cm.load("bad-id")


@pytest.mark.asyncio
async def test_swap_out_and_swap_in(cm, event_manager):
    ctx_id = await cm.create(process_id=1)
    await cm.add_page(ctx_id, 1, "content")
    # Swap out
    await cm.swap_out(ctx_id, 0)
    pages = await cm.load(ctx_id)
    assert pages[0].loaded is False
    # Swap in
    await cm.swap_in(ctx_id, 0)
    pages = await cm.load(ctx_id)
    assert pages[0].loaded is True


@pytest.mark.asyncio
async def test_swap_out_emits_event(cm, event_manager):
    ctx_id = await cm.create(process_id=1)
    await cm.add_page(ctx_id, 1, "data")
    await cm.swap_out(ctx_id, 0)
    types = [e.event_type for e in await event_manager.get_history()]
    assert EventType.CONTEXT_SWAP_OUT in types


@pytest.mark.asyncio
async def test_swap_in_emits_event(cm, event_manager):
    ctx_id = await cm.create(process_id=1)
    await cm.add_page(ctx_id, 1, "data")
    await cm.swap_out(ctx_id, 0)
    await event_manager.clear_history()
    await cm.swap_in(ctx_id, 0)
    types = [e.event_type for e in await event_manager.get_history()]
    assert EventType.CONTEXT_SWAP_IN in types


@pytest.mark.asyncio
async def test_get_page_returns_correct_page(cm):
    ctx_id = await cm.create(process_id=1)
    await cm.add_page(ctx_id, 1, "first")
    await cm.add_page(ctx_id, 1, "second")
    page = await cm.get_page(ctx_id, 1)
    assert page.content == "second"


@pytest.mark.asyncio
async def test_get_page_out_of_bounds_returns_none(cm):
    ctx_id = await cm.create(process_id=1)
    result = await cm.get_page(ctx_id, 99)
    assert result is None


@pytest.mark.asyncio
async def test_update_page_changes_content(cm):
    ctx_id = await cm.create(process_id=1)
    await cm.add_page(ctx_id, 1, "original")
    await cm.update_page(ctx_id, 0, "updated")
    page = await cm.get_page(ctx_id, 0)
    assert page.content == "updated"
    assert page.version == 2


@pytest.mark.asyncio
async def test_remove_context(cm):
    ctx_id = await cm.create(process_id=1)
    await cm.add_page(ctx_id, 1, "data")
    await cm.remove(ctx_id)
    with pytest.raises(ValueError):
        await cm.load(ctx_id)


@pytest.mark.asyncio
async def test_eviction_triggered_when_over_limit(cm, event_manager):
    cm.max_loaded_pages = 2
    ctx_id = await cm.create(process_id=1)
    # Add 3 pages — 3rd triggers eviction of oldest
    await cm.add_page(ctx_id, 1, "a")
    await cm.add_page(ctx_id, 1, "b")
    await cm.add_page(ctx_id, 1, "c")
    types = [e.event_type for e in await event_manager.get_history()]
    assert EventType.CONTEXT_SWAP_OUT in types
