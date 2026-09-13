"""
Agent-OS Metrics — Event system

Defines event types, event model, and the EventManager (§63-§64).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine


class EventType(str, Enum):
    """All observable event types in Agent-OS (§63)."""

    # Process lifecycle
    PROCESS_CREATED = "PROCESS_CREATED"
    PROCESS_READY = "PROCESS_READY"
    PROCESS_STARTED = "PROCESS_STARTED"
    PROCESS_WAITING = "PROCESS_WAITING"
    PROCESS_BLOCKED = "PROCESS_BLOCKED"
    PROCESS_COMPLETED = "PROCESS_COMPLETED"
    PROCESS_FAILED = "PROCESS_FAILED"
    PROCESS_CANCELLED = "PROCESS_CANCELLED"
    PROCESS_TERMINATED = "PROCESS_TERMINATED"

    # Scheduler
    SCHEDULER_SELECTED = "SCHEDULER_SELECTED"

    # Resources
    RESOURCE_LIMIT = "RESOURCE_LIMIT"
    TOKEN_USAGE = "TOKEN_USAGE"
    TOOL_CALL = "TOOL_CALL"
    LLM_CALL = "LLM_CALL"

    # IPC
    IPC_SENT = "IPC_SENT"
    IPC_RECEIVED = "IPC_RECEIVED"
    IPC_DROPPED = "IPC_DROPPED"

    # Context
    CONTEXT_SWAP_OUT = "CONTEXT_SWAP_OUT"
    CONTEXT_SWAP_IN = "CONTEXT_SWAP_IN"
    CHECKPOINT_CREATED = "CHECKPOINT_CREATED"

    # Synchronization
    LOCK_ACQUIRED = "LOCK_ACQUIRED"
    LOCK_RELEASED = "LOCK_RELEASED"
    DEADLOCK_DETECTED = "DEADLOCK_DETECTED"

    # Supervisor
    RESTART_STARTED = "RESTART_STARTED"
    RESTART_COMPLETED = "RESTART_COMPLETED"

    # Sandbox
    SANDBOX_STARTED = "SANDBOX_STARTED"
    SANDBOX_COMPLETED = "SANDBOX_COMPLETED"


@dataclass
class Event:
    """A single observable event in the Agent-OS runtime (§64)."""
    event_id: str
    event_type: EventType
    timestamp: float
    process_id: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# Type for event subscribers
EventHandler = Callable[[Event], Coroutine[Any, Any, None] | None]


class EventManager:
    """
    Central event system for Agent-OS (§64).

    Provides emit(), subscribe(), and get_history().
    Events are stored in memory with optional persistence.
    """

    def __init__(self, max_history: int = 10000):
        self._subscribers: dict[EventType | None, list[EventHandler]] = {}
        self._history: deque[Event] = deque(maxlen=max_history)
        self._lock = asyncio.Lock()

    async def emit(
        self,
        event_type: EventType,
        process_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Event:
        """
        Emit an event and notify all subscribers.

        Args:
            event_type: The type of event.
            process_id: Associated process ID, if any.
            metadata: Additional event data.

        Returns:
            The emitted Event object.
        """
        event = Event(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            timestamp=time.time(),
            process_id=process_id,
            metadata=metadata or {},
        )

        async with self._lock:
            self._history.append(event)

        # Notify type-specific subscribers
        handlers = self._subscribers.get(event_type, [])
        # Notify global subscribers (subscribed to None)
        handlers = handlers + self._subscribers.get(None, [])

        for handler in handlers:
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                # Subscriber errors must not break event emission
                pass

        return event

    def subscribe(
        self,
        event_type: EventType | None,
        handler: EventHandler,
    ) -> None:
        """
        Subscribe to events.

        Args:
            event_type: Specific event type, or None for all events.
            handler: Callback function (sync or async).
        """
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)

    def unsubscribe(
        self,
        event_type: EventType | None,
        handler: EventHandler,
    ) -> None:
        """Unsubscribe a handler from events."""
        handlers = self._subscribers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)

    async def get_history(
        self,
        event_type: EventType | None = None,
        process_id: int | None = None,
        limit: int | None = None,
    ) -> list[Event]:
        """
        Retrieve event history with optional filtering.

        Args:
            event_type: Filter by event type.
            process_id: Filter by process ID.
            limit: Maximum number of events to return.

        Returns:
            List of matching events, most recent last.
        """
        async with self._lock:
            events = list(self._history)

        if event_type is not None:
            events = [e for e in events if e.event_type == event_type]
        if process_id is not None:
            events = [e for e in events if e.process_id == process_id]
        if limit is not None:
            events = events[-limit:]

        return events

    async def clear_history(self) -> None:
        """Clear the event history."""
        async with self._lock:
            self._history.clear()
