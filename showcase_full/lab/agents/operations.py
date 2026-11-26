"""Operations — lifecycle: pause/resume, cancel, process trees, orphan policies, limits."""
from __future__ import annotations

import asyncio
import time

from agent_os.kernel.process_manager import ProcessLimitReached

from ..os_api import LabAgent


class BatchReport(LabAgent):
    def __init__(self, steps: int = 20):
        self.left = steps

    async def act(self, s):
        s.record("batch_step_t", time.time())
        await asyncio.sleep(0.005)
        self.left -= 1
        return s.done() if self.left == 0 else s.CONTINUE


class Stargazer(LabAgent):
    """Sleeps 0.1 s between observations; gets paused *while asleep*."""

    def __init__(self):
        self.n = 0

    async def act(self, s):
        self.n += 1
        s.record("stargazer_t", time.time())
        if self.n == 1:
            s.board["stargazer_asleep"] = True
            return s.sleep(0.1)
        return s.done() if self.n >= 3 else s.sleep(0.01)


class RunawayCrawler(LabAgent):
    """Grabs 'crawl-db' and never stops. The operator cancels it."""

    async def act(self, s):
        if not s.holds("crawl-db"):
            await s.acquire("crawl-db")
            s.board["crawler_holds"] = True
        await asyncio.sleep(0.005)
        return s.CONTINUE


class ReportWriter(LabAgent):
    async def act(self, s):
        if not s.board.get("crawler_holds"):
            return s.sleep(0.03)
        if not s.holds("crawl-db"):
            if not await s.acquire("crawl-db"):
                return s.BLOCK
        s.record("report_writer_got_lock", True)
        await s.release("crawl-db")
        return s.done()


class MailWatcher(LabAgent):
    """Waits for mail forever (the mission's IPC timeout keeps re-arming). Cancelled while WAITING."""

    async def act(self, s):
        if await s.recv() is not None:
            return s.done()
        s.board["watcher_waiting"] = True
        return s.wait_ipc()


class Worker(LabAgent):
    """Long-lived child: dies only through the orphan policy (or finishes after `steps`)."""

    def __init__(self, steps: int | None = None):
        self.steps = steps

    async def act(self, s):
        if self.steps is not None:
            self.steps -= 1
            if self.steps <= 0:
                s.record("worker_finished", s.name)
                return s.done()
        return s.sleep(0.05)


class Foreman(LabAgent):
    """Spawns 4 children with a child limit of 3, then crashes (restart NEVER)."""

    def __init__(self):
        self.n = 0

    async def act(self, s):
        self.n += 1
        if self.n == 1:
            for i in range(1, 5):
                try:
                    await s.spawn(Worker(), name=f"Rigger-{i}", priority=3)
                    s.record("children_spawned", f"Rigger-{i}")
                except ProcessLimitReached as e:
                    s.record("child_rejected", str(e))
            return s.sleep(0.15)
        if self.n < 3:
            return s.sleep(0.15)
        raise RuntimeError("foreman crashed with riggers still working")


class Manager(LabAgent):
    """Middle of a 3-level tree: spawns one Intern, then idles."""

    async def act(self, s):
        if not s.board.get("intern_spawned"):
            await s.spawn(Worker(), name="Intern", priority=3)
            s.board["intern_spawned"] = True
        return s.sleep(0.05)


class Director(LabAgent):
    """Top of the tree: spawns a Manager, waits for the Intern to exist, then crashes."""

    def __init__(self):
        self.spawned = False

    async def act(self, s):
        if not self.spawned:
            await s.spawn(Manager(), name="Manager", priority=4)
            self.spawned = True
        if not s.board.get("intern_spawned"):
            return s.sleep(0.03)
        raise RuntimeError("director resigned abruptly")


class Founder(LabAgent):
    """Spawns a child with orphan_policy=KEEP, then completes; the child must outlive it."""

    async def act(self, s):
        await s.spawn(Worker(steps=6), name="Successor", priority=3, orphan_policy="KEEP")
        s.board["founder_done_t"] = time.time()
        return s.done()


class Recruiter(LabAgent):
    """Spawns workers until the kernel's global process limit refuses."""

    async def act(self, s):
        for i in range(1, 20):
            try:
                await s._os.spawn(Worker(steps=1), name=f"Hire-{i}", priority=2)
                s.record("hired", f"Hire-{i}")
            except ProcessLimitReached as e:
                s.record("hire_refused", str(e))
                break
        return s.done()
