"""Agent-OS Generic Demonstration (§89)

Demonstrates all core Agent-OS functionality using generic processes.
No external LLM required - uses Mock LLM provider.
"""
import asyncio
import sys
import os
import time

# Allow direct execution from project root
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
for _p in [os.path.join(_project_root, 'src'), os.path.join(_project_root, 'sdk'), _project_root]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agent_os.config.settings import Settings, reset_settings
from agent_os.metrics.events import EventManager
from agent_os.kernel.process_table import ProcessTable
from agent_os.kernel.process_manager import ProcessManager
from agent_os.kernel.state_machine import ProcessState, StepStatus, AgentStepResult, WaitReason
from agent_os.resources.manager import ResourceManager
from agent_os.resources.quota import ResourceLimits
from agent_os.scheduler.priority import PriorityScheduler
from agent_os.scheduler.weighted_fair import WeightedFairScheduler
from agent_os.runtime.executor import RuntimeExecutor
from agent_os.ipc.ipc_manager import IPCManager
from agent_os.memory.context_manager import ContextManager
from agent_os.memory.checkpoint import CheckpointManager
from agent_os.supervisor.supervisor import Supervisor
from agent_os.supervisor.failure import FailureType
from agent_os.supervisor.restart import RestartManager
from agent_os.synchronization.deadlock import DeadlockDetector
from agent_os.llm.mock import MockLLMProvider
from agent_os.llm.base import LLMRequest
from sdk.agent import AgentContext


# ── Generic Agents ──


class GenericAgentA:
    """Does 3 steps. Uses mock LLM on step 2, sends IPC on step 3."""
    def __init__(self, ipc: IPCManager, target_pid: int | None = None):
        self._step = 0
        self._ipc = ipc
        self._target_pid = target_pid
        self._pid: int | None = None

    async def step(self, context: AgentContext) -> AgentStepResult:
        self._step += 1
        self._pid = context.process_id
        if self._step == 1:
            return AgentStepResult(status=StepStatus.CONTINUE, output="A: Step 1 — initialization")
        elif self._step == 2:
            return AgentStepResult(status=StepStatus.CONTINUE, output="A: Step 2 — processing")
        elif self._step == 3:
            if self._target_pid and self._pid:
                await self._ipc.send(self._pid, self._target_pid, {"msg": "Wake up!"})
            return AgentStepResult(status=StepStatus.COMPLETED, output="A: Step 3 — completed, IPC sent")
        return AgentStepResult(status=StepStatus.COMPLETED)


class GenericAgentB:
    """Waits for IPC on step 1, does 2 more steps after receiving."""
    def __init__(self):
        self._step = 0
        self._waiting = True

    async def step(self, context: AgentContext) -> AgentStepResult:
        if self._waiting:
            self._waiting = False
            return AgentStepResult(status=StepStatus.WAIT, wait_reason=WaitReason.IPC, output="B: Waiting for IPC")
        self._step += 1
        if self._step == 1:
            return AgentStepResult(status=StepStatus.CONTINUE, output="B: Processing IPC data")
        return AgentStepResult(status=StepStatus.COMPLETED, output="B: Finished")


class GenericAgentC:
    """Does 2 steps then fails intentionally (for restart demo)."""
    def __init__(self):
        self._step = 0

    async def step(self, context: AgentContext) -> AgentStepResult:
        self._step += 1
        if self._step == 2:
            raise RuntimeError("Intentional failure for restart demo")
        return AgentStepResult(status=StepStatus.CONTINUE, output=f"C: Step {self._step}")


# ── Main Demo ──


def section(title: str) -> None:
    print(f"\n{'-' * 50}")
    print(f"  {title}")
    print(f"{'-' * 50}")


