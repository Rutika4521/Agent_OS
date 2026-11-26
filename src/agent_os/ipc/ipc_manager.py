"""
Agent-OS IPC — Manager

High-level IPC interface coordinating message queues,
channels, and deduplication (§36-§41).
"""

from __future__ import annotations

import asyncio
from typing import Any

from agent_os.config.settings import Settings, get_settings
from agent_os.metrics.events import EventManager, EventType
from agent_os.ipc.message import Message
from agent_os.ipc.queue import MessageQueue
from agent_os.ipc.deduplication import DeduplicationFilter


class IPCManager:
    """
    High-level IPC interface for Agent-OS.

    Manages per-receiver message queues with deduplication
    and event emission.
    """

    def __init__(self, settings: Settings | None = None, event_manager: EventManager | None = None):
        self._settings = settings or get_settings()
        self._event_manager = event_manager or EventManager()
        self._queues: dict[int, MessageQueue] = {}
        self._dedup_filter = DeduplicationFilter()
        self._lock = asyncio.Lock()
        # Optional async callable(pid) -> str | None. Returns a reason when the
        # receiver cannot accept mail (missing / dead process), else None.
        # Wired by the kernel; without it every PID is accepted (standalone use).
        self._receiver_check = None

    def set_receiver_check(self, check) -> None:
        """Install the dead-letter guard: `async check(pid) -> reason | None`."""
        self._receiver_check = check

    async def discard_mailbox(self, pid: int) -> int:
        """Drop every message queued for `pid` (e.g. when it terminates). Returns the count."""
        async with self._lock:
            queue = self._queues.pop(pid, None)
        n = queue.count() if queue else 0
        if n:
            await self._event_manager.emit(
                EventType.IPC_DROPPED, process_id=pid,
                metadata={"receiver_pid": pid, "reason": "receiver terminated", "discarded": n},
            )
        return n

    async def _get_queue(self, receiver_pid: int) -> MessageQueue:
        """Get or create a message queue for a receiver."""
        async with self._lock:
            if receiver_pid not in self._queues:
                self._queues[receiver_pid] = MessageQueue(
                    capacity=self._settings.ipc.queue_capacity,
                    overflow_policy=self._settings.ipc.overflow_policy,
                )
            return self._queues[receiver_pid]

    async def send(
        self,
        sender_pid: int,
        receiver_pid: int,
        payload: Any,
        message_type: str = "DATA",
        correlation_id: str | None = None,
    ) -> Message:
        """
        Send a message from one process to another.

        Creates the message, checks for duplicates, enqueues,
        and emits the appropriate event.
        """
        msg = Message(
            sender_pid=sender_pid,
            receiver_pid=receiver_pid,
            payload=payload,
            message_type=message_type,
            correlation_id=correlation_id,
        )

        # Dead-letter guard: refuse mail for processes that don't exist or are gone
        if self._receiver_check is not None:
            reason = await self._receiver_check(receiver_pid)
            if reason:
                msg.delivery_status = "DROPPED"
                await self._event_manager.emit(
                    EventType.IPC_DROPPED,
                    process_id=sender_pid,
                    metadata={"message_id": msg.message_id, "sender_pid": sender_pid,
                              "receiver_pid": receiver_pid, "reason": reason},
                )
                return msg

        # Check for duplicate
        if await self._dedup_filter.is_duplicate(msg.message_id):
            msg.delivery_status = "DROPPED"
            await self._event_manager.emit(
                EventType.IPC_DROPPED,
                process_id=sender_pid,
                metadata={"message_id": msg.message_id, "reason": "duplicate"},
            )
            return msg

        await self._dedup_filter.mark_seen(msg.message_id)

        queue = await self._get_queue(receiver_pid)
        success = await queue.send(msg)

        if success:
            msg.delivery_status = "DELIVERED"
            await self._event_manager.emit(
                EventType.IPC_SENT,
                process_id=sender_pid,
                metadata={
                    "message_id": msg.message_id,
                    "sender_pid": sender_pid,
                    "receiver_pid": receiver_pid,
                },
            )
        else:
            msg.delivery_status = "DROPPED"
            await self._event_manager.emit(
                EventType.IPC_DROPPED,
                process_id=sender_pid,
                metadata={
                    "message_id": msg.message_id,
                    "sender_pid": sender_pid,
                    "receiver_pid": receiver_pid,
                },
            )

        return msg

    async def receive(self, pid: int) -> Message | None:
        """
        Non-blocking receive: returns oldest message for pid, or None.
        """
        queue = await self._get_queue(pid)
        msg = await queue.receive(pid)
        if msg:
            await self._event_manager.emit(
                EventType.IPC_RECEIVED,
                process_id=pid,
                metadata={"message_id": msg.message_id, "receiver_pid": pid},
            )
        return msg

    async def wait_for_message(self, pid: int) -> Message:
        """
        Blocking receive: waits until a message is available for pid.
        """
        queue = await self._get_queue(pid)
        msg = await queue.wait_for_message(pid)
        await self._event_manager.emit(
            EventType.IPC_RECEIVED,
            process_id=pid,
            metadata={"message_id": msg.message_id, "receiver_pid": pid},
        )
        return msg
