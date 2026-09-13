from agent_os.memory.context_page import ContextPage

class MemoryPressureError(Exception):
    """Raised when memory pressure is too high and no pages can be evicted."""
    pass

class LRUEvictionPolicy:
    """
    Least Recently Used (LRU) eviction policy for context memory.
    """
    def select_victim(self, pages: list[ContextPage]) -> ContextPage | None:
        """
        Choose page with oldest last_accessed among pages that are loaded AND not pinned.
        If no page can be evicted (all pinned), return None.
        Must raise MemoryPressureError when called and returns None.
        """
        candidates = [p for p in pages if p.loaded and not p.pinned]
        if not candidates:
            raise MemoryPressureError("No unpinned pages available for eviction")
        
        victim = min(candidates, key=lambda p: p.last_accessed)
        return victim
