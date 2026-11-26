"""Synchronisation agents: deadlocks, priority inversion, semaphores, lock leaks, re-entrancy."""
from __future__ import annotations

import asyncio
import time

from . import BLOCK, CONTINUE, done


class OrderedLocker:
    """
    Takes `first`, waits at a rendezvous until every member of `group` holds
    its first lock, then requests `second`. With crossed orderings this
    *guarantees* a circular wait — a real deadlock in the kernel's lock table.
    """

    def __init__(self, first: str, second: str, group: str, group_size: int, work: int = 2):
        self.first, self.second = first, second
        self.group, self.group_size = group, group_size
        self.work, self.done_work = work, 0
        self.retry = False

    def on_restart(self, _checkpoint):
        self.retry, self.done_work = True, 0

    async def step(self, ctx):
        s = ctx.data["sys"]
        if not s.holds(self.first):
            if not await s.acquire(self.first):
                return BLOCK
            s.log(f"holds '{self.first}'")
            if not self.retry:
                s.board.setdefault(self.group, set()).add(s.name)
        if not self.retry and len(s.board.get(self.group, ())) < self.group_size:
            return s.sleep(0.03)                       # rendezvous
        if not s.holds(self.second):
            s.log(f"requests '{self.second}'")
            if not await s.acquire(self.second):
                return BLOCK
        self.done_work += 1
        if self.done_work < self.work:
            return CONTINUE
        await s.release(self.second)
        await s.release(self.first)
        s.record(f"{self.group}_finished", s.name)
        return done()


# ── Priority inversion trio ──────────────────────────────────────────────────
class LowLogger:
    """Priority 2. Holds 'disk' while a priority-9 agent needs it."""

    def __init__(self):
        self.work = 0

    async def step(self, ctx):
        s = ctx.data["sys"]
        if not s.holds("disk"):
            await s.acquire("disk")
            s.board["disk_held"] = True
            s.log("holds 'disk'")
        if not s.board.get("high_blocked"):
            return s.sleep(0.03)
        p = await s._k.pm.get(s.pid)                    # read-only peek for evidence
        s.record("low_prio_while_holding", p.priority)
        self.work += 1
        if self.work < 4:
            return CONTINUE
        s.board["disk_released_at_medium_step"] = s.board.get("medium_steps", 0)
        await s.release("disk")
        return done()


class HighCritical:
    async def step(self, ctx):
        s = ctx.data["sys"]
        if not s.board.get("disk_held"):
            return s.sleep(0.03)
        if not s.holds("disk"):
            if not await s.acquire("disk"):
                s.board["high_blocked"] = True
                s.log("blocked on 'disk' held by LowLogger")
                return BLOCK
        s.board["high_done_at_medium_step"] = s.board.get("medium_steps", 0)
        await s.release("disk")
        return done()


class MediumBatch:
    """Priority 5 CPU work that would run ahead of LowLogger without inheritance."""

    def __init__(self, steps: int = 25):
        self.left = steps

    async def step(self, ctx):
        s = ctx.data["sys"]
        if not s.board.get("high_blocked"):
            return s.sleep(0.03)
        await asyncio.sleep(0.004)
        s.board["medium_steps"] = s.board.get("medium_steps", 0) + 1
        self.left -= 1
        return done() if self.left == 0 else CONTINUE


# ── Counting semaphore ───────────────────────────────────────────────────────
class GPUJob:
    """Needs one of 2 GPU slots (counting semaphore) for 3 steps."""

    def __init__(self):
        self.work = 0

    async def step(self, ctx):
        s = ctx.data["sys"]
        if not s.holds_sem("gpu"):
            if not await s.sem_acquire("gpu"):
                s.record("gpu_blocked", s.name)
                return BLOCK
        self.work += 1
        if self.work < 3:
            return s.sleep(0.05)                       # keeps the slot while sleeping
        await s.sem_release("gpu")
        return done()


# ── Lock leak / re-entrancy ──────────────────────────────────────────────────
class SloppyAgent:
    """Exits while still holding 'cache' — the kernel must reclaim it."""

    def __init__(self):
        self.n = 0

    async def step(self, ctx):
        s = ctx.data["sys"]
        self.n += 1
        if self.n == 1:
            await s.acquire("cache")
            s.board["cache_held"] = True
            return s.sleep(0.1)
        return done()                                  # forgot to release!


class CacheReader:
    async def step(self, ctx):
        s = ctx.data["sys"]
        if not s.board.get("cache_held"):
            return s.sleep(0.03)
        if not s.holds("cache"):
            if not await s.acquire("cache"):
                return BLOCK
        s.record("cache_reader_got_lock", time.time())
        await s.release("cache")
        return done()


class DoubleLocker:
    """Acquires the same non-reentrant lock twice → kernel LockError → FAILED."""

    async def step(self, ctx):
        s = ctx.data["sys"]
        await s.acquire("config")
        await s.acquire("config")
        return done()
