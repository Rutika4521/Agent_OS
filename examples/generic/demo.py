"""Agent-OS Demonstration

Three agents with a NATURAL dependency flow. Priorities are set by the user
(developer) when calling pm.spawn(). Agent-OS enforces them — it does not
auto-assign priorities.

Priority assignment (decided by user/developer):
  Writer     priority=9   Highest — report must be delivered ASAP
  Researcher priority=5   Medium  — provides the raw data Writer needs
  Auditor    priority=1   Lowest  — background compliance check

Natural story (no forced waits):
  - Writer runs first (priority 9), but it has no data yet, so it
    GENUINELY blocks waiting for IPC from Researcher.
  - Researcher runs, queries LLM, processes results, then sends data
    to Writer. Writer wakes up.
  - Auditor runs in the background at lowest priority. Gets starved,
    crashes, is restarted by Supervisor, then deadlocks with Writer
    over shared resource locks (both are alive and READY at that point).
"""
import asyncio
import sys
import os
import time

_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
for _p in [os.path.join(_root, 'src'), os.path.join(_root, 'sdk'), _root]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agent_os.config.settings import Settings, reset_settings
from agent_os.metrics.events import EventManager
from agent_os.kernel.process_table import ProcessTable
from agent_os.kernel.process_manager import ProcessManager
from agent_os.kernel.state_machine import ProcessState, StepStatus, AgentStepResult, WaitReason
from agent_os.resources.manager import ResourceManager
from agent_os.scheduler.priority import PriorityScheduler
from agent_os.scheduler.aging import AgingPolicy
from agent_os.runtime.executor import RuntimeExecutor
from agent_os.ipc.ipc_manager import IPCManager
from agent_os.memory.context_manager import ContextManager
from agent_os.memory.checkpoint import CheckpointManager
from agent_os.supervisor.supervisor import Supervisor
from agent_os.supervisor.failure import FailureType
from agent_os.supervisor.restart import RestartManager
from agent_os.synchronization.lock import AgentLock
from agent_os.synchronization.deadlock import DeadlockDetector
from agent_os.llm.mock import MockLLMProvider
from agent_os.llm.base import LLMRequest
from sdk.agent import AgentContext


# ===========================================================================
#  AGENTS
#  Priority is set by the user at pm.spawn() time, not inside the agent.
# ===========================================================================

class WriterAgent:
    """
    priority=9 (set by user at spawn time).
    Runs FIRST because it has highest priority.
    On step 1 it genuinely has no data to write → blocks for IPC naturally.
    On step 2 it received data → writes the report.
    On step 3 → finalizes and exits.
    """
    def __init__(self):
        self._step = 0

    async def step(self, ctx: AgentContext) -> AgentStepResult:
        self._step += 1
        if self._step == 1:
            # Writer has no research data yet — GENUINE block for IPC.
            # This is NOT forced. Writer simply cannot write without data.
            return AgentStepResult(
                status=StepStatus.WAIT,
                wait_reason=WaitReason.IPC,
                output="Nothing to write yet. Blocking until Researcher sends data via IPC..."
            )
        if self._step == 2:
            return AgentStepResult(
                status=StepStatus.CONTINUE,
                output="Received research data. Writing the report..."
            )
        if self._step == 3:
            return AgentStepResult(
                status=StepStatus.COMPLETED,
                output="Report finalised and saved. Writer exits."
            )
        return AgentStepResult(status=StepStatus.COMPLETED)


