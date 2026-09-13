import asyncio
import time
from agent_os.memory.context_page import ContextPage

class SwapManager:
    """
    Manages swapping of ContextPages to and from a backing store.
    """
    def __init__(self):
        self._swap_store: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def swap_out(self, page: ContextPage) -> None:
        """
        Store content in swap, set loaded=False, clear content, set content_reference.
        """
        async with self._lock:
            if not page.loaded:
                return
            self._swap_store[page.page_id] = page.content
            page.loaded = False
            page.content = ""
            page.content_reference = f"swap://{page.page_id}"

    async def swap_in(self, page: ContextPage) -> None:
        """
        Load content from swap, set loaded=True, update last_accessed, increment version.
        Must preserve latest version (concurrent updates must not silently overwrite newer state).
        """
        async with self._lock:
            if page.loaded:
                return
            if page.page_id not in self._swap_store:
                raise ValueError(f"Content for page {page.page_id} not found in swap store")
            
            page.content = self._swap_store.pop(page.page_id)
            page.loaded = True
            page.content_reference = ""
            page.last_accessed = time.time()
            page.version += 1
