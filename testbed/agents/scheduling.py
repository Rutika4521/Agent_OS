"""Scheduling agents: priority preemption, starvation/aging, weighted fair share."""
from __future__ import annotations

import asyncio
import time

from . import CONTINUE, done


class Commander:
    """Priority 10 — must be the very first process the scheduler picks."""

    def __init__(self):
        self.n = 0

    async def step(self, ctx):
        s = ctx.data["sys"]
        self.n += 1
        await s.llm(f"triage step {self.n}", 40, 60)
        return done() if self.n >= 3 else CONTINUE


class CPUHog:
    """High-priority compute-bound agent that would starve anything below it."""

    def __init__(self, steps: int = 45):
        self.left = steps

    async def step(self, ctx):
        s = ctx.data["sys"]
        s.board.setdefault("hogs_alive", set()).add(s.name)
        await asyncio.sleep(0.008)          # burn "CPU"
        self.left -= 1
        if self.left == 0:
            s.board["hogs_alive"].discard(s.name)
            return done()
        return CONTINUE


class Janitor:
    """Priority 1. Only the aging policy can get it scheduled while hogs are runnable."""

    def __init__(self):
        self.spawned = time.time()
        self.n = 0

    async def step(self, ctx):
        s = ctx.data["sys"]
        self.n += 1
        if self.n == 1:
            waited = time.time() - self.spawned
            s.record("janitor_first_run", {"waited": round(waited, 2),
                                           "hogs_alive": len(s.board.get("hogs_alive", ()))})
            s.log(f"finally scheduled after {waited:.2f}s (aging) while "
                  f"{len(s.board.get('hogs_alive', ()))} hogs still alive")
        return done() if self.n >= 2 else CONTINUE


class Tenant:
    """Phase 2: identical workloads with different weights under the weighted-fair scheduler."""

    def __init__(self, steps: int = 60):
        self.left = steps

    async def step(self, ctx):
        self.left -= 1
        return done() if self.left == 0 else CONTINUE
