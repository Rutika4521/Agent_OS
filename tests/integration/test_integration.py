"""
Agent-OS Integration Tests (§75).

10 required integration tests combining multiple subsystems.
"""

import pytest
import asyncio
import time

from agent_os.config.settings import Settings, reset_settings
from agent_os.metrics.events import EventManager
from agent_os.kernel.process_table import ProcessTable
from agent_os.kernel.process_manager import ProcessManager
from agent_os.kernel.state_machine import (
    StepStatus, AgentStepResult, WaitReason, ProcessState,
)
from agent_os.resources.manager import ResourceManager, ResourceLimitExceeded
from agent_os.resources.quota import ResourceLimits
from agent_os.scheduler.scheduler import SchedulerManager
from agent_os.scheduler.priority import PriorityScheduler
from agent_os.scheduler.weighted_fair import WeightedFairScheduler
from agent_os.ipc.ipc_manager import IPCManager
from agent_os.memory.context_manager import ContextManager
from agent_os.memory.checkpoint import CheckpointManager
from agent_os.supervisor.supervisor import Supervisor
from agent_os.supervisor.failure import FailureType
from agent_os.supervisor.restart import RestartManager
from agent_os.synchronization.deadlock import DeadlockDetector
from agent_os.runtime.executor import RuntimeExecutor
from agent_os.runtime.event_loop import AgentEventLoop
from sdk.agent import AgentContext


# --- Test agents ---

class SimpleAgent:
    def __init__(self, steps=1):
        self._steps = steps
        self._current = 0

    async def step(self, context: AgentContext) -> AgentStepResult:
        self._current += 1
        if self._current >= self._steps:
            return AgentStepResult(status=StepStatus.COMPLETED, output=f"done-{self._current}")
        return AgentStepResult(status=StepStatus.CONTINUE, output=f"step-{self._current}")


class FailingAgent:
    async def step(self, context: AgentContext) -> AgentStepResult:
        raise RuntimeError("intentional failure")


class WaitingAgent:
    def __init__(self):
        self._waiting = True

    async def step(self, context: AgentContext) -> AgentStepResult:
        if self._waiting:
            self._waiting = False
            return AgentStepResult(status=StepStatus.WAIT, wait_reason=WaitReason.IPC)
        return AgentStepResult(status=StepStatus.COMPLETED, output="resumed")


class InfiniteAgent:
    async def step(self, context: AgentContext) -> AgentStepResult:
        return AgentStepResult(status=StepStatus.CONTINUE, output="running")


# --- Fixtures ---

@pytest.fixture
def kernel():
    """Set up full kernel components."""
    reset_settings()
    settings = Settings()
    event_manager = EventManager()
    process_table = ProcessTable()
    process_manager = ProcessManager(process_table, event_manager, settings)
    resource_manager = ResourceManager(settings)
    context_manager = ContextManager(event_manager=event_manager, settings=settings)
    scheduler = PriorityScheduler(settings=settings)
    executor = RuntimeExecutor(
        process_manager, resource_manager, context_manager, event_manager, settings
    )
    restart_manager = RestartManager(settings.supervisor)
    supervisor = Supervisor(process_manager, restart_manager, event_manager)
    ipc_manager = IPCManager(settings, event_manager)
    return {
        "settings": settings,
        "events": event_manager,
        "table": process_table,
        "pm": process_manager,
        "rm": resource_manager,
        "cm": context_manager,
        "scheduler": scheduler,
        "executor": executor,
        "restart": restart_manager,
        "supervisor": supervisor,
        "ipc": ipc_manager,
    }


# --- Test 1: Concurrent execution ---

@pytest.mark.asyncio
async def test_1_concurrent_execution(kernel):
    pm = kernel["pm"]
    scheduler = kernel["scheduler"]
    executor = kernel["executor"]

    # Create 3 processes
    p1 = await pm.spawn(SimpleAgent(steps=2), name="A")
    p2 = await pm.spawn(SimpleAgent(steps=2), name="B")
    p3 = await pm.spawn(SimpleAgent(steps=2), name="C")

    # All should be READY
    assert p1.state == ProcessState.READY
    assert p2.state == ProcessState.READY
    assert p3.state == ProcessState.READY

    # Execute steps until all complete
    for _ in range(20):
        ready = await kernel["table"].get_runnable()
        if not ready:
            break
        selected = scheduler.select_next(ready)
        if selected:
            await executor.execute_step(selected)

    # All should be COMPLETED
    assert p1.state == ProcessState.COMPLETED
    assert p2.state == ProcessState.COMPLETED
    assert p3.state == ProcessState.COMPLETED


# --- Test 2: Priority scheduling ---

@pytest.mark.asyncio
async def test_2_priority_scheduling(kernel):
    pm = kernel["pm"]
    scheduler = kernel["scheduler"]

    p_low = await pm.spawn(SimpleAgent(1), name="Low", priority=2)
    p_high = await pm.spawn(SimpleAgent(1), name="High", priority=9)

    ready = await kernel["table"].get_runnable()
    selected = scheduler.select_next(ready)

    # Higher priority should be selected first
    assert selected.process_id == p_high.process_id


# --- Test 3: Starvation prevention ---

