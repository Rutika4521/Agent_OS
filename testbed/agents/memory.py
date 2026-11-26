"""Memory agents: LRU paging, pinned pages, swap-in integrity, memory pressure."""
from __future__ import annotations

from . import CONTINUE, done


class Librarian:
    """Pins 2 pages (system prompt) — they must survive every eviction."""

    def __init__(self):
        self.n = 0

    async def step(self, ctx):
        s = ctx.data["sys"]
        self.n += 1
        if self.n == 1:
            await s.page_add("SYSTEM PROMPT: you are a librarian", pinned=True)
            await s.page_add("POLICY: never delete books", pinned=True)
            s.board["librarian_ready"] = True
            return s.sleep(0.03)
        if not s.board.get("indexer_done"):
            return s.sleep(0.03)
        s.record("pinned_survived", [await s.page_is_loaded(0), await s.page_is_loaded(1)])
        s.board["librarian_done"] = True
        return done()


class Indexer:
    """Writes 12 pages into an 8-page global budget, then reads page 0 back."""

    def __init__(self):
        self.written = 0

    async def step(self, ctx):
        s = ctx.data["sys"]
        if not s.board.get("librarian_ready"):
            return s.sleep(0.03)
        if self.written < 12:
            await s.page_add(f"document #{self.written} " + "x" * 64)
            self.written += 1
            return CONTINUE
        was_loaded = await s.page_is_loaded(0)
        content = await s.page_read(0)          # page fault → swap in
        s.record("indexer_page0", {"was_swapped_out": not was_loaded,
                                   "intact": content.startswith("document #0 "),
                                   "loaded_now": await s.page_is_loaded(0)})
        s.board["indexer_done"] = True
        return done()


class PinHog:
    """Pins more pages than the whole budget allows."""

    async def step(self, ctx):
        s = ctx.data["sys"]
        if not s.board.get("librarian_done"):
            return s.sleep(0.03)
        for i in range(10):
            await s.page_add(f"pinned blob {i}", pinned=True)
        s.record("pinhog_loaded", s.loaded_pages_total())
        return done()
