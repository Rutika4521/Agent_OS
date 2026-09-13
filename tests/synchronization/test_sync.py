"""Tests for Synchronization (§42-§44)."""
import pytest
from agent_os.synchronization.lock import AgentLock, LockError
from agent_os.synchronization.semaphore import AgentSemaphore, SemaphoreError
from agent_os.synchronization.deadlock import DeadlockDetector


@pytest.mark.asyncio
async def test_lock_acquire_and_release():
    lock = AgentLock("lock1")
    assert await lock.acquire(1) is True
    assert lock.is_locked is True
    assert lock.owner == 1
    next_pid = await lock.release(1)
    assert next_pid is None
    assert lock.is_locked is False


@pytest.mark.asyncio
async def test_lock_contention():
    lock = AgentLock("lock1")
    assert await lock.acquire(1) is True
    assert await lock.acquire(2) is False
    assert 2 in lock.waiting_pids
    next_pid = await lock.release(1)
    assert next_pid == 2


@pytest.mark.asyncio
async def test_lock_double_release_raises():
    lock = AgentLock("lock1")
    await lock.acquire(1)
    await lock.release(1)
    with pytest.raises(LockError):
        await lock.release(1)


@pytest.mark.asyncio
async def test_lock_reentrant_raises():
    lock = AgentLock("lock1")
    await lock.acquire(1)
    with pytest.raises(LockError):
        await lock.acquire(1)


@pytest.mark.asyncio
async def test_semaphore_acquire_and_release():
    sem = AgentSemaphore("sem1", max_count=2)
    assert await sem.acquire(1) is True
    assert await sem.acquire(2) is True
    assert sem.is_full is True
    assert await sem.acquire(3) is False
    next_pid = await sem.release(1)
    assert next_pid == 3


@pytest.mark.asyncio
async def test_semaphore_release_non_holder():
    sem = AgentSemaphore("sem1", max_count=2)
    await sem.acquire(1)
    with pytest.raises(SemaphoreError):
        await sem.release(99)


def test_deadlock_detection():
    dd = DeadlockDetector()
    dd.add_dependency(1, 2)
    dd.add_dependency(2, 1)
    cycle = dd.detect_cycle()
    assert cycle is not None
    assert set(cycle) == {1, 2}


def test_no_deadlock():
    dd = DeadlockDetector()
    dd.add_dependency(1, 2)
    dd.add_dependency(2, 3)
    cycle = dd.detect_cycle()
    assert cycle is None


def test_deadlock_victim_selection():
    dd = DeadlockDetector()
    dd.add_dependency(1, 2)
    dd.add_dependency(2, 1)
    cycle = dd.detect_cycle()
    victim = dd.select_victim(cycle, {1: 10, 2: 5})
    assert victim == 2  # lowest priority
