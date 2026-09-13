"""Agent-OS Synchronization — Semaphores."""
import asyncio

class SemaphoreError(Exception):
    pass

class AgentSemaphore:
    def __init__(self, semaphore_id: str, max_count: int):
        self.semaphore_id = semaphore_id
        self.max_count = max_count
        self._current_count: int = 0
        self._holders: set[int] = set()
        self._waiting: list[tuple[int, asyncio.Event]] = []
        self._lock = asyncio.Lock()
    
    @property
    def available(self) -> int:
        return self.max_count - self._current_count
    
    @property
    def is_full(self) -> bool:
        return self._current_count >= self.max_count
    
    async def acquire(self, pid: int) -> bool:
        async with self._lock:
            if self._current_count < self.max_count:
                self._current_count += 1
                self._holders.add(pid)
                return True
            event = asyncio.Event()
            self._waiting.append((pid, event))
            return False
    
    async def release(self, pid: int) -> int | None:
        async with self._lock:
            if pid not in self._holders:
                raise SemaphoreError(f"Process {pid} does not hold semaphore {self.semaphore_id}")
            self._holders.discard(pid)
            self._current_count -= 1
            if self._waiting:
                next_pid, event = self._waiting.pop(0)
                self._current_count += 1
                self._holders.add(next_pid)
                event.set()
                return next_pid
            return None
    
    async def wait_for_acquisition(self, pid: int) -> None:
        for p, event in self._waiting:
            if p == pid:
                await event.wait()
                return
