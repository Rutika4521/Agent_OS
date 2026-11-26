"""Quota agents: each one deliberately runs away on a different resource axis."""
from __future__ import annotations

import asyncio

from . import CONTINUE


class TokenHog:
    """400 tokens per LLM call against a 1000-token budget."""

    async def step(self, ctx):
        s = ctx.data["sys"]
        await s.llm("summarise the entire internet", 100, 300)
        return CONTINUE


class InfiniteLooper:
    """Never finishes — only the step quota stops it."""

    async def step(self, ctx):
        return CONTINUE


class ToolSpammer:
    async def step(self, ctx):
        s = ctx.data["sys"]
        await s.tool("http_get", "https://example.invalid")
        return CONTINUE


class SlowPoke:
    """Each step takes 0.25s of wall time against a 0.6s budget."""

    async def step(self, ctx):
        await asyncio.sleep(0.25)
        return CONTINUE
