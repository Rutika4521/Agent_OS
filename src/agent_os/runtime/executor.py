"""Runtime executor for agent processes."""
import asyncio
from typing import Optional, Dict

from agent_os.kernel.state_machine import ProcessState, StepStatus, AgentStepResult
from agent_os.kernel.process_manager import ProcessManager
from agent_os.kernel.agent_process import AgentProcess
from agent_os.metrics.events import EventManager
from agent_os.config.settings import Settings
from agent_os.sdk.agent import AgentContext

from agent_os.runtime.timeout import execute_with_timeout, StepTimeoutError
from agent_os.runtime.cancellation import CancellationToken

class RuntimeExecutor:
    def __init__(self, process_manager: ProcessManager, resource_manager, context_manager, event_manager: EventManager, settings: Optional[Settings] = None):
        self.process_manager = process_manager
        self.resource_manager = resource_manager
        self.context_manager = context_manager
        self.event_manager = event_manager
        self.settings = settings
        self._cancellation_tokens: Dict[int, CancellationToken] = {}

    def get_cancellation_token(self, process_id: int) -> CancellationToken:
        if process_id not in self._cancellation_tokens:
            self._cancellation_tokens[process_id] = CancellationToken()
        return self._cancellation_tokens[process_id]

    async def cancel_process(self, process_id: int) -> None:
        token = self.get_cancellation_token(process_id)
        token.cancel()

    async def execute_step(self, process: AgentProcess) -> AgentStepResult:
        token = self.get_cancellation_token(process.process_id)
        
        if token.is_cancelled:
            await self.process_manager.set_state(process.process_id, ProcessState.RUNNING)
            await self.process_manager.set_state(process.process_id, ProcessState.CANCELLING)
            await self.process_manager.set_state(process.process_id, ProcessState.CANCELLED)
            return AgentStepResult(status=StepStatus.FAILED, error="Process cancelled")

        if self.resource_manager is not None:
            if hasattr(self.resource_manager, "can_execute"):
                can_exec = self.resource_manager.can_execute(process)
                if asyncio.iscoroutine(can_exec):
                    can_exec = await can_exec
                if not can_exec:
                    await self.process_manager.set_state(process.process_id, ProcessState.RUNNING)
                    await self.process_manager.set_state(process.process_id, ProcessState.FAILED)
                    return AgentStepResult(status=StepStatus.FAILED, error="Resource limit exceeded")

        await self.process_manager.set_state(process.process_id, ProcessState.RUNNING)
        
        context = AgentContext(process_id=process.process_id, data={})
        timeout = getattr(process.resource_limits, 'wall_time_limit', 60.0) if hasattr(process, 'resource_limits') else 60.0
        
        try:
            result = await execute_with_timeout(process.agent.step(context), timeout)
        except StepTimeoutError:
            await self.process_manager.set_state(process.process_id, ProcessState.FAILED)
            return AgentStepResult(status=StepStatus.FAILED, error="Step timed out")
        except asyncio.CancelledError:
            await self.process_manager.set_state(process.process_id, ProcessState.CANCELLING)
            await self.process_manager.set_state(process.process_id, ProcessState.CANCELLED)
            return AgentStepResult(status=StepStatus.FAILED, error="Process cancelled")
        except Exception as e:
            await self.process_manager.set_state(process.process_id, ProcessState.FAILED)
            return AgentStepResult(status=StepStatus.FAILED, error=str(e))
            
        if self.resource_manager is not None:
            if hasattr(self.resource_manager, "consume_step"):
                consume = self.resource_manager.consume_step(process)
                if asyncio.iscoroutine(consume):
                    await consume
            
        if result.status in (StepStatus.CONTINUE, StepStatus.YIELD):
            await self.process_manager.set_state(process.process_id, ProcessState.READY)
        elif result.status == StepStatus.WAIT:
            reason = getattr(result, 'wait_reason', None)
            await self.process_manager.set_state(process.process_id, ProcessState.WAITING, wait_reason=reason)
        elif result.status == StepStatus.BLOCK:
            reason = getattr(result, 'wait_reason', None)
            await self.process_manager.set_state(process.process_id, ProcessState.BLOCKED, wait_reason=reason)
        elif result.status == StepStatus.COMPLETED:
            await self.process_manager.set_state(process.process_id, ProcessState.COMPLETED)
        elif result.status == StepStatus.FAILED:
            await self.process_manager.set_state(process.process_id, ProcessState.FAILED)
            
        return result
