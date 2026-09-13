"""Tests for IPC system."""
import pytest
import asyncio
from agent_os.ipc.ipc_manager import IPCManager
from agent_os.metrics.events import EventManager
from agent_os.config.settings import Settings


@pytest.mark.asyncio
async def test_send_and_receive():
    ipc = IPCManager(Settings(), EventManager())
    msg = await ipc.send(sender_pid=1, receiver_pid=2, payload="hello")
    assert msg.sender_pid == 1
    assert msg.receiver_pid == 2
    assert msg.payload == "hello"
    assert msg.delivery_status == "DELIVERED"

    received = await ipc.receive(2)
    assert received is not None
    assert received.payload == "hello"


@pytest.mark.asyncio
async def test_fifo_ordering():
    ipc = IPCManager(Settings(), EventManager())
    await ipc.send(sender_pid=1, receiver_pid=2, payload="first")
    await ipc.send(sender_pid=1, receiver_pid=2, payload="second")
    m1 = await ipc.receive(2)
    m2 = await ipc.receive(2)
    assert m1.payload == "first"
    assert m2.payload == "second"


@pytest.mark.asyncio
async def test_no_message_returns_none():
    ipc = IPCManager(Settings(), EventManager())
    received = await ipc.receive(99)
    assert received is None


@pytest.mark.asyncio
async def test_wait_for_message():
    ipc = IPCManager(Settings(), EventManager())

    async def delayed_send():
        await asyncio.sleep(0.05)
        await ipc.send(sender_pid=1, receiver_pid=2, payload="delayed")

    task = asyncio.create_task(delayed_send())
    msg = await ipc.wait_for_message(2)
    assert msg.payload == "delayed"
    await task