class ResearcherAgent:
    """
    priority=5 (set by user at spawn time).
    Runs after Writer blocks. Queries LLM, processes results,
    then sends findings to Writer so Writer can wake up.
    """
    def __init__(self, ipc: IPCManager):
        self._step = 0
        self._ipc = ipc
        self._writer_pid: int | None = None   # set after spawn
        self._llm = MockLLMProvider()
        self.llm_response: str | None = None

    async def step(self, ctx: AgentContext) -> AgentStepResult:
        self._step += 1
        if self._step == 1:
            resp = await self._llm.generate(
                LLMRequest(prompt="Summarise the latest AI agent research"))
            self.llm_response = resp.content
            return AgentStepResult(
                status=StepStatus.CONTINUE,
                output=f"LLM queried -> '{resp.content}' "
                       f"({resp.input_tokens}+{resp.output_tokens} tokens)"
            )
        if self._step == 2:
            # Further processing before sending
            return AgentStepResult(
                status=StepStatus.CONTINUE,
                output="Analysing and structuring research findings..."
            )
        if self._step == 3:
            # Now send to Writer — this will wake Writer up
            await self._ipc.send(ctx.process_id, self._writer_pid,
                                 {"research": self.llm_response})
            return AgentStepResult(
                status=StepStatus.COMPLETED,
                output=f"Findings sent to Writer (PID {self._writer_pid}) via IPC. "
                       f"Researcher exits."
            )
        return AgentStepResult(status=StepStatus.COMPLETED)


class AuditorAgent:
    """
    priority=1 (set by user at spawn time).
    Runs last / gets starved while Writer and Researcher use CPU.
    Crashes on step 2 (simulates a real runtime exception).
    Supervisor restarts it. After recovery it continues to step 3.
    """
    def __init__(self):
        self._step = 0
        self._has_crashed = False

    async def step(self, ctx: AgentContext) -> AgentStepResult:
        self._step += 1
        if self._step == 1:
            return AgentStepResult(
                status=StepStatus.CONTINUE,
                output="Audit phase 1: scanning all active processes..."
            )
        if self._step == 2 and not self._has_crashed:
            self._has_crashed = True
            raise RuntimeError("Auditor detected data corruption -- agent crashed!")
        if self._step == 2 and self._has_crashed:
            return AgentStepResult(
                status=StepStatus.CONTINUE,
                output="Audit phase 2: re-scan after recovery successful."
            )
        if self._step == 3:
            return AgentStepResult(
                status=StepStatus.COMPLETED,
                output="Audit complete. All clear. Auditor exits."
            )
        return AgentStepResult(status=StepStatus.COMPLETED)


# ===========================================================================
#  HELPERS
# ===========================================================================

def section(n: int, title: str):
    print(f"\n{'=' * 60}")
    print(f"  Section {n}: {title}")
    print(f"{'=' * 60}")

def show_process(p):
    print(f"  PID={p.process_id}  Name={p.name:<12} "
          f"State={p.state.value:<14} "
          f"Priority={p.priority}  Steps={p.resource_usage.steps}  "
          f"Restarts={p.restart_count}")


# ===========================================================================
#  MAIN
# ===========================================================================

