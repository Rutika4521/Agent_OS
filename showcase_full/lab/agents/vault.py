"""Vault — synchronisation: lock and semaphore deadlocks, inversion, FIFO hand-off, leaks."""
from __future__ import annotations

import asyncio
import time

from ..os_api import LabAgent


class OrderedLocker(LabAgent):
    """
    Takes `first`, waits at a rendezvous until every member of `group` holds its
    first resource, then requests `second`. Crossed orderings *guarantee* a
    circular wait in the kernel's lock table. kind="sem" uses 1-slot semaphores.
    """

    def __init__(self, first: str, second: str, group: str, size: int, kind: str = "lock"):
        self.first, self.second, self.group, self.size, self.kind = first, second, group, size, kind
        self.retry, self.work = False, 0

    def on_restart(self, _checkpoint):
        self.retry, self.work = True, 0

    def _holds(self, s, r):
        return s.holds(r) if self.kind == "lock" else s.holds_sem(r)

    async def _take(self, s, r):
        return await (s.acquire(r) if self.kind == "lock" else s.sem_acquire(r, 1))

    async def _give(self, s, r):
        await (s.release(r) if self.kind == "lock" else s.sem_release(r))

    async def act(self, s):
        if not self._holds(s, self.first):
            if not await self._take(s, self.first):
                return s.BLOCK
            if not self.retry:
                s.board.setdefault(self.group, set()).add(s.name)
        if not self.retry and len(s.board.get(self.group, ())) < self.size:
            return s.sleep(0.03)
        if not self._holds(s, self.second):
            if not await self._take(s, self.second):
                return s.BLOCK
        self.work += 1
        if self.work < 2:
            return s.CONTINUE
        await self._give(s, self.second)
        await self._give(s, self.first)
        s.record(f"{self.group}_finished", s.name)
        return s.done()


class LowLogger(LabAgent):
    """Priority 2. Holds 'disk' while a priority-9 agent needs it."""

    def __init__(self):
        self.work = 0

    async def act(self, s):
        if not s.holds("disk"):
            await s.acquire("disk")
            s.board["disk_held"] = True
        if not s.board.get("high_blocked"):
            return s.sleep(0.03)
        s.record("low_prio_while_holding", s.priority)
        self.work += 1
        if self.work < 4:
            return s.CONTINUE
        s.board["disk_released_at_medium_step"] = s.board.get("medium_steps", 0)
        await s.release("disk")
        return s.done()


class HighCritical(LabAgent):
    async def act(self, s):
        if not s.board.get("disk_held"):
            return s.sleep(0.03)
        if not s.holds("disk"):
            if not await s.acquire("disk"):
                s.board["high_blocked"] = True
                return s.BLOCK
        await s.release("disk")
        return s.done()


class MediumBatch(LabAgent):
    """Priority 5 CPU work that would overtake LowLogger without inheritance."""

    def __init__(self, steps: int = 25):
        self.left = steps

    async def act(self, s):
        if not s.board.get("high_blocked"):
            return s.sleep(0.03)
        await asyncio.sleep(0.004)
        s.board["medium_steps"] = s.board.get("medium_steps", 0) + 1
        self.left -= 1
        return s.done() if self.left == 0 else s.CONTINUE


class GPUJob(LabAgent):
    """Needs one of 2 GPU slots (counting semaphore) for 3 steps."""

    def __init__(self):
        self.work = 0

    async def act(self, s):
        if not s.holds_sem("gpu"):
            if not await s.sem_acquire("gpu", 2):
                s.record("gpu_blocked", s.name)
                return s.BLOCK
        self.work += 1
        if self.work < 3:
            return s.sleep(0.05)               # keeps its slot while sleeping
        await s.sem_release("gpu")
        return s.done()


class SloppyAgent(LabAgent):
    """Exits while still holding 'cache'."""

    def __init__(self):
        self.n = 0

    async def act(self, s):
        self.n += 1
        if self.n == 1:
            await s.acquire("cache")
            s.board["cache_held"] = True
            return s.sleep(0.1)
        return s.done()                        # forgot to release


class CacheReader(LabAgent):
    async def act(self, s):
        if not s.board.get("cache_held"):
            return s.sleep(0.03)
        if not s.holds("cache"):
            if not await s.acquire("cache"):
                return s.BLOCK
        s.record("cache_reader_got_lock", time.time())
        await s.release("cache")
        return s.done()


class DoubleLocker(LabAgent):
    """Acquires the same non-reentrant lock twice."""

    async def act(self, s):
        await s.acquire("config")
        await s.acquire("config")
        return s.done()


class Gatekeeper(LabAgent):
    """Holds 'airlock' until three crew members are queued behind it."""

    async def act(self, s):
        if not s.holds("airlock"):
            await s.acquire("airlock")
            s.board["airlock_held"] = True
        lock = s.k.sync.get_lock("airlock")
        if len(lock.waiting_pids) < 3:
            return s.sleep(0.02)
        s.record("airlock_queue", list(lock.waiting_pids))
        await s.release("airlock")
        return s.done()


class CrewMember(LabAgent):
    """Joins the airlock queue only after crew member `index-1` is queued, so the queue
    order is forced to 1, 2, 3 regardless of priority."""

    def __init__(self, index: int):
        self.index = index

    async def act(self, s):
        if not s.holds("airlock"):
            if not s.board.get("airlock_held") or s.board.get("crew_queued", 0) < self.index - 1:
                return s.sleep(0.01)
            if not await s.acquire("airlock"):
                s.board["crew_queued"] = self.index
                return s.BLOCK
        s.record("airlock_order", s.name)
        await s.release("airlock")
        return s.done()


class Squatter(LabAgent):
    """Holds 'hangar' for a while so others queue behind it."""

    def __init__(self):
        self.n = 0

    async def act(self, s):
        if not s.holds("hangar"):
            await s.acquire("hangar")
            s.board["hangar_held"] = True
        self.n += 1
        if not s.board.get("quitter_cancelled"):
            return s.sleep(0.03)
        await s.release("hangar")
        return s.done()


class HangarWaiter(LabAgent):
    def __init__(self, delay: float = 0.0):
        self.delay, self.started = delay, False

    async def act(self, s):
        if not s.board.get("hangar_held"):
            return s.sleep(0.02)
        if not self.started:
            self.started = True
            if self.delay:
                return s.sleep(self.delay)
        if not s.holds("hangar"):
            if not await s.acquire("hangar"):
                s.record("hangar_blocked", s.name)
                return s.BLOCK
        s.record("hangar_got", s.name)
        await s.release("hangar")
        return s.done()
