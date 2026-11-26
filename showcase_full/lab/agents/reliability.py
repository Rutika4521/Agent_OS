"""Reliability — supervisor policies, backoff, step timeouts, LLM outages, checkpoints."""
from __future__ import annotations

import asyncio
import time

from ..os_api import LabAgent


class Crasher(LabAgent):
    """Crashes on the first step of its first `fail_runs` runs, then succeeds (99 = forever)."""

    def __init__(self, fail_runs: int, steps: int = 2):
        self.fail_runs, self.steps, self.n = fail_runs, steps, 0

    def on_restart(self, _checkpoint):
        self.n = 0

    async def act(self, s):
        self.n += 1
        if self.n == 1:
            s.record(f"run_start:{s.name}", time.time())
            if s.restarts < self.fail_runs:
                s.record(f"crash_at:{s.name}", time.time())
                raise RuntimeError(f"simulated crash (run {s.restarts + 1})")
        return s.done() if self.n >= self.steps else s.CONTINUE


class Quitter(LabAgent):
    """Returns StepStatus.FAILED (no exception) on its first run, succeeds after restart."""

    async def act(self, s):
        if s.restarts == 0:
            return s.failed("sensor calibration out of range")
        return s.done()


class HungAgent(LabAgent):
    """First run hangs 10 s inside a step; the step timeout must cut it short."""

    async def act(self, s):
        if s.restarts == 0:
            await asyncio.sleep(10)
        return s.done()


class LLMFlaky(LabAgent):
    """First call hits a provider outage; the retry after restart succeeds."""

    async def act(self, s):
        answer = await s.llm("classify anomaly", 20, 30, provider="outage" if s.restarts == 0 else "mock")
        s.record("llm_recovered", answer)
        return s.done()


class LLMStalled(LabAgent):
    """First call hangs at the provider and times out (LLM_TIMEOUT)."""

    async def act(self, s):
        answer = await s.llm("summarise downlink", 20, 30, provider="stalled" if s.restarts == 0 else "mock")
        s.record("llm_timeout_recovered", answer)
        return s.done()


class MigrationJob(LabAgent):
    """10 batches, checkpoint after each. Loses power at batch 6 once; must resume, not redo."""

    def __init__(self):
        self.batch, self._resumed = 0, None

    def on_restart(self, checkpoint):
        self.batch = checkpoint["next_batch"] if checkpoint else 0
        self._resumed = self.batch

    async def act(self, s):
        if self._resumed is not None:
            s.record("migration_resumed_from", self._resumed)
            self._resumed = None
        if self.batch == 6 and s.restarts == 0:
            raise RuntimeError("power loss during batch 6")
        s.record("migration_batch", self.batch)
        self.batch += 1
        await s.checkpoint({"next_batch": self.batch})
        return s.done() if self.batch == 10 else s.CONTINUE
