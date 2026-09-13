"""Cooperative cancellation tokens."""
import asyncio

class CancellationToken:
    """Token for cooperative cancellation of agent processes."""
    def __init__(self):
        self._cancelled = False
        self._event = asyncio.Event()
    
    def cancel(self) -> None:
        self._cancelled = True
        self._event.set()
    
    @property
    def is_cancelled(self) -> bool:
        return self._cancelled
    
    async def wait_for_cancellation(self) -> None:
        await self._event.wait()
    
    def reset(self) -> None:
        self._cancelled = False
        self._event.clear()
