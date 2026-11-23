import uuid
import time
import asyncio
from agent_os.config.settings import Settings
from agent_os.metrics.events import EventManager, EventType
from agent_os.memory.context_page import ContextPage
from agent_os.memory.swap_manager import SwapManager
from agent_os.memory.lru import LRUEvictionPolicy, MemoryPressureError

class ContextManager:
    """
    Manages contexts, which consist of sets of ContextPages.
    Provides memory limits, eviction, and swapping using SwapManager and LRUEvictionPolicy.
    """
    def __init__(self, settings: Settings, event_manager: EventManager):
        self.settings = settings
        self.event_manager = event_manager
        self._contexts: dict[str, list[ContextPage]] = {}
        self._swap_manager = SwapManager()
        self._lru = LRUEvictionPolicy()
        self._lock = asyncio.Lock()
        
        self.max_loaded_pages = getattr(settings, "max_loaded_pages", 100)

    async def create(self, process_id: int) -> str:
        """Create a new context and return its context_id (uuid)."""
        async with self._lock:
            context_id = str(uuid.uuid4())
            self._contexts[context_id] = []
            return context_id

    async def add_page(self, context_id: str, process_id: int, content: str, pinned: bool = False) -> ContextPage:
        """Add a page, enforce max_loaded_pages, evict if needed."""
        async with self._lock:
            if context_id not in self._contexts:
                raise ValueError(f"Context {context_id} does not exist")
            
            await self._evict_if_needed()
            
            index = len(self._contexts[context_id])
            page = ContextPage(
                process_id=process_id,
                index=index,
                content=content,
                pinned=pinned
            )
            self._contexts[context_id].append(page)
            return page

    async def load(self, context_id: str) -> list[ContextPage]:
        """Return all pages for a context."""
        async with self._lock:
            if context_id not in self._contexts:
                raise ValueError(f"Context {context_id} does not exist")
            return list(self._contexts[context_id])

    async def save(self, context_id: str) -> None:
        """Persist state (no-op for in-memory, hook for persistence)."""
        pass

    async def swap_out(self, context_id: str, page_index: int) -> None:
        """Swap out specific page, emit CONTEXT_SWAP_OUT event."""
        async with self._lock:
            if context_id not in self._contexts:
                raise ValueError(f"Context {context_id} does not exist")
            
            pages = self._contexts[context_id]
            if not (0 <= page_index < len(pages)):
                raise IndexError(f"Invalid page index {page_index}")
            
            page = pages[page_index]
            if page.loaded:
                await self._swap_manager.swap_out(page)
                await self.event_manager.emit(
                    EventType.CONTEXT_SWAP_OUT,
                    process_id=page.process_id,
                    metadata={"context_id": context_id, "page_id": page.page_id},
                )

    async def swap_in(self, context_id: str, page_index: int) -> None:
        """Swap in specific page, emit CONTEXT_SWAP_IN event."""
        async with self._lock:
            if context_id not in self._contexts:
                raise ValueError(f"Context {context_id} does not exist")
            
            pages = self._contexts[context_id]
            if not (0 <= page_index < len(pages)):
                raise IndexError(f"Invalid page index {page_index}")
            
            page = pages[page_index]
            if not page.loaded:
                await self._evict_if_needed()
                await self._swap_manager.swap_in(page)
                await self.event_manager.emit(
                    EventType.CONTEXT_SWAP_IN,
                    process_id=page.process_id,
                    metadata={"context_id": context_id, "page_id": page.page_id},
                )

    async def get_page(self, context_id: str, page_index: int) -> ContextPage | None:
        """Get a page. If swapped out, swap it in."""
        async with self._lock:
            if context_id not in self._contexts:
                return None
            pages = self._contexts[context_id]
            if not (0 <= page_index < len(pages)):
                return None
            
            page = pages[page_index]
            if not page.loaded:
                await self._evict_if_needed()
                await self._swap_manager.swap_in(page)
                await self.event_manager.emit(
                    EventType.CONTEXT_SWAP_IN,
                    process_id=page.process_id,
                    metadata={"context_id": context_id, "page_id": page.page_id},
                )
            
            page.last_accessed = time.time()
            return page

    async def update_page(self, context_id: str, page_index: int, content: str) -> None:
        """Update content, increment version, update last_accessed."""
        async with self._lock:
            if context_id not in self._contexts:
                raise ValueError(f"Context {context_id} does not exist")
            
            pages = self._contexts[context_id]
            if not (0 <= page_index < len(pages)):
                raise IndexError(f"Invalid page index {page_index}")
            
            page = pages[page_index]
            if not page.loaded:
                await self._evict_if_needed()
                await self._swap_manager.swap_in(page)
                await self.event_manager.emit(
                    EventType.CONTEXT_SWAP_IN,
                    process_id=page.process_id,
                    metadata={"context_id": context_id, "page_id": page.page_id},
                )
            
            page.content = content
            page.last_accessed = time.time()
            page.version += 1

    async def remove(self, context_id: str) -> None:
        """Remove entire context."""
        async with self._lock:
            self._contexts.pop(context_id, None)

    def _count_loaded_pages(self) -> int:
        """Count total loaded pages across all contexts."""
        return sum(1 for pages in self._contexts.values() for p in pages if p.loaded)

    async def _evict_if_needed(self) -> None:
        """If loaded pages > max_loaded_pages, use LRU to evict."""
        while self._count_loaded_pages() >= self.max_loaded_pages:
            all_pages = [p for pages in self._contexts.values() for p in pages]
            try:
                victim = self._lru.select_victim(all_pages)
                if victim:
                    await self._swap_manager.swap_out(victim)
                    
                    # Find context_id for victim
                    context_id = next(cid for cid, pages in self._contexts.items() if victim in pages)
                    await self.event_manager.emit(
                        EventType.CONTEXT_SWAP_OUT,
                        process_id=victim.process_id,
                        metadata={"context_id": context_id, "page_id": victim.page_id},
                    )
            except MemoryPressureError:
                break
