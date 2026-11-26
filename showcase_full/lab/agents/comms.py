"""Comms — IPC: fan-out/fan-in, three overflow policies, ordering, dead peers, wait timeouts."""
from __future__ import annotations

from ..os_api import LabAgent


class Dispatcher(LabAgent):
    """Fans 3 analysis jobs out, each tagged with a correlation id."""

    async def act(self, s):
        for i in (1, 2, 3):
            s.record("dispatch", await s.send(f"Analyst-{i}", {"job": i, "reply_to": "Aggregator"},
                                              mtype="REQUEST", corr=f"job-{i}"))
        return s.done()


class Analyst(LabAgent):
    """Parks in WAITING(IPC) until a job arrives, answers it with the same correlation id."""

    async def act(self, s):
        msg = await s.recv()
        if msg is None:
            s.record("analyst_waited", s.name)
            return s.wait_ipc()
        answer = await s.llm(f"analyse orbit {msg.payload['job']}", 30, 50)
        await s.send(msg.payload["reply_to"], {"from": s.name, "answer": answer},
                     mtype="REPLY", corr=msg.correlation_id)
        return s.done()


class Aggregator(LabAgent):
    def __init__(self):
        self.got: dict[str, str] = {}

    async def act(self, s):
        while (msg := await s.recv()) is not None:
            self.got[msg.correlation_id] = msg.payload["from"]
        if len(self.got) == 3:
            s.record("aggregated", dict(self.got))
            return s.done()
        return s.wait_ipc()


class Flooder(LabAgent):
    """Bursts 8 messages into a capacity-3 mailbox with the given overflow policy."""

    def __init__(self, box: str, target: str):
        self.box, self.target = box, target

    async def act(self, s):
        statuses = [await s.send(self.target, {"n": i}, box=self.box) for i in range(8)]
        s.record(f"flood:{self.box}", statuses)
        s.board[f"flood_done:{self.box}"] = True
        return s.done()


class Drainer(LabAgent):
    """Waits for the flood, then drains its mailbox and records what survived."""

    def __init__(self, box: str):
        self.box, self.got = box, []

    async def act(self, s):
        if not s.board.get(f"flood_done:{self.box}"):
            return s.sleep(0.03)
        msg = await s.recv(box=self.box)
        if msg is None:
            s.record(f"drained:{self.box}", list(self.got))
            return s.done()
        self.got.append(msg.payload["n"])
        return s.CONTINUE


class BlockingProducer(LabAgent):
    """Sends 3 messages into a capacity-2 BLOCK mailbox nobody reads.
    The 3rd send blocks inside the step; only the kernel's step timeout can end it."""

    async def act(self, s):
        for i in range(3):
            s.record("block_sent", i)
            await s.send("NobodyHome", {"n": i}, box="block")
        return s.done()


class NobodyHome(LabAgent):
    async def act(self, s):
        return s.sleep(0.05) if not s.board.get("producer_dead") else s.done()


class Sequencer(LabAgent):
    """Sends 5 numbered messages to the Collator."""

    async def act(self, s):
        for i in range(5):
            await s.send("Collator", {"from": s.name, "seq": i})
        s.board[f"seq_done:{s.name}"] = True
        return s.done()


class Collator(LabAgent):
    def __init__(self):
        self.got: list[tuple[str, int, int]] = []

    async def act(self, s):
        while (msg := await s.recv()) is not None:
            self.got.append((msg.payload["from"], msg.payload["seq"], msg.sequence_number))
        if len(self.got) == 10:
            s.record("collated", list(self.got))
            return s.done()
        return s.wait_ipc()


class Ghost(LabAgent):
    """Crashes on its first step with restart policy NEVER."""

    async def act(self, s):
        raise RuntimeError("ground station lost power")


class Pinger(LabAgent):
    """Pings a peer that crashed, then waits for a reply that never comes."""

    def __init__(self):
        self.sent = False

    async def act(self, s):
        if not self.sent:
            if not s.board.get("ghost_dead"):
                return s.sleep(0.03)
            await s.send("Ghost", "ping")
            self.sent = True
            return s.wait_ipc()
        if s.ipc_timed_out:
            s.record("pinger_gave_up", True)
            return s.done()
        return s.wait_ipc()


class DeadLetterProbe(LabAgent):
    """Sends to a terminated process and to a PID that never existed."""

    async def act(self, s):
        if not s.board.get("ghost_dead"):
            return s.sleep(0.03)
        s.record("to_dead_peer", await s.send("Ghost", "hello?"))
        s.record("to_missing_pid", await s.send(9999, "hello?"))
        return s.done()


class Lonely(LabAgent):
    """Waits for mail from its partner, who is waiting for mail from it."""

    async def act(self, s):
        if await s.recv() is not None:
            return s.done()
        s.record("lonely_waiting", s.name)
        return s.wait_ipc()