@pytest.mark.asyncio
async def test_3_starvation_prevention(kernel):
    pm = kernel["pm"]
    scheduler = kernel["scheduler"]

    p_high = await pm.spawn(SimpleAgent(1), name="High", priority=9)
    p_low = await pm.spawn(SimpleAgent(1), name="Low", priority=2)

    # Artificially age the low priority process
    p_low.ready_since = time.time() - 200  # 200 seconds ago, bonus = 200/5 = 40, capped at 10

    ready = await kernel["table"].get_runnable()
    selected = scheduler.select_next(ready)

    # Low priority (2 + 10 aging = 12) should beat high priority (9 + 0 aging)
    assert selected.process_id == p_low.process_id


# --- Test 4: IPC dependency ---

@pytest.mark.asyncio
async def test_4_ipc_dependency(kernel):
    pm = kernel["pm"]
    ipc = kernel["ipc"]

    p_a = await pm.spawn(WaitingAgent(), name="Waiter")
    p_b = await pm.spawn(SimpleAgent(1), name="Sender")

    # Execute A's step — should WAIT for IPC
    executor = kernel["executor"]
    result = await executor.execute_step(p_a)
    assert result.status == StepStatus.WAIT
    assert p_a.state == ProcessState.WAITING

    # B sends message to A via IPC
    msg = await ipc.send(p_b.process_id, p_a.process_id, {"data": "hello"})
    assert msg.delivery_status == "DELIVERED"

    # Resume A
    await pm.resume(p_a.process_id)
    assert p_a.state == ProcessState.READY

    # Receive message
    received = await ipc.receive(p_a.process_id)
    assert received is not None
    assert received.payload == {"data": "hello"}


# --- Test 5: Context swapping ---

@pytest.mark.asyncio
async def test_5_context_swapping(kernel):
    cm = kernel["cm"]

    ctx_id = await cm.create(process_id=1)
    page = await cm.add_page(ctx_id, process_id=1, content="important data")
    assert page.loaded is True

    # Swap out
    await cm.swap_out(ctx_id, page.index)
    # Check internal state (get_page auto-swaps-in)
    raw_pages = cm._contexts[ctx_id]
    assert raw_pages[page.index].loaded is False

    # Swap in
    await cm.swap_in(ctx_id, page.index)
    restored = await cm.get_page(ctx_id, page.index)
    assert restored.loaded is True
    assert restored.content == "important data"


# --- Test 6: Deadlock detection ---

@pytest.mark.asyncio
async def test_6_deadlock_detection(kernel):
    detector = DeadlockDetector()

    # A waits for B, B waits for A
    detector.add_dependency(1, 2)
    detector.add_dependency(2, 1)

    cycle = detector.detect_cycle()
    assert cycle is not None
    assert set(cycle) == {1, 2}

    # Select victim (lowest priority)
    victim = detector.select_victim(cycle, {1: 5, 2: 3})
    assert victim == 2  # lowest priority


# --- Test 7: Failure recovery ---

@pytest.mark.asyncio
async def test_7_failure_recovery(kernel):
    pm = kernel["pm"]
    supervisor = kernel["supervisor"]
    executor = kernel["executor"]

    p = await pm.spawn(FailingAgent(), name="Failer", restart_policy="N_TIMES")

    # Execute step — should fail
    result = await executor.execute_step(p)
    assert result.status == StepStatus.FAILED
    assert p.state == ProcessState.FAILED

    # Supervisor handles failure — should restart
    await supervisor.handle_failure(p.process_id, FailureType.AGENT_EXCEPTION, "test error")

    # After restart, should be READY again
    assert p.state == ProcessState.READY
    assert p.restart_count == 1


# --- Test 8: Resource exhaustion ---

@pytest.mark.asyncio
async def test_8_resource_exhaustion(kernel):
    pm = kernel["pm"]
    rm = kernel["rm"]
    executor = kernel["executor"]

    limits = ResourceLimits(step_limit=2, token_limit=99999, llm_call_limit=99,
                            tool_call_limit=99, wall_time_limit=999, child_process_limit=10)
    p = await pm.spawn(InfiniteAgent(), name="Limited", resource_limits=limits)

    # Execute 2 steps (at limit)
    await executor.execute_step(p)
    assert p.state == ProcessState.READY  # step 1 consumed, CONTINUE -> READY

    await executor.execute_step(p)
    assert p.state == ProcessState.READY  # step 2 consumed

    # 3rd step should fail — resource limit exceeded
    result = await executor.execute_step(p)
    assert p.state == ProcessState.FAILED


# --- Test 9: Cancellation ---

@pytest.mark.asyncio
async def test_9_cancellation(kernel):
    pm = kernel["pm"]

    p = await pm.spawn(InfiniteAgent(), name="Cancelled")
    assert p.state == ProcessState.READY

    await pm.cancel(p.process_id)
    assert p.state == ProcessState.CANCELLED


# --- Test 10: Full lifecycle ---

@pytest.mark.asyncio
async def test_10_full_lifecycle(kernel):
    pm = kernel["pm"]
    executor = kernel["executor"]

    p = await pm.spawn(SimpleAgent(steps=1), name="Lifecycle")

    # CREATED -> READY (done by spawn)
    assert p.state == ProcessState.READY

    # READY -> RUNNING -> COMPLETED (done by execute_step)
    result = await executor.execute_step(p)
    assert result.status == StepStatus.COMPLETED
    assert p.state == ProcessState.COMPLETED

    # COMPLETED -> TERMINATED
    await pm.terminate(p.process_id)
    assert p.state == ProcessState.TERMINATED
