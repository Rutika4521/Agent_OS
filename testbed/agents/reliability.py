"""Reliability agents: restart policies, backoff, hangs, LLM failures, checkpoint/restore."""
from __future__ import annotations

import asyncio
import time

from . import CONTINUE, done


class Crasher:
    """
    Crashes on the first step of its first `fail_runs` runs, then succeeds.
    fail_runs=99 → crashes forever (crash loop).
    """

    def __init__(self, fail_runs: int, steps: int = 2):
        self.fail_runs, self.steps, self.n = fail_runs, steps, 0

    def on_restart(self, _checkpoint):
        self.n = 0

    async def step(self, ctx):
        s = ctx.data["sys"]
        self.n += 1
        if self.n == 1:
            s.record(f"run_start:{s.name}", time.time())
            if s.restarts < self.fail_runs:
                s.record(f"crash_at:{s.name}", time.time())
                raise RuntimeError(f"simulated crash (run {s.restarts + 1})")
        return done() if self.n >= self.steps else CONTINUE


class HungAgent:
    """First run hangs for 10s inside a step; the 0.4s step timeout must cut it."""

    async def step(self, ctx):
        s = ctx.data["sys"]
        if s.restarts == 0:
            await asyncio.sleep(10)
        return done()


class LLMFlaky:
    """First LLM call hits a provider outage; the retry after restart succeeds."""

    async def step(self, ctx):
        s = ctx.data["sys"]
        answer = await s.llm("classify incident", 20, 30, fail=(s.restarts == 0))
        s.record("llm_recovered", answer)
        return done()


class MigrationJob:
    """10 batches, checkpoint after each. Loses power at batch 6 once; must resume, not redo."""

    def __init__(self):
        self.batch = 0

    def on_restart(self, checkpoint):
        self.batch = checkpoint["next_batch"] if checkpoint else 0
        self._resumed = self.batch

    async def step(self, ctx):
        s = ctx.data["sys"]
        if getattr(self, "_resumed", None) is not None:
            s.record("migration_resumed_from", self._resumed)
            self._resumed = None
        if self.batch == 6 and s.restarts == 0:
            raise RuntimeError("power loss during batch 6")
        s.record("migration_batch", self.batch)
        self.batch += 1
        await s.checkpoint({"next_batch": self.batch})
        return done() if self.batch == 10 else CONTINUE
