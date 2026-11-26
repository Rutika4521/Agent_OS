"""Mission Control — scheduling: priority preemption, aging, fair share, cooperative yield."""
from __future__ import annotations

import asyncio
import time

from ..os_api import LabAgent


class FlightDirector(LabAgent):
    """Priority 10. Must be the very first agent the scheduler ever picks."""

    def __init__(self):
        self.n = 0

    async def act(self, s):
        self.n += 1
        await s.llm(f"go/no-go poll {self.n}", 40, 60)
        return s.done() if self.n >= 3 else s.CONTINUE


class TelemetryCruncher(LabAgent):
    """High-priority CPU-bound work that would starve anything below it."""

    def __init__(self, steps: int = 45):
        self.left = steps

    async def act(self, s):
        s.board.setdefault("crunchers_alive", set()).add(s.name)
        await asyncio.sleep(0.008)
        self.left -= 1
        if self.left == 0:
            s.board["crunchers_alive"].discard(s.name)
            return s.done()
        return s.CONTINUE


class NightJanitor(LabAgent):
    """Priority 1. Only the aging policy can get it scheduled while the crunchers run."""

    def __init__(self):
        self.born, self.n = time.time(), 0

    async def act(self, s):
        self.n += 1
        if self.n == 1:
            s.record("janitor_first_run", {"waited": round(time.time() - self.born, 2),
                                           "crunchers_alive": len(s.board.get("crunchers_alive", ()))})
        return s.done() if self.n >= 2 else s.CONTINUE


class Tenant(LabAgent):
    """Identical workloads with different weights under the weighted-fair scheduler."""

    def __init__(self, steps: int = 60):
        self.left = steps

    async def act(self, s):
        self.left -= 1
        return s.done() if self.left == 0 else s.CONTINUE


class Courteous(LabAgent):
    """Returns YIELD every step: it must stay runnable and still finish."""

    def __init__(self, steps: int = 5):
        self.left = steps

    async def act(self, s):
        self.left -= 1
        s.record("yields", s.name)
        return s.done() if self.left == 0 else s.YIELD
