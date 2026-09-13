"""Step timeout enforcement."""
import asyncio
from typing import Any, Coroutine

class StepTimeoutError(Exception):
    """Raised when a step exceeds its time limit."""
    def __init__(self, timeout: float):
        self.timeout = timeout
        super().__init__(f"Step timed out after {timeout}s")

async def execute_with_timeout(coro: Coroutine, timeout_seconds: float) -> Any:
    """Execute a coroutine with a timeout. Raises StepTimeoutError on timeout."""
    try:
        return await asyncio.wait_for(coro, timeout=timeout_seconds)
    except asyncio.TimeoutError:
        raise StepTimeoutError(timeout_seconds)
