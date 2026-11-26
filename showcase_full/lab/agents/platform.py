"""Platform — agents driven from outside: the REST API acts on the live native kernel."""
from __future__ import annotations

import asyncio

from ..os_api import LabAgent


class Beacon(LabAgent):
    """Waits for a message that arrives over HTTP (POST /ipc/send)."""

    async def act(self, s):
        msg = await s.recv()
        if msg is None:
            s.board["beacon_waiting"] = True
            return s.wait_ipc()
        s.record("beacon_got", msg.payload)
        return s.done()


class Hoarder(LabAgent):
    """Holds 'telemetry-db' and loops; cancelled over REST."""

    async def act(self, s):
        if not s.holds("telemetry-db"):
            await s.acquire("telemetry-db")
            s.board["hoarder_holds"] = True
        await asyncio.sleep(0.005)
        return s.sleep(0.01)


class Archivist(LabAgent):
    """Needs 'telemetry-db' after the Hoarder."""

    async def act(self, s):
        if not s.board.get("hoarder_holds"):
            return s.sleep(0.02)
        if not s.holds("telemetry-db"):
            if not await s.acquire("telemetry-db"):
                return s.BLOCK
        s.record("archivist_got_lock", True)
        await s.release("telemetry-db")
        return s.done()


class Metronome(LabAgent):
    """Ticks 30 times; an operator tries to pause it over REST."""

    def __init__(self):
        self.left = 30

    async def act(self, s):
        s.record("metronome_t", asyncio.get_event_loop().time())
        await asyncio.sleep(0.004)
        self.left -= 1
        return s.done() if self.left == 0 else s.CONTINUE
