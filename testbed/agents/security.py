"""Security agents: capability-gated tools, live revocation, sandboxed execution."""
from __future__ import annotations

import sys

from agent_os.sandbox.sandbox import SandboxTimeout

from . import CONTINUE, done


class ToolUser:
    """Calls a fixed list of tools in order."""

    def __init__(self, tools: list[str]):
        self.tools = list(tools)

    async def step(self, ctx):
        s = ctx.data["sys"]
        tool = self.tools.pop(0)
        await s.tool(tool)
        s.record(f"tool_ok:{s.name}", tool)
        return done() if not self.tools else CONTINUE


class Contractor:
    """Writes to the DB every step; the operator revokes db.write mid-run."""

    async def step(self, ctx):
        s = ctx.data["sys"]
        await s.tool("db_write", "row")
        s.record("contractor_writes", 1)
        return s.sleep(0.05)


class BuildBot:
    def __init__(self):
        self.n = 0

    async def step(self, ctx):
        s = ctx.data["sys"]
        self.n += 1
        if self.n == 1:
            res = await s.sandbox([sys.executable, "-c", "print(6*7)"])
            s.record("sandbox_stdout", res.stdout.strip())
            return CONTINUE
        if self.n == 2:
            try:
                await s.sandbox([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.5)
                s.record("sandbox_timeout", False)
            except SandboxTimeout:
                s.record("sandbox_timeout", True)
                s.log("runaway subprocess killed by sandbox after 0.5s")
            return CONTINUE
        return done()


class Hacker:
    """No sys.exec capability, tries to shell out anyway."""

    async def step(self, ctx):
        s = ctx.data["sys"]
        await s.sandbox([sys.executable, "-c", "print('pwned')"])
        return done()
