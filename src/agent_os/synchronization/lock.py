"""Agent-OS Synchronization — Locks with priority inheritance support."""
import asyncio
from typing import Any

class LockError(Exception):
    def __init__(self, message: str):
        super().__init__(message)

class AgentLock:
    def __init__(self, lock_id: str):
        self.lock_id = lock_id
        self._owner_pid: int | None = None
        self._waiting: list[tuple[int, int, asyncio.Event]] = []  # (pid, priority, event)
        self._lock = asyncio.Lock()
    
    @property
    def owner(self) -> int | None:
        return self._owner_pid
    
    @property
    def is_locked(self) -> bool:
        return self._owner_pid is not None
    
    @property
    def waiting_pids(self) -> list[int]:
        return [pid for pid, _, _ in self._waiting]
    
    async def acquire(self, pid: int, process_priority: int = 0) -> bool:
        async with self._lock:
            if self._owner_pid is None:
                self._owner_pid = pid
                return True
            if self._owner_pid == pid:
                raise LockError(f"Process {pid} already owns lock {self.lock_id} (no reentrant locks)")
            event = asyncio.Event()
            self._waiting.append((pid, process_priority, event))
            return False
    
    async def release(self, pid: int) -> int | None:
        async with self._lock:
            if self._owner_pid != pid:
                raise LockError(f"Process {pid} does not own lock {self.lock_id}")
            self._owner_pid = None
            if self._waiting:
                next_pid, _, event = self._waiting.pop(0)
                self._owner_pid = next_pid
                event.set()
                return next_pid
            return None
    
    async def wait_for_acquisition(self, pid: int) -> None:
        """Wait until lock is acquired (called after acquire returns False)."""
        for p, _, event in self._waiting:
            if p == pid:
                await event.wait()
                return
    
    def get_inheritance_target(self) -> tuple[int, int] | None:
        if not self._waiting or self._owner_pid is None:
            return None
        max_priority = max(p for _, p, _ in self._waiting)
        return (self._owner_pid, max_priority)
