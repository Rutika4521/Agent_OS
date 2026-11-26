"""Budget Office — quotas: tokens, LLM calls, tool calls, steps, wall time."""
from __future__ import annotations

import asyncio

from ..os_api import LabAgent


class TokenHog(LabAgent):
    """Each LLM call costs 300 tokens; budget is 1000."""

    async def act(self, s):
        await s.llm("write the full mission report", 100, 200)
        return s.CONTINUE


class ChattyPlanner(LabAgent):
    """Cheap LLM calls, but too many of them (llm_call_limit)."""

    async def act(self, s):
        await s.llm("one more idea", 1, 1)
        return s.CONTINUE


class InfiniteLooper(LabAgent):
    async def act(self, s):
        return s.CONTINUE


class ToolSpammer(LabAgent):
    async def act(self, s):
        await s.tool("web_search", "starlink")
        return s.CONTINUE


class SlowPoke(LabAgent):
    async def act(self, s):
        await asyncio.sleep(0.1)
        return s.CONTINUE
