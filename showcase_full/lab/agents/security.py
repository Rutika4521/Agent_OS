"""Security — capability-gated tools, live revocation, default capabilities, sandbox."""
from __future__ import annotations

from ..os_api import LabAgent


class ToolUser(LabAgent):
    def __init__(self, tools: list[str]):
        self.tools = tools

    async def act(self, s):
        for t in self.tools:
            await s.tool(t)
            s.record(f"tool_ok:{s.name}", t)
        return s.done()


class Contractor(LabAgent):
    """Writes to the DB every step; the operator revokes db.write after 3 writes."""

    async def act(self, s):
        await s.tool("db_write", "row")
        s.record("contractor_writes", True)
        return s.sleep(0.02)


class BuildBot(LabAgent):
    """Runs code in the sandbox, then a runaway subprocess that must be killed."""

    async def act(self, s):
        res = await s.sandbox("print(6*7)")
        s.record("sandbox_stdout", res.stdout.strip())
        try:
            await s.sandbox("import time; time.sleep(30)", timeout=0.5)
        except Exception as e:  # SandboxTimeout
            s.record("sandbox_timeout", type(e).__name__)
        return s.done()


class Intruder(LabAgent):
    """Tries to execute code without the sys.exec capability."""

    async def act(self, s):
        await s.sandbox("print('pwned')")
        return s.done()


class Probe(LabAgent):
    """Records the capabilities the kernel gave it, then tries a tool."""

    def __init__(self, tool: str):
        self.tool = tool

    async def act(self, s):
        s.record(f"caps:{s.name}", sorted(s.k.capabilities.get_capabilities(s.pid)))
        await s.tool(self.tool)
        s.record(f"tool_ok:{s.name}", self.tool)
        return s.done()


class SandboxUser(LabAgent):
    """Has sys.exec, but the sandbox is disabled in this mission's settings."""

    async def act(self, s):
        await s.sandbox("print(1)")
        return s.done()
