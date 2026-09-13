"""Agent event loop."""
import asyncio
from typing import Optional

from agent_os.kernel.process_manager import ProcessManager
from agent_os.kernel.state_machine import AgentStepResult
from agent_os.metrics.events import EventManager
from agent_os.config.settings import Settings
from agent_os.runtime.executor import RuntimeExecutor

class AgentEventLoop:
    def __init__(
        self,
        process_manager: ProcessManager,
        scheduler_manager,
        executor: RuntimeExecutor,
        event_manager: EventManager,
        settings: Optional[Settings] = None
    ):
        self.process_manager = process_manager
        self.scheduler_manager = scheduler_manager
        self.executor = executor
        self.event_manager = event_manager
        self.settings = settings
        self._running: bool = False
        self._tick_count: int = 0

    @property
    def tick_count(self) -> int:
        return self._tick_count

    async def start(self) -> None:
        self._running = True
        while self._running:
            ready = await self.process_manager.process_table.get_runnable()
            if not ready:
                active = await self.process_manager.process_table.get_active()
                if not active:
                    break
                await asyncio.sleep(0.01)
                continue
            
            selected = self.scheduler_manager.select_next(ready)
            if selected is None:
                await asyncio.sleep(0.01)
                continue
                
            try:
                await self.executor.execute_step(selected)
            except Exception:
                pass
            
            self._tick_count += 1
            await asyncio.sleep(0)

    async def stop(self) -> None:
        self._running = False

    async def run_until_complete(self) -> None:
        await self.start()

    async def tick(self) -> Optional[AgentStepResult]:
        ready = await self.process_manager.process_table.get_runnable()
        if not ready:
            return None
        
        selected = self.scheduler_manager.select_next(ready)
        if selected is None:
            return None
            
        result = await self.executor.execute_step(selected)
        self._tick_count += 1
        return result
