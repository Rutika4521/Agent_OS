"""IPC agents: fan-out/fan-in with correlation IDs, backpressure, dead letters, wait timeouts."""
from __future__ import annotations

from . import CONTINUE, done


class Dispatcher:
    """Fans 3 jobs out to Worker-1..3, each tagged with a correlation id."""

    async def step(self, ctx):
        s = ctx.data["sys"]
        for i in (1, 2, 3):
            status = await s.send(f"Worker-{i}", {"job": i, "reply_to": "Aggregator"},
                                  mtype="REQUEST", corr=f"job-{i}")
            s.record("dispatch", status)
        s.log("fanned out 3 jobs")
        return done()


class Worker:
    """Blocks in WAITING(IPC) until a job arrives, processes it, replies with same correlation id."""

    async def step(self, ctx):
        s = ctx.data["sys"]
        msg = await s.recv()
        if msg is None:
            s.record("worker_waited", s.name)
            return s.wait_ipc()
        answer = await s.llm(f"solve {msg.payload['job']}", 30, 50)
        await s.send(msg.payload["reply_to"], {"from": s.name, "answer": answer},
                     mtype="REPLY", corr=msg.correlation_id)
        return done()


class Aggregator:
    """Fan-in: completes only when all three correlated replies have arrived."""

    def __init__(self):
        self.got: dict[str, str] = {}

    async def step(self, ctx):
        s = ctx.data["sys"]
        while (msg := await s.recv()) is not None:
            self.got[msg.correlation_id] = msg.payload["from"]
        if len(self.got) == 3:
            s.record("aggregated", dict(self.got))
            s.log(f"collected replies {sorted(self.got)}")
            return done()
        return s.wait_ipc()


class Flooder:
    """Bursts 8 messages into a bounded (capacity 3, REJECT) mailbox."""

    async def step(self, ctx):
        s = ctx.data["sys"]
        statuses = [await s.send("SlowConsumer", {"n": i}, bounded=True) for i in range(8)]
        s.record("flood", statuses)
        s.board["flood_done"] = True
        s.log(f"burst result: {statuses.count('DELIVERED')} delivered, {statuses.count('DROPPED')} rejected")
        return done()


class SlowConsumer:
    def __init__(self):
        self.read = 0

    async def step(self, ctx):
        s = ctx.data["sys"]
        if not s.board.get("flood_done"):
            return s.sleep(0.03)
        msg = await s.recv(bounded=True)
        if msg is None:
            s.record("consumed", self.read)
            return done()
        self.read += 1
        return CONTINUE


class Ghost:
    """Crashes on its first step with restart policy NEVER."""

    async def step(self, ctx):
        raise RuntimeError("ghost process crashed")


class OrphanWaiter:
    """Messages a dead peer and a non-existent PID, then waits for a reply that never comes."""

    def __init__(self):
        self.sent = False

    async def step(self, ctx):
        s = ctx.data["sys"]
        if not self.sent:
            if not s.board.get("ghost_dead"):
                return s.sleep(0.03)
            s.record("to_dead_peer", await s.send("Ghost", "ping"))
            s.record("to_missing_pid", await s.send(9999, "ping"))
            self.sent = True
            return s.wait_ipc()
        if s.ipc_timed_out:
            s.record("orphan_gave_up", True)
            s.log("no reply before IPC deadline — degrading gracefully")
            return done()
        return s.wait_ipc()
