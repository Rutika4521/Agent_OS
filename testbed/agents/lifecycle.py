"""Lifecycle agents: pause/resume, cancellation with lock reclaim, process trees and orphans."""
from __future__ import annotations

import asyncio
import time

from agent_os.kernel.process_manager import ProcessLimitReached

from . import BLOCK, CONTINUE, done


class BatchReport:
    def __init__(self, steps: int = 20):
        self.left = steps

    async def step(self, ctx):
        s = ctx.data["sys"]
        s.record("batch_step_t", time.time())
        await asyncio.sleep(0.005)
        self.left -= 1
        return done() if self.left == 0 else CONTINUE


class RunawayCrawler:
    """Grabs 'crawl-db' and never stops. Operator cancels it."""

    async def step(self, ctx):
        s = ctx.data["sys"]
        if not s.holds("crawl-db"):
            await s.acquire("crawl-db")
            s.board["crawler_holds"] = True
        await asyncio.sleep(0.005)
        return CONTINUE


class ReportWriter:
    async def step(self, ctx):
        s = ctx.data["sys"]
        if not s.board.get("crawler_holds"):
            return s.sleep(0.03)
        if not s.holds("crawl-db"):
            if not await s.acquire("crawl-db"):
                return BLOCK
        s.record("report_writer_got_lock", True)
        await s.release("crawl-db")
        return done()


class ChildWorker:
    """Long-lived child; should die only through the orphan policy."""

    async def step(self, ctx):
        return ctx.data["sys"].sleep(0.1)


class Foreman:
    """Spawns 4 children with a child limit of 3, then crashes (restart NEVER)."""

    def __init__(self):
        self.n = 0

    async def step(self, ctx):
        s = ctx.data["sys"]
        self.n += 1
        if self.n == 1:
            for i in range(1, 5):
                try:
                    await s.spawn(ChildWorker(), name=f"Child-{i}", priority=3)
                    s.record("children_spawned", f"Child-{i}")
                except ProcessLimitReached as e:
                    s.record("child_rejected", str(e))
                    s.log(f"kernel refused Child-{i}: {e}")
            return s.sleep(0.15)
        if self.n < 3:
            return s.sleep(0.15)
        raise RuntimeError("foreman crashed with children still running")