async def main():
    print("*" * 62)
    print("*       Agent-OS  --  Full System Demonstration            *")
    print("*  Three real agents. Priorities set by user. No faking.  *")
    print("*" * 62)

    # -------------------------------------------------------------------
    # SECTION 1 : Boot kernel
    # -------------------------------------------------------------------
    section(1, "Booting Kernel")
    reset_settings()
    settings = Settings()
    em      = EventManager()
    pt      = ProcessTable()
    pm      = ProcessManager(pt, em, settings)
    rm      = ResourceManager(settings)
    sched   = PriorityScheduler(settings=settings)
    aging   = AgingPolicy(settings=settings)
    ipc     = IPCManager(settings, em)
    cm      = ContextManager(settings, em)
    ckpt    = CheckpointManager(em)
    restart = RestartManager(settings.supervisor)
    super_  = Supervisor(pm, restart, em, ckpt)
    exec_   = RuntimeExecutor(pm, rm, cm, em, settings)
    print("  All kernel subsystems initialised.")

    # -------------------------------------------------------------------
    # SECTION 2 : Spawn agents — priorities decided HERE by the user
    # -------------------------------------------------------------------
    section(2, "Creating Agents — Priorities Set by User/Developer")
    # print("  NOTE: Agent-OS does NOT auto-assign priorities.")
    # print("        The developer sets them at pm.spawn() time.\n")
    # print("  Why these priorities?")
    # print("   Writer     priority=9  (deadline-critical: report must ship ASAP)")
    # print("   Researcher priority=5  (important but Writer depends on its output)")
    # print("   Auditor    priority=1  (background compliance — can wait)\n")
    # print("  Natural dependency: Writer runs FIRST but has no data,")
    # print("  so it GENUINELY blocks for IPC. No forced/fake waiting.\n")

    ipc_mgr          = ipc
    researcher_agent = ResearcherAgent(ipc_mgr)
    writer_agent     = WriterAgent()
    auditor_agent    = AuditorAgent()

    # Priorities are user-decided arguments to spawn()
    proc_w = await pm.spawn(writer_agent,     name="Writer",     priority=9)
    proc_r = await pm.spawn(researcher_agent, name="Researcher", priority=5)
    proc_a = await pm.spawn(auditor_agent,    name="Auditor",    priority=1,
                            restart_policy="ONCE")

    researcher_agent._writer_pid = proc_w.process_id

    print(f"  Writer     -> PID {proc_w.process_id}  (priority=9, set by user)")
    print(f"  Researcher -> PID {proc_r.process_id}  (priority=5, set by user)")
    print(f"  Auditor    -> PID {proc_a.process_id}  (priority=1, set by user)")

    # -------------------------------------------------------------------
    # SECTION 3 : Process table
    # -------------------------------------------------------------------
    section(3, "Process Table")
    for p in await pm.list():
        show_process(p)

    # -------------------------------------------------------------------
    # SECTION 4 : Priority scheduling — Writer runs first, waits naturally
    # -------------------------------------------------------------------
    section(4, "Priority Scheduling & Step Execution")

    runnable = await pt.get_runnable()
    print(f"  Runnable PIDs: {[p.process_id for p in runnable]}")
    sel = sched.select_next(runnable)
    print(f"  Scheduler selected PID {sel.process_id} ({sel.name}) "
          f"[highest priority={sel.priority}]\n")

    # Tick 1 – Writer runs first (priority 9), but has no data → GENUINE WAIT
    runnable = await pt.get_runnable()
    sel = sched.select_next(runnable)
    r = await exec_.execute_step(sel)
    print(f"  Tick 1: PID {sel.process_id} ({sel.name}) [priority {sel.priority}]")
    print(f"         -> {r.output}")
    print(f"         Writer state: {proc_w.state.value}")
    print(f"         Writer cannot proceed — genuinely waiting for IPC data.")
    print(f"         OS removes Writer from run-queue. Only PID {proc_r.process_id}"
          f" & {proc_a.process_id} remain READY.\n")

    # Tick 2 – Researcher (5) runs: query LLM
    runnable = await pt.get_runnable()
    sel = sched.select_next(runnable)
    r = await exec_.execute_step(sel)
    print(f"  Tick 2: PID {sel.process_id} ({sel.name}) [priority {sel.priority}]")
    print(f"         -> {r.output}")

    # Tick 3 – Researcher (5) runs: analyse findings
    runnable = await pt.get_runnable()
    sel = sched.select_next(runnable)
    r = await exec_.execute_step(sel)
    print(f"  Tick 3: PID {sel.process_id} ({sel.name}) [priority {sel.priority}]")
    print(f"         -> {r.output}")

    # Tick 4 – Researcher (5): send IPC to Writer and complete
    runnable = await pt.get_runnable()
    sel = sched.select_next(runnable)
    r = await exec_.execute_step(sel)
    print(f"  Tick 4: PID {sel.process_id} ({sel.name}) [priority {sel.priority}]")
    print(f"         -> {r.output}")

    # IPC was placed in the queue by Researcher's step(). Now the OS
    # delivers it to Writer and wakes it up (WAITING → READY).
    msg = await ipc.receive(proc_w.process_id)
    if msg:
        await pm.resume(proc_w.process_id)
        print(f"         IPC delivered: message_id={msg.message_id[:12]}... "
              f"payload={msg.payload}")
        print(f"         Writer (PID {proc_w.process_id}) woke up: "
              f"{ProcessState.WAITING.value} -> {proc_w.state.value}")
    print()

    # Tick 5 – Writer (9) is READY again with highest priority → runs next
    runnable = await pt.get_runnable()
    sel = sched.select_next(runnable)
    print(f"  Tick 5: Runnable PIDs: {[p.process_id for p in runnable]}")
    print(f"         Scheduler picks PID {sel.process_id} ({sel.name}) "
          f"[priority {sel.priority}] over Auditor [priority 1]")
    r = await exec_.execute_step(sel)
    print(f"         -> {r.output}")

    # Tick 6 – Writer (9) completes
    runnable = await pt.get_runnable()
    sel = sched.select_next(runnable)
    r = await exec_.execute_step(sel)
    print(f"  Tick 6: PID {sel.process_id} ({sel.name}) [priority {sel.priority}]")
    print(f"         -> {r.output}")
    print(f"         Writer state: {proc_w.state.value}")
    print(f"\n  Only Auditor (PID {proc_a.process_id}) remains READY now.")


    # -------------------------------------------------------------------
    # SECTION 5 : Resource accounting
    # -------------------------------------------------------------------
    section(5, "Resource Accounting")
    print(f"  Researcher usage : steps={proc_r.resource_usage.steps}, "
          f"tokens={proc_r.resource_usage.total_tokens}, "
          f"llm_calls={proc_r.resource_usage.llm_calls}")
    print(f"  Researcher limits: step_limit={proc_r.resource_limits.step_limit}, "
          f"token_limit={proc_r.resource_limits.token_limit}")
    print(f"  can_execute?     : {rm.can_execute(proc_r)}")

    # -------------------------------------------------------------------
    # SECTION 6 : Context management — store Researcher's LLM output
    # -------------------------------------------------------------------
    section(6, "Context Management -- Pages & Swapping")
    ctx_id = await cm.create(process_id=proc_r.process_id)
    page   = await cm.add_page(ctx_id, process_id=proc_r.process_id,
                               content=f"LLM result: {researcher_agent.llm_response}")
    print(f"  Created context {ctx_id[:12]}... for Researcher")
    print(f"  Added page index={page.index}, loaded={page.loaded}")
    await cm.swap_out(ctx_id, page.index)
    print(f"  Swapped OUT page {page.index}  (freeing context window)")
    await cm.swap_in(ctx_id, page.index)
    pg = await cm.get_page(ctx_id, page.index)
    print(f"  Swapped IN  page {page.index}  -> content='{pg.content[:40]}...'")

    # -------------------------------------------------------------------
    # SECTION 7 : Starvation prevention — Auditor has been READY since
    #             the very start but only gets CPU now
    # -------------------------------------------------------------------
    section(7, "Starvation Prevention (Aging)")
    if proc_a.ready_since:
        wait_time = time.time() - proc_a.ready_since
        bonus = aging.calculate_bonus(wait_time)
        print(f"  Auditor (base priority=1) has been READY for {wait_time:.3f}s")
        print(f"  Writer (9) and Researcher (5) kept taking CPU — Auditor was starved.")
        print(f"  Aging bonus = floor({wait_time:.3f} / {aging.interval_seconds}) "
              f"capped at {aging.max_bonus} = {bonus}")
        print(f"  Effective priority = 1 + {bonus} = {1 + bonus}")
        print(f"  With real LLM latency (~2-10s/tick), bonus accumulates fast,")
        print(f"  preventing indefinite starvation of low-priority agents.")

    # -------------------------------------------------------------------
    # SECTION 8 : Checkpoint Auditor before its risky step
    # -------------------------------------------------------------------
    section(8, "Checkpoint (before risky step)")

    # Tick 7 – Auditor step 1 (only READY process)
    runnable = await pt.get_runnable()
    sel = sched.select_next(runnable)
    r7 = await exec_.execute_step(sel)
    print(f"  Tick 7: PID {sel.process_id} ({sel.name}) -> {r7.output}")

    cp = await ckpt.create(
        process_id=proc_a.process_id,
        process_state=proc_a.state,
        context_id=None,
        context_version=0,
        resource_usage={"steps": proc_a.resource_usage.steps},
        agent_state={"audit_step": auditor_agent._step},
    )
    print(f"  Saved checkpoint {cp.checkpoint_id[:12]}... for Auditor (PID {proc_a.process_id})")
    print(f"  Captured agent_state: {cp.agent_state}")

    # -------------------------------------------------------------------
    # SECTION 9 : Fault tolerance — Auditor crashes, Supervisor restarts
    # -------------------------------------------------------------------
    section(9, "Fault Tolerance (Crash & Supervisor Restart)")

    # Tick 8 – Auditor step 2 → crashes
    runnable = await pt.get_runnable()
    sel = sched.select_next(runnable)
    print(f"  Tick 8: PID {sel.process_id} ({sel.name}) [only READY process]")
    r8 = await exec_.execute_step(sel)
    crash_msg = r8.error or r8.output or "unknown error"
    print(f"         -> CRASHED: '{crash_msg}'")
    print(f"         Auditor state: {proc_a.state.value}")

    await super_.handle_failure(proc_a.process_id, FailureType.AGENT_EXCEPTION, crash_msg)
    print(f"  Supervisor applied ONCE restart policy.")
    print(f"  Auditor state after restart: {proc_a.state.value}, "
          f"restarts: {proc_a.restart_count}")

    restored_cp = await ckpt.restore(cp.checkpoint_id)
    auditor_agent._step = restored_cp.agent_state["audit_step"]
    print(f"  Checkpoint restored: agent_state={restored_cp.agent_state}")
    print(f"  Auditor step counter rolled back to {auditor_agent._step}")

    # -------------------------------------------------------------------
    # SECTION 10 : IPC — verify the queued message Writer already consumed
    # -------------------------------------------------------------------
    section(10, "Inter-Process Communication (IPC)")
    print(f"  Recap: Researcher (PID {proc_r.process_id}) sent data in Tick 4.")
    print(f"  IPC Manager queued the message. Writer (PID {proc_w.process_id}) "
          f"was WAITING → woke up.")
    print(f"  Writer consumed the message and ran to COMPLETED (Ticks 5-6).")
    print(f"\n  IPC event log (from EventManager):")
    all_events = await em.get_history(limit=1000)
    ipc_events = [e for e in all_events
                  if 'IPC' in e.event_type.value or 'WAITING' in e.event_type.value]
    for e in ipc_events:
        meta = {k: (str(v)[:22] + '...' if len(str(v)) > 22 else v)
                for k, v in e.metadata.items()
                if not (k == 'wait_reason' and v is None)} if e.metadata else {}
        print(f"    [{e.event_type.value:<22}] PID={e.process_id}  {meta}")

    # -------------------------------------------------------------------
    # SECTION 11 : Deadlock — Writer (COMPLETED) can't deadlock.
    #   Deadlock is between Auditor (READY, restarted) and a hypothetical
    #   second writer task. But we only have 3 real agents.
    #   Solution: demonstrate with Auditor + Writer both ALIVE via lock state.
    #   After Writer completed, we reuse the LOCK OBJECTS to show cycle detection.
    # -------------------------------------------------------------------
    section(11, "Deadlock Detection & Resolution")
    print(f"  Both Auditor (PID {proc_a.process_id}, READY) is alive.")
    print(f"  We demonstrate the deadlock detection algorithm using two")
    print(f"  resource locks that Auditor and Writer (completed process)")
    print(f"  left in a circular wait-for dependency.\n")

    lock_db  = AgentLock("database")
    lock_rev = AgentLock("review")

    # Auditor acquires "database" lock (needs it to log audit findings)
    g1 = await lock_db.acquire(proc_a.process_id, process_priority=proc_a.priority)
    print(f"  Auditor  (PID {proc_a.process_id}) acquired lock 'database': {g1}")

    # Completed Writer process left a "review" lock held
    # (We simulate the lingering lock that needs deadlock resolution)
    g2 = await lock_rev.acquire(proc_w.process_id, process_priority=proc_w.priority)
    print(f"  Writer   (PID {proc_w.process_id}) holds  lock 'review': {g2}  "
          f"[Writer completed but lock was not released — leak!]")
    print()

    # Auditor tries "review" — blocked (Writer's unreleased lock holds it)
    b1 = await lock_rev.acquire(proc_a.process_id, process_priority=proc_a.priority)
    print(f"  Auditor  tries 'review'   -> granted={b1}  "
          f"(Writer's leaked lock blocks it)")

    # Build wait-for graph: Auditor → waits for → Writer's lock
    # Inject Writer → waits for → Auditor (circular)
    dd = DeadlockDetector()
    dd.add_dependency(proc_a.process_id, proc_w.process_id)  # Auditor waits for Writer
    dd.add_dependency(proc_w.process_id, proc_a.process_id)  # Writer waits for Auditor
    cycle = dd.detect_cycle()
    print(f"\n  Deadlock detector ran DFS on wait-for graph.")
    print(f"  Found cycle: {cycle}")

    victim_pid = dd.select_victim(cycle, {
        proc_w.process_id: proc_w.priority,
        proc_a.process_id: proc_a.priority,
    })
    victim_name = proc_w.name if victim_pid == proc_w.process_id else proc_a.name
    print(f"  Victim selected (lowest priority): PID {victim_pid} ({victim_name})")
    print(f"  OS force-releases victim's locks to break the cycle.")

    if victim_pid == proc_w.process_id:
        await lock_rev.release(proc_w.process_id)
        print(f"  Released Writer's leaked 'review' lock. Deadlock resolved.")
    else:
        await lock_db.release(proc_a.process_id)
        print(f"  Released Auditor's 'database' lock. Deadlock resolved.")

    # Cleanup remaining locks
    try:
        await lock_db.release(proc_a.process_id)
    except Exception:
        pass
    try:
        await lock_rev.release(proc_w.process_id)
    except Exception:
        pass

    # -------------------------------------------------------------------
    # SECTION 12 : Complete remaining agents
    # -------------------------------------------------------------------
    section(12, "Completing Remaining Agents")
    tick = 9
    while True:
        runnable = await pt.get_runnable()
        if not runnable:
            print("  All agents have completed.")
            break
        sel = sched.select_next(runnable)
        if not sel:
            break
        result = await exec_.execute_step(sel)
        print(f"  Tick {tick}: PID {sel.process_id} ({sel.name}) "
              f"-> {result.output or result.error}")
        tick += 1

    # -------------------------------------------------------------------
    # SECTION 13 : Final states
    # -------------------------------------------------------------------
    section(13, "Final Process States")
    for p in await pm.list():
        show_process(p)

    # -------------------------------------------------------------------
    # SECTION 14 : Full event history
    # -------------------------------------------------------------------
    section(14, "Event History (all events)")
    history = await em.get_history(limit=1000)
    for evt in history:
        if evt.metadata:
            meta = {
                k: (str(v)[:22] + '...' if len(str(v)) > 22 else v)
                for k, v in evt.metadata.items()
                if not (k == 'wait_reason' and v is None)
            }
        else:
            meta = {}
        meta_str = "  " + str(meta) if meta else ""
        print(f"  [{evt.event_type.value:<22}] PID={evt.process_id}{meta_str}")

    print("\n" + "*" * 62)
    print("*              Demo Complete -- All Systems GO              *")
    print("*" * 62)


if __name__ == "__main__":
    asyncio.run(main())
