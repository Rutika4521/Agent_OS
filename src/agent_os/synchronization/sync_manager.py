"""Agent-OS Synchronization — Manager."""
from agent_os.synchronization.lock import AgentLock
from agent_os.synchronization.semaphore import AgentSemaphore
from agent_os.synchronization.deadlock import DeadlockDetector
from agent_os.metrics.events import EventManager, EventType

class SynchronizationManager:
    def __init__(self, event_manager: EventManager):
        self._event_manager = event_manager
        self._locks: dict[str, AgentLock] = {}
        self._semaphores: dict[str, AgentSemaphore] = {}
        self._deadlock_detector = DeadlockDetector()
    
    def create_lock(self, lock_id: str) -> AgentLock:
        lock = AgentLock(lock_id)
        self._locks[lock_id] = lock
        return lock
    
    def create_semaphore(self, semaphore_id: str, max_count: int) -> AgentSemaphore:
        sem = AgentSemaphore(semaphore_id, max_count)
        self._semaphores[semaphore_id] = sem
        return sem
    
    def get_lock(self, lock_id: str) -> AgentLock | None:
        return self._locks.get(lock_id)
    
    def get_semaphore(self, semaphore_id: str) -> AgentSemaphore | None:
        return self._semaphores.get(semaphore_id)
    
    @property
    def deadlock_detector(self) -> DeadlockDetector:
        return self._deadlock_detector
    
    async def acquire_lock(self, lock_id: str, pid: int, priority: int = 0) -> bool:
        lock = self._locks.get(lock_id)
        if lock is None:
            lock = self.create_lock(lock_id)
        acquired = await lock.acquire(pid, priority)
        if acquired:
            await self._event_manager.emit(EventType.LOCK_ACQUIRED, process_id=pid, metadata={"lock_id": lock_id})
        else:
            # Add to wait-for graph
            if lock.owner is not None:
                self._deadlock_detector.add_dependency(pid, lock.owner)
            # Check for priority inheritance
            target = lock.get_inheritance_target()
            if target:
                pass  # Priority inheritance handled by caller
        return acquired
    
    async def release_lock(self, lock_id: str, pid: int) -> None:
        lock = self._locks.get(lock_id)
        if lock is None:
            return
        # Remove dependencies
        self._deadlock_detector.remove_process(pid)
        next_pid = await lock.release(pid)
        await self._event_manager.emit(EventType.LOCK_RELEASED, process_id=pid, metadata={"lock_id": lock_id})
        if next_pid is not None:
            self._deadlock_detector.remove_dependency(next_pid, pid)
            await self._event_manager.emit(EventType.LOCK_ACQUIRED, process_id=next_pid, metadata={"lock_id": lock_id})
    
    async def check_deadlocks(self) -> list[int] | None:
        cycle = self._deadlock_detector.detect_cycle()
        if cycle:
            await self._event_manager.emit(EventType.DEADLOCK_DETECTED, metadata={"cycle": cycle})
        return cycle
