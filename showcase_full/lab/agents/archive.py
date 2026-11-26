"""Archive — paged agent memory: LRU swap, pinned pages, page faults, versions, pressure."""
from __future__ import annotations

from ..os_api import LabAgent


class Librarian(LabAgent):
    """Pins 2 pages (system prompt + policy). They must survive every eviction."""

    def __init__(self):
        self.n = 0

    async def act(self, s):
        self.n += 1
        if self.n == 1:
            await s.page_add("SYSTEM PROMPT: you are the archive librarian", pinned=True)
            await s.page_add("POLICY: never delete telemetry", pinned=True)
            s.board["librarian_ready"] = True
            return s.sleep(0.03)
        if not s.board.get("indexer_done"):
            return s.sleep(0.03)
        s.record("pinned_survived", [await s.page_loaded(0), await s.page_loaded(1)])
        s.board["librarian_done"] = True
        return s.done()


class Indexer(LabAgent):
    """Writes 12 pages into an 8-page global budget, then reads page 0 back (page fault)."""

    def __init__(self):
        self.written = 0

    async def act(self, s):
        if not s.board.get("librarian_ready"):
            return s.sleep(0.03)
        if self.written < 12:
            await s.page_add(f"telemetry chunk #{self.written} " + "x" * 64)
            self.written += 1
            return s.CONTINUE
        was_loaded = await s.page_loaded(0)
        content = await s.page_read(0)
        s.record("indexer_page0", {"was_swapped_out": not was_loaded,
                                   "intact": content.startswith("telemetry chunk #0 "),
                                   "loaded_now": await s.page_loaded(0)})
        s.board["indexer_done"] = True
        return s.done()


class Editor(LabAgent):
    """Updates one page three times; versions must advance 1 → 4."""

    async def act(self, s):
        idx = await s.page_add("draft v1")
        versions = [await s.page_update(idx, f"draft v{i}") for i in (2, 3, 4)]
        s.record("editor_versions", versions)
        s.record("editor_content", await s.page_read(idx))
        return s.done()


class PinHog(LabAgent):
    """Pins more pages than the whole budget allows."""

    async def act(self, s):
        if not s.board.get("librarian_done"):
            return s.sleep(0.03)
        for i in range(10):
            await s.page_add(f"pinned blob {i}", pinned=True)
        s.record("pinhog_loaded", s.loaded_pages_total())
        return s.done()
