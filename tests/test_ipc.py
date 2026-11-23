"""Tests for IPCManager — send, receive, deduplication, events."""
import pytest
from agent_os.ipc.ipc_manager import IPCManager
from agent_os.ipc.message import Message
from agent_os.metrics.events import EventManager, EventType
from agent_os.config.settings import Settings


@pytest.fixture
def ipc(settings, event_manager):
    return IPCManager(settings=settings, event_manager=event_manager)


@pytest.mark.asyncio
async def test_send_returns_message(ipc):
    msg = await ipc.send(sender_pid=1, receiver_pid=2, payload={"data": "hello"})
    assert isinstance(msg, Message)
    assert msg.sender_pid == 1
    assert msg.receiver_pid == 2
    assert msg.payload == {"data": "hello"}


@pytest.mark.asyncio
async def test_send_emits_ipc_sent_event(ipc, event_manager):
    await ipc.send(1, 2, "hello")
    types = [e.event_type for e in await event_manager.get_history()]
    assert EventType.IPC_SENT in types


@pytest.mark.asyncio
async def test_receive_returns_message(ipc):
    await ipc.send(1, 2, "payload")
    msg = await ipc.receive(2)
    assert msg is not None
    assert msg.payload == "payload"


@pytest.mark.asyncio
async def test_receive_returns_none_when_empty(ipc):
    msg = await ipc.receive(pid=99)
    assert msg is None


@pytest.mark.asyncio
async def test_receive_emits_ipc_received_event(ipc, event_manager):
    await ipc.send(1, 2, "x")
    await event_manager.clear_history()
    await ipc.receive(2)
    types = [e.event_type for e in await event_manager.get_history()]
    assert EventType.IPC_RECEIVED in types


@pytest.mark.asyncio
async def test_receive_returns_oldest_message_first(ipc):
    await ipc.send(1, 2, "first")
    await ipc.send(1, 2, "second")
    msg1 = await ipc.receive(2)
    msg2 = await ipc.receive(2)
    assert msg1.payload == "first"
    assert msg2.payload == "second"


@pytest.mark.asyncio
async def test_send_message_has_unique_id(ipc):
    m1 = await ipc.send(1, 2, "a")
    m2 = await ipc.send(1, 2, "b")
    assert m1.message_id != m2.message_id


@pytest.mark.asyncio
async def test_message_queue_isolated_per_receiver(ipc):
    await ipc.send(1, 2, "for_pid2")
    await ipc.send(1, 3, "for_pid3")
    msg_for_2 = await ipc.receive(2)
    msg_for_3 = await ipc.receive(3)
    assert msg_for_2.payload == "for_pid2"
    assert msg_for_3.payload == "for_pid3"


@pytest.mark.asyncio
async def test_send_multiple_senders_to_same_receiver(ipc):
    await ipc.send(1, 3, "from1")
    await ipc.send(2, 3, "from2")
    msgs = []
    for _ in range(2):
        m = await ipc.receive(3)
        if m:
            msgs.append(m.payload)
    assert set(msgs) == {"from1", "from2"}