async def main():
    print("=" * 50)
    print("      Agent-OS Generic Demonstration              ")
    print("=" * 50)

    # ── 1. Boot kernel ──
    section("1. Booting Kernel")
    reset_settings()
    settings = Settings()
    event_manager = EventManager()
    process_table = ProcessTable()
    process_manager = ProcessManager(process_table, event_manager, settings)
    resource_manager = ResourceManager(settings)
    scheduler = PriorityScheduler(settings=settings)
    ipc = IPCManager(settings, event_manager)
    context_manager = ContextManager(settings, event_manager)
    checkpoint_manager = CheckpointManager(event_manager)
    restart_manager = RestartManager(settings.supervisor)
    supervisor = Supervisor(process_manager, restart_manager, event_manager, checkpoint_manager)
    executor = RuntimeExecutor(process_manager, resource_manager, context_manager, event_manager, settings)
    print("[OK] All kernel components initialized")

    # ── 2. Create agents with automatic PID assignment ──
    section("2. Creating Agents (automatic PID assignment)")
    agent_b = GenericAgentB()
    proc_b = await process_manager.spawn(agent_b, name="AgentB", priority=5)
    agent_a = GenericAgentA(ipc, target_pid=proc_b.process_id)
    proc_a = await process_manager.spawn(agent_a, name="AgentA", priority=9)
    agent_c = GenericAgentC()
    proc_c = await process_manager.spawn(agent_c, name="AgentC", priority=3, restart_policy="ONCE")
    print(f"  AgentA → PID {proc_a.process_id} (priority={proc_a.priority})")
    print(f"  AgentB → PID {proc_b.process_id} (priority={proc_b.priority})")
    print(f"  AgentC → PID {proc_c.process_id} (priority={proc_c.priority})")

    # ── 3. Show process table ──
    section("3. Process Table")
    for p in await process_manager.list():
        print(f"  PID={p.process_id}  Name={p.name:<10} State={p.state.value:<12} Priority={p.priority}")

    # ── 4. Priority scheduling demonstration ──
    section("4. Priority Scheduling")
    ready = await process_table.get_runnable()
    selected = scheduler.select_next(ready)
    print(f"  Runnable PIDs: {[p.process_id for p in ready]}")
    print(f"  Selected (highest priority): PID {selected.process_id} ({selected.name})")

    # ── 5. Execute steps with scheduler ──
    section("5. Executing Steps via Scheduler + Executor")
    for tick in range(1, 8):
        ready = await process_table.get_runnable()
        if not ready:
            print(f"  Tick {tick}: No runnable processes")
            break
        selected = scheduler.select_next(ready)
        if selected:
            result = await executor.execute_step(selected)
            print(f"  Tick {tick}: PID {selected.process_id} ({selected.name}) → "
                  f"status={result.status.value}, output={result.output or result.error}")

            # If AgentB is WAITING, send IPC and resume
            if selected.process_id == proc_b.process_id and result.status == StepStatus.WAIT:
                print(f"    → AgentB is WAITING for IPC. Will resume after AgentA sends message.")

            # If AgentC failed, handle via supervisor
            if result.status == StepStatus.FAILED and selected.process_id == proc_c.process_id:
                print(f"    → AgentC FAILED. Supervisor handling failure...")
                await supervisor.handle_failure(
                    proc_c.process_id, FailureType.AGENT_EXCEPTION, result.error or "unknown"
                )
                print(f"    → AgentC state after supervisor: {proc_c.state.value}")
        await asyncio.sleep(0)

    # ── 6. IPC demonstration ──
    section("6. IPC — Wake AgentB")
    if proc_b.state == ProcessState.WAITING:
        msg = await ipc.send(proc_a.process_id, proc_b.process_id, {"msg": "Wake up!"})
        print(f"  Sent message: {msg.message_id[:8]}... from PID {proc_a.process_id} → PID {proc_b.process_id}")
        print(f"  Delivery status: {msg.delivery_status}")
        received = await ipc.receive(proc_b.process_id)
        if received:
            print(f"  Received by AgentB: {received.payload}")
        await process_manager.resume(proc_b.process_id)
        print(f"  AgentB state: {proc_b.state.value}")

    # ── 7. Context management ──
    section("7. Context Management — Pages & Swapping")
    ctx_id = await context_manager.create(process_id=proc_a.process_id)
    page = await context_manager.add_page(ctx_id, process_id=proc_a.process_id, content="Agent A conversation history")
    print(f"  Created context: {ctx_id[:8]}...")
    print(f"  Added page: index={page.index}, loaded={page.loaded}")
    await context_manager.swap_out(ctx_id, page.index)
    print(f"  Swapped out page {page.index}")
    await context_manager.swap_in(ctx_id, page.index)
    restored = await context_manager.get_page(ctx_id, page.index)
    print(f"  Swapped in page {page.index}: content='{restored.content[:30]}...'")

    # ── 8. Checkpoint ──
    section("8. Checkpoint")
    cp = await checkpoint_manager.create(
        process_id=proc_a.process_id,
        process_state=proc_a.state,
        context_id=ctx_id,
        context_version=1,
        resource_usage={"steps": proc_a.resource_usage.steps},
        agent_state={"step_count": agent_a._step},
    )
    print(f"  Created checkpoint: {cp.checkpoint_id[:8]}... for PID {cp.process_id}")
    restored_cp = await checkpoint_manager.restore(cp.checkpoint_id)
    print(f"  Restored checkpoint: agent_state={restored_cp.agent_state}")

    # ── 9. Aging / starvation prevention ──
    section("9. Aging / Starvation Prevention")
    proc_low = await process_manager.spawn(GenericAgentC(), name="LowPrio", priority=1)
    proc_high = await process_manager.spawn(GenericAgentC(), name="HighPrio", priority=9)
    proc_low.ready_since = time.time() - 200  # aged 200s
    ready = await process_table.get_runnable()
    selected = scheduler.select_next(ready)
    print(f"  LowPrio (prio=1, aged 200s) vs HighPrio (prio=9, fresh)")
    print(f"  Aging bonus for LowPrio: 1 + 10 (capped) = 11")
    print(f"  Selected: PID {selected.process_id} ({selected.name})")

    # ── 10. Deadlock detection ──
    section("10. Deadlock Detection")
    dd = DeadlockDetector()
    dd.add_dependency(proc_a.process_id, proc_b.process_id)
    dd.add_dependency(proc_b.process_id, proc_a.process_id)
    cycle = dd.detect_cycle()
    print(f"  Added: PID {proc_a.process_id} waits for PID {proc_b.process_id}")
    print(f"  Added: PID {proc_b.process_id} waits for PID {proc_a.process_id}")
    print(f"  Cycle detected: {cycle}")
    if cycle:
        victim = dd.select_victim(cycle, {proc_a.process_id: proc_a.priority, proc_b.process_id: proc_b.priority})
        print(f"  Victim (lowest priority): PID {victim}")

    # ── 11. Mock LLM ──
    section("11. Mock LLM Provider")
    llm = MockLLMProvider()
    resp = await llm.generate(LLMRequest(prompt="What is Agent-OS?"))
    print(f"  Prompt: 'What is Agent-OS?'")
    print(f"  Response: '{resp.content[:60]}...'")
    print(f"  Tokens: input={resp.input_tokens}, output={resp.output_tokens}")

    # ── 12. Resource accounting ──
    section("12. Resource Accounting")
    print(f"  AgentA usage: steps={proc_a.resource_usage.steps}, tokens={proc_a.resource_usage.total_tokens}")
    print(f"  AgentA limits: step_limit={proc_a.resource_limits.step_limit}, token_limit={proc_a.resource_limits.token_limit}")
    can_exec = resource_manager.can_execute(proc_a)
    print(f"  AgentA can_execute: {can_exec}")

    # ── 13. Final process states ──
    section("13. Final Process States")
    for p in await process_manager.list():
        print(f"  PID={p.process_id}  Name={p.name:<12} State={p.state.value:<14} "
              f"Steps={p.resource_usage.steps}  Restarts={p.restart_count}")

    # ── 14. Event history ──
    section("14. Event History (last 10)")
    history = await event_manager.get_history(limit=10)
    for evt in history:
        print(f"  [{evt.event_type.value}] PID={evt.process_id} {evt.metadata}")

    print("\n" + "=" * 50)
    print("          Demo Complete — All Systems GO          ")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
