"""Tests for EventManager — emit, subscribe, history, filtering."""
import pytest
from agent_os.metrics.events import EventManager, EventType, Event


@pytest.mark.asyncio
async def test_emit_adds_to_history(event_manager):
    await event_manager.emit(EventType.PROCESS_CREATED, process_id=1)
    history = await event_manager.get_history()
    assert len(history) == 1
    assert history[0].event_type == EventType.PROCESS_CREATED


@pytest.mark.asyncio
async def test_emit_with_metadata(event_manager):
    await event_manager.emit(EventType.PROCESS_CREATED, process_id=1, metadata={"name": "agent1"})
    ev = (await event_manager.get_history())[0]
    assert ev.metadata["name"] == "agent1"


@pytest.mark.asyncio
async def test_emit_calls_sync_subscriber(event_manager):
    received = []
    def handler(event: Event):
        received.append(event)
    event_manager.subscribe(EventType.PROCESS_READY, handler)
    await event_manager.emit(EventType.PROCESS_READY, process_id=1)
    assert len(received) == 1
    assert received[0].process_id == 1


@pytest.mark.asyncio
async def test_emit_calls_async_subscriber(event_manager):
    received = []
    async def handler(event: Event):
        received.append(event)
    event_manager.subscribe(EventType.PROCESS_STARTED, handler)
    await event_manager.emit(EventType.PROCESS_STARTED, process_id=2)
    assert len(received) == 1


@pytest.mark.asyncio
async def test_subscriber_not_called_for_other_events(event_manager):
    received = []
    event_manager.subscribe(EventType.PROCESS_COMPLETED, lambda e: received.append(e))
    await event_manager.emit(EventType.PROCESS_READY, process_id=1)
    assert len(received) == 0


@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery(event_manager):
    received = []
    def handler(event):
        received.append(event)
    event_manager.subscribe(EventType.PROCESS_READY, handler)
    event_manager.unsubscribe(EventType.PROCESS_READY, handler)
    await event_manager.emit(EventType.PROCESS_READY, process_id=1)
    assert len(received) == 0


@pytest.mark.asyncio
async def test_get_history_filter_by_event_type(event_manager):
    await event_manager.emit(EventType.PROCESS_CREATED, process_id=1)
    await event_manager.emit(EventType.PROCESS_READY, process_id=1)
    await event_manager.emit(EventType.PROCESS_STARTED, process_id=1)
    history = await event_manager.get_history(event_type=EventType.PROCESS_READY)
    assert len(history) == 1
    assert history[0].event_type == EventType.PROCESS_READY


@pytest.mark.asyncio
async def test_get_history_filter_by_process_id(event_manager):
    await event_manager.emit(EventType.PROCESS_CREATED, process_id=1)
    await event_manager.emit(EventType.PROCESS_CREATED, process_id=2)
    history = await event_manager.get_history(process_id=1)
    assert all(e.process_id == 1 for e in history)


@pytest.mark.asyncio
async def test_get_history_limit(event_manager):
    for i in range(10):
        await event_manager.emit(EventType.PROCESS_CREATED, process_id=i)
    history = await event_manager.get_history(limit=5)
    assert len(history) == 5


@pytest.mark.asyncio
async def test_clear_history(event_manager):
    await event_manager.emit(EventType.PROCESS_CREATED, process_id=1)
    await event_manager.clear_history()
    assert len(await event_manager.get_history()) == 0


@pytest.mark.asyncio
async def test_multiple_events_ordered(event_manager):
    for et in [EventType.PROCESS_CREATED, EventType.PROCESS_READY, EventType.PROCESS_STARTED]:
        await event_manager.emit(et, process_id=1)
    history = await event_manager.get_history()
    assert history[0].event_type == EventType.PROCESS_CREATED
    assert history[1].event_type == EventType.PROCESS_READY
    assert history[2].event_type == EventType.PROCESS_STARTED


@pytest.mark.asyncio
async def test_emit_returns_event_object(event_manager):
    ev = await event_manager.emit(EventType.IPC_SENT, process_id=1, metadata={"k": "v"})
    assert isinstance(ev, Event)
    assert ev.event_type == EventType.IPC_SENT
    assert ev.process_id == 1
