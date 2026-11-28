"""
Agent-OS SDK — Kernel

High-level bootstrap helper that wires together all OS subsystems
and runs registered agents to completion.

Usage:
    import agent_os

    @agent_os.register(priority=7, name="MyAgent")
    class MyAgent:
        async def run(self) -> str:
            return "done"

    async def main():
        kernel = agent_os.Kernel()
        await kernel.boot()
        await kernel.spawn_registered()
        await kernel.run()

    asyncio.run(main())

What run() does each scheduling quantum
---------------------------------------
1. Housekeeping: wake sleepers whose deadline passed, IPC waiters that got
   mail (or hit `ipc_wait_timeout`), and BLOCKED processes whose lock or
   semaphore was handed to them.
2. Priority inheritance: a lock owner inherits the highest waiter priority
   and is restored once it holds no locks.
3. Deadlock detection: a wait-for graph is rebuilt from the live lock and
   semaphore state; a cycle aborts the lowest-priority member, which then
   goes through the Supervisor like any other failure.
4. Scheduling: the configured scheduler (priority + aging, or
   weighted_fair) picks ONE READY process.
5. Execution: quota pre-check (ResourceManager.can_execute), then the step
   runs under a per-process step timeout. Exceptions are classified into
   FailureTypes and handed to the Supervisor (restart policy, checkpoint
   resume via `agent.on_restart(state)`, exponential backoff).
6. Cleanup on exit/failure/cancel: locks and semaphores are reclaimed (and
   handed to the next waiter), memory contexts freed, and the orphan policy
   applied to child processes.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

from agent_os.config.settings import Settings
from agent_os.kernel.agent_process import AgentProcess
from agent_os.kernel.process_manager import ProcessManager, ProcessNotFound
from agent_os.kernel.process_table import ProcessTable
from agent_os.kernel.state_machine import (
    AgentStepResult, ProcessState, StepStatus, WaitReason,
)
from agent_os.ipc.ipc_manager import IPCManager
from agent_os.memory.context_manager import ContextManager
from agent_os.memory.checkpoint import CheckpointManager
from agent_os.metrics.events import EventManager, EventType
from agent_os.metrics.collector import MetricsCollector
from agent_os.resources.manager import ResourceLimitExceeded, ResourceManager
from agent_os.resources.quota import ResourceLimits
from agent_os.runtime.timeout import StepTimeoutError, execute_with_timeout
from agent_os.sandbox.sandbox import SandboxError
from agent_os.scheduler.priority import PriorityScheduler
from agent_os.scheduler.weighted_fair import WeightedFairScheduler
from agent_os.security.capability import CapabilityDenied, CapabilityManager
from agent_os.supervisor.failure import FailureType
from agent_os.supervisor.supervisor import Supervisor
from agent_os.supervisor.restart import RestartManager, RestartPolicy
from agent_os.synchronization.deadlock import DeadlockDetector
from agent_os.synchronization.lock import LockError
from agent_os.synchronization.sync_manager import SynchronizationManager

from sdk.agent import AgentContext
from sdk.registry import get_registry, AgentRegistration
from sdk.wrapper import AutoWrapper

logger = logging.getLogger(__name__)

LIVE = (ProcessState.READY, ProcessState.RUNNING, ProcessState.WAITING,
        ProcessState.BLOCKED, ProcessState.RESTARTING, ProcessState.CANCELLING)


class KernelNotBootedError(RuntimeError):
    """Raised when kernel methods are called before boot()."""
    pass


class Kernel:
    """
    High-level helper that bootstraps all Agent-OS subsystems.

    This is the recommended entry-point for applications using the SDK.
    It initialises all subsystems (ProcessManager, IPC, Supervisor, etc.)
    and exposes a simple interface to spawn and run agents.

    Lifecycle:
        kernel = Kernel()
        await kernel.boot()          # initialise subsystems
        await kernel.spawn_registered()  # spawn @register-decorated agents
        await kernel.run()           # drive all processes to completion
        await kernel.shutdown()      # clean up

    Advanced usage:
        proc = await kernel.spawn(MyAgent(), name="Worker", priority=8)

    Tuning (constructor keywords):
        default_step_timeout  seconds one step may run before it is failed
        ipc_wait_timeout      seconds a WAIT(IPC) may last before the process
                              is woken with ctx.data["ipc_timed_out"] = True
                              (None = wait for mail indefinitely)
        stall_timeout         seconds with nothing runnable and nothing that
                              could wake anyone before the remaining processes
                              are terminated (None = never)
        event_manager         share an existing EventManager (audit trail)
        pid_base              first PID to allocate
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        default_step_timeout: float = 30.0,
        ipc_wait_timeout: float | None = None,
        stall_timeout: float | None = 3.0,
        event_manager: EventManager | None = None,
        pid_base: int = 1,
    ):
        self._settings = settings or Settings()
        self._shared_events = event_manager   # e.g. one audit trail for several kernels
        self._pid_base = pid_base             # first PID handed out (keeps kernels' PIDs disjoint)
        self._booted = False
        self.default_step_timeout = default_step_timeout
        self.ipc_wait_timeout = ipc_wait_timeout
        self.stall_timeout = stall_timeout

        # Subsystems (set by boot())
        self._event_manager: EventManager | None = None
        self._process_table: ProcessTable | None = None
        self._process_manager: ProcessManager | None = None
        self._resource_manager: ResourceManager | None = None
        self._ipc_manager: IPCManager | None = None
        self._context_manager: ContextManager | None = None
        self._checkpoint_manager: CheckpointManager | None = None
        self._restart_manager: RestartManager | None = None
        self._supervisor: Supervisor | None = None
        self._metrics_collector: MetricsCollector | None = None
        self._sync_manager: SynchronizationManager | None = None
        self._capability_manager: CapabilityManager | None = None
        self._schedulers: dict[str, Any] = {}
        self._scheduler: Any = None
        self.scheduler_name = ""

        # Run-loop bookkeeping
        self._mailboxes: list[IPCManager] = []
        self._sleep_until: dict[int, float] = {}
        self._ipc_wait_since: dict[int, float] = {}
        self._ipc_timed_out: set[int] = set()
        self._paused: set[int] = set()
        self._step_timeouts: dict[int, float] = {}
        self._orphan_policy: dict[int, str] = {}
        self._observers: list[Callable[[str, dict], None]] = []
        self.journal: list[dict] = []     # every kernel decision, in order
        self.steps_taken = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def boot(self) -> None:
        """Initialise all OS subsystems. Must be called before spawn/run."""
        if self._booted:
            return

        s = self._settings
        self._event_manager = self._shared_events or EventManager()
        self._process_table = ProcessTable()
        self._process_table._next_pid = self._pid_base
        self._process_manager = ProcessManager(
            self._process_table, self._event_manager, s
        )
        self._resource_manager = ResourceManager(s)
        self._ipc_manager = IPCManager(s, self._event_manager)
        self._mailboxes = [self._ipc_manager]
        self._ipc_manager.set_receiver_check(self._mail_refusal)
        self._context_manager = ContextManager(s, self._event_manager)
        # ContextManager looks for a top-level `max_loaded_pages`; the real
        # setting lives under `memory`, so wire it explicitly.
        self._context_manager.max_loaded_pages = s.memory.max_loaded_pages
        self._checkpoint_manager = CheckpointManager(self._event_manager)
        self._restart_manager = RestartManager(s.supervisor)
        self._supervisor = Supervisor(
            self._process_manager,
            self._restart_manager,
            self._event_manager,
            self._checkpoint_manager,
        )
        self._metrics_collector = MetricsCollector()
        self._sync_manager = SynchronizationManager(self._event_manager)
        self._capability_manager = CapabilityManager(s.security.default_capabilities)
        self._schedulers = {
            "priority": PriorityScheduler(settings=s),
            "weighted_fair": WeightedFairScheduler(),
        }
        self.use_scheduler(s.system.default_scheduler)

        self._booted = True
        logger.info("[Kernel] Booted successfully.")

    async def shutdown(self) -> None:
        """Gracefully shut down the kernel."""
        if not self._booted:
            return
        logger.info("[Kernel] Shutting down.")
        self._booted = False

    def use_scheduler(self, kind: str) -> None:
        """Switch scheduling algorithm: "priority" (with aging) or "weighted_fair"."""
        if kind not in self._schedulers:
            raise ValueError(f"Unknown scheduler '{kind}' (expected one of {sorted(self._schedulers)})")
        self._scheduler = self._schedulers[kind]
        self.scheduler_name = kind
        self._note("scheduler", scheduler=kind)

    def attach_ipc(self, ipc: IPCManager) -> None:
        """Register an extra IPCManager whose mailboxes can wake WAIT(IPC) processes."""
        if ipc not in self._mailboxes:
            self._mailboxes.append(ipc)
            ipc.set_receiver_check(self._mail_refusal)

    async def _mail_refusal(self, pid: int) -> str | None:
        """Dead-letter guard installed on every attached IPCManager."""
        p = self._process_table._processes.get(pid) if self._process_table else None
        if p is None:
            return "no such process"
        if p.state in (ProcessState.TERMINATED, ProcessState.CANCELLED, ProcessState.COMPLETED):
            return f"receiver is {p.state.value}"
        return None

    def observe(self, fn: Callable[[str, dict], None]) -> None:
        """Call fn(kind, info) for every kernel decision (restart, deadlock, reclaim, ...)."""
        self._observers.append(fn)

    # ------------------------------------------------------------------
    # Process Spawning
    # ------------------------------------------------------------------

    async def spawn(
        self,
        agent: Any,
        *,
        name: str = "",
        priority: int | None = None,
        weight: int | None = None,
        restart_policy: str | None = None,
        resource_limits: ResourceLimits | None = None,
        capabilities: list[str] | None = None,
        parent_process_id: int | None = None,
        step_timeout: float | None = None,
        orphan_policy: str | None = None,
    ) -> AgentProcess:
        """
        Spawn a single agent as a managed process.

        The agent must implement the step(ctx) -> AgentStepResult protocol
        OR be wrapped with AutoWrapper first.

        Args:
            agent:             Agent instance (must have step() method).
            name:              Human-readable process name.
            priority:          Scheduling priority 1–10.
            weight:            Weight for weighted-fair scheduling.
            restart_policy:    "N_TIMES" | "ONCE" | "NEVER" | "EXPONENTIAL_BACKOFF"
            resource_limits:   Per-process quotas (defaults from settings).
            capabilities:      Capabilities granted to the process.
            parent_process_id: Parent PID (child limit + orphan policy apply).
            step_timeout:      Max seconds per step (default: default_step_timeout).
            orphan_policy:     "TERMINATE" (default from settings) or "KEEP".

        Returns:
            The spawned AgentProcess in READY state.
        """
        self._require_booted()
        proc = await self._process_manager.spawn(
            agent,
            name=name,
            priority=priority,
            weight=weight,
            restart_policy=restart_policy,
            resource_limits=resource_limits,
            capabilities=capabilities,
            parent_process_id=parent_process_id,
        )
        pid = proc.process_id
        self._capability_manager.initialize_process(pid, list(proc.capabilities))
        self._metrics_collector.initialize_process(pid)
        self._metrics_collector.update_process_count(len(await self._process_manager.list()))
        self._step_timeouts[pid] = step_timeout if step_timeout is not None else self.default_step_timeout
        self._orphan_policy[pid] = (orphan_policy or
                                    self._settings.process_defaults.orphan_policy).upper()
        for sched in self._schedulers.values():
            sched.add(proc)
        if parent_process_id is not None:
            try:
                (await self._process_manager.get(parent_process_id)).resource_usage.child_processes += 1
            except ProcessNotFound:
                pass
        return proc

    async def spawn_registered(self) -> list[AgentProcess]:
        """
        Spawn all agents decorated with @agent_os.register().

        Reads the global registry, instantiates each class, wraps it in
        AutoWrapper, and spawns it as a managed process.

        Returns:
            List of created AgentProcess objects in READY state.
        """
        self._require_booted()
        processes: list[AgentProcess] = []
        for reg in get_registry():
            proc = await self._spawn_from_registration(reg)
            processes.append(proc)
        return processes

    async def _spawn_from_registration(self, reg: AgentRegistration) -> AgentProcess:
        """Instantiate, wrap and spawn a single registered agent."""
        instance = reg.cls(*reg.init_args, **reg.init_kwargs)
        wrapper = AutoWrapper(
            agent=instance,
            method=reg.method,
            steps=reg.steps,
        )
        return await self.spawn(
            wrapper,
            name=reg.name,
            priority=reg.priority,
            weight=reg.weight,
            restart_policy=reg.restart_policy,
        )

    # ------------------------------------------------------------------
    # Operator controls
    # ------------------------------------------------------------------

    async def pause(self, pid: int) -> None:
        """Stop scheduling a process until resume(). Its state is kept."""
        self._require_booted()
        p = await self._process_manager.get(pid)
        if p.state in LIVE:
            self._paused.add(pid)
            if p.state == ProcessState.READY:
                await self._process_manager.pause(pid)          # READY → RUNNING → WAITING(SLEEP)
            elif p.state == ProcessState.RUNNING:
                # Wait for the currently executing step to finish and settle into WAITING
                t0 = time.monotonic()
                step_timeout = self._step_timeouts.get(pid, self.default_step_timeout)
                while p.state == ProcessState.RUNNING and pid in self._paused:
                    if time.monotonic() - t0 > step_timeout + 0.5:
                        break
                    await asyncio.sleep(0.001)
            self._note("pause", pid=pid, name=p.name, step=p.resource_usage.steps)

    async def resume(self, pid: int) -> None:
        """Make a paused process schedulable again."""
        self._require_booted()
        p = await self._process_manager.get(pid)
        if pid not in self._paused:
            return
        self._paused.discard(pid)
        sleeping = pid in self._sleep_until or pid in self._ipc_wait_since
        if p.state == ProcessState.WAITING and not sleeping:
            await self._process_manager.set_state(pid, ProcessState.READY)
        self._note("resume", pid=pid, name=p.name, step=p.resource_usage.steps)

    async def cancel(self, pid: int) -> None:
        """Cancel a process: reclaim its locks/memory and terminate it (and orphans)."""
        self._require_booted()
        p = await self._process_manager.get(pid)
        if p.state == ProcessState.TERMINATED:
            return
        await self._reclaim(p, "cancelled")
        if p.state in (ProcessState.READY, ProcessState.RUNNING, ProcessState.WAITING,
                       ProcessState.BLOCKED, ProcessState.CANCELLING):
            await self._process_manager.cancel(pid)
        await self._terminate(p, "cancelled")
        self._note("cancel", pid=pid, name=p.name, step=p.resource_usage.steps)

    # ------------------------------------------------------------------
    # Run Loop
    # ------------------------------------------------------------------

    async def run(
        self,
        *,
        max_steps: int = 10_000,
        tick_interval: float = 0.0,
        max_seconds: float | None = None,
        max_ticks: int | None = None,
    ) -> None:
        """
        Drive all processes until every one reaches a terminal state.

        Each iteration performs housekeeping, priority inheritance and
        deadlock detection, then lets the scheduler pick ONE READY process
        and executes one step of it.

        Args:
            max_steps:      Safety ceiling on the number of agent steps.
            tick_interval:  Optional sleep between steps (seconds).
            max_seconds:    Optional wall-clock ceiling; on expiry every
                            remaining process is terminated.
            max_ticks:      Alias for max_steps (backward compatibility).
        """
        self._require_booted()
        if max_ticks is not None:
            max_steps = max_ticks
        pm = self._process_manager
        started = time.time()
        idle_since: float | None = None
        steps = 0

        while steps < max_steps:
            now = time.time()
            if max_seconds is not None and now - started > max_seconds:
                self._note("timeout", seconds=max_seconds)
                for p in await pm.list():
                    if p.state in LIVE:
                        await self._terminate(p, "run timeout")
                break

            await self._housekeeping(now)
            await self._priority_inheritance()
            await self._check_deadlocks()

            ready = [p for p in await pm.list(state=ProcessState.READY) if p.process_id not in self._paused]
            if not ready:
                live = [p for p in await pm.list() if p.state in LIVE]
                if not live:
                    break
                if self._may_wake_later() or self.stall_timeout is None:
                    idle_since = None
                else:
                    idle_since = idle_since or now
                    if now - idle_since > self.stall_timeout:
                        self._note("stall", processes=[f"{p.name}:{p.state.value}" for p in live])
                        for p in live:
                            await self._terminate(p, "stalled")
                        break
                await asyncio.sleep(0.005)
                continue

            idle_since = None
            chosen = self._scheduler.select_next(ready)
            if chosen is None:
                await asyncio.sleep(0.005)
                continue
            await self._run_step(chosen)
            steps += 1
            self.steps_taken += 1
            self._metrics_collector.record_step(chosen.process_id)
            self._metrics_collector.update_ready_queue_length(len(ready) - 1)
            await asyncio.sleep(tick_interval)

        logger.info("[Kernel] Run loop complete. Steps taken: %d", steps)

    # ------------------------------------------------------------------
    # One step
    # ------------------------------------------------------------------

    async def _run_step(self, proc: AgentProcess) -> None:
        pm = self._process_manager
        pid = proc.process_id

        if not self._resource_manager.can_execute(proc):
            await self._quota_kill(proc, self._quota_breach(proc))
            return

        await pm.set_state(pid, ProcessState.RUNNING)
        ctx = AgentContext(process_id=pid)
        if pid in self._ipc_timed_out:
            self._ipc_timed_out.discard(pid)
            ctx.data["ipc_timed_out"] = True

        t0 = time.monotonic()
        try:
            result = await execute_with_timeout(
                proc.agent.step(ctx), self._step_timeouts.get(pid, self.default_step_timeout))
        except Exception as exc:  # noqa: BLE001 — every failure is classified
            proc.resource_usage.execution_time += time.monotonic() - t0
            await self._handle_exception(proc, exc)
            return
        proc.resource_usage.execution_time += time.monotonic() - t0

        try:
            self._resource_manager.consume_step(proc)
        except ResourceLimitExceeded as exc:
            await self._quota_kill(proc, f"{exc.resource_type} exceeded")
            return

        if not isinstance(result, AgentStepResult):
            result = AgentStepResult(status=StepStatus.CONTINUE, output=result)
        await self._apply(proc, result)

    async def _handle_exception(self, proc: AgentProcess, exc: Exception) -> None:
        if isinstance(exc, ResourceLimitExceeded):
            await self._quota_kill(proc, f"{exc.resource_type} exceeded mid-step "
                                         f"(tokens={proc.resource_usage.total_tokens})")
            return
        ftype, restartable = self._classify(exc)
        msg = f"LockError: {exc}" if isinstance(exc, LockError) else (
            str(exc) if isinstance(exc, (StepTimeoutError, CapabilityDenied))
            else f"{type(exc).__name__}: {exc}")
        logger.info("[Kernel] %s (pid %d) raised %s", proc.name, proc.process_id, msg)
        await self._fail(proc, ftype, msg, restartable=restartable, exc=exc)

    @staticmethod
    def _classify(exc: Exception) -> tuple[FailureType, bool]:
        """Map an exception to (FailureType, restartable).

        Exceptions may declare `failure_type` / `restartable` attributes to
        classify themselves (e.g. an application's LLM client error)."""
        declared = getattr(exc, "failure_type", None)
        restartable = getattr(exc, "restartable", None)
        if declared is not None:
            ftype = FailureType(declared)
        elif isinstance(exc, StepTimeoutError):
            ftype = FailureType.TOOL_TIMEOUT
        elif isinstance(exc, CapabilityDenied):
            ftype = FailureType.TOOL_FAILURE
            restartable = False if restartable is None else restartable   # retrying can't help
        elif isinstance(exc, SandboxError):
            ftype = FailureType.SANDBOX_FAILURE
        elif isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
            ftype = FailureType.LLM_TIMEOUT
        else:
            ftype = FailureType.AGENT_EXCEPTION
        return ftype, (True if restartable is None else bool(restartable))

    async def _apply(self, proc: AgentProcess, result: AgentStepResult) -> None:
        pm = self._process_manager
        pid, st = proc.process_id, result.status

        # Guard: process may have been cancelled/terminated by an operator hook
        # while its step was executing concurrently. Nothing to apply — bail out.
        if proc.state in (ProcessState.TERMINATED, ProcessState.CANCELLED,
                          ProcessState.COMPLETED, ProcessState.CANCELLING):
            return

        if st in (StepStatus.CONTINUE, StepStatus.YIELD):
            if pid in self._paused:
                if proc.state != ProcessState.WAITING:
                    await pm.set_state(pid, ProcessState.WAITING, wait_reason=WaitReason.SLEEP)
            else:
                await pm.set_state(pid, ProcessState.READY)

        elif st == StepStatus.WAIT:
            reason = result.wait_reason or WaitReason.IPC
            if reason == WaitReason.SLEEP:
                seconds = result.output if isinstance(result.output, (int, float)) else 0.05
                await pm.set_state(pid, ProcessState.WAITING, wait_reason=WaitReason.SLEEP)
                self._sleep_until[pid] = time.time() + float(seconds)
            elif reason == WaitReason.IPC and self._has_mail(pid):
                if pid not in self._paused:
                    await pm.set_state(pid, ProcessState.READY)
                else:
                    await pm.set_state(pid, ProcessState.WAITING, wait_reason=WaitReason.IPC)
            elif reason == WaitReason.IPC:
                await pm.set_state(pid, ProcessState.WAITING, wait_reason=WaitReason.IPC)
                self._ipc_wait_since[pid] = time.time()
            else:
                # Other wait reasons have no kernel wake source: treat as a yield.
                if pid in self._paused:
                    await pm.set_state(pid, ProcessState.WAITING, wait_reason=WaitReason.SLEEP)
                else:
                    await pm.set_state(pid, ProcessState.READY)

        elif st == StepStatus.BLOCK:
            waiting = self._waiting_on(pid)
            if waiting:
                kind = waiting[0]
                await pm.set_state(pid, ProcessState.BLOCKED,
                                   wait_reason=WaitReason.LOCK if kind == "lock" else WaitReason.RESOURCE)
            else:
                if pid in self._paused:
                    await pm.set_state(pid, ProcessState.WAITING, wait_reason=WaitReason.SLEEP)
                else:
                    await pm.set_state(pid, ProcessState.READY)   # granted already / nothing to wait on

        elif st == StepStatus.COMPLETED:
            held = self._held(pid)
            if held:
                self._note("leak", pid=pid, name=proc.name, locks=sorted(held))
                await self._reclaim(proc, "exited while holding")
            await pm.set_state(pid, ProcessState.COMPLETED)
            await pm.terminate(pid)
            self._note("completed", pid=pid, name=proc.name, steps=proc.resource_usage.steps)
            await self._after_death(proc)

        elif st == StepStatus.FAILED:
            await self._fail(proc, FailureType.AGENT_EXCEPTION, result.error or "agent returned FAILED")

    # ------------------------------------------------------------------
    # Housekeeping / wakeups
    # ------------------------------------------------------------------

    def _has_mail(self, pid: int) -> bool:
        for ipc in self._mailboxes:
            q = ipc._queues.get(pid)
            if q is not None and q.count():
                return True
        return False

    def _may_wake_later(self) -> bool:
        """Is there anything that could make a process runnable without a step?"""
        if self._sleep_until or self._paused:
            return True
        return bool(self._ipc_wait_since) and self.ipc_wait_timeout is not None

    async def _wake(self, pid: int) -> None:
        p = await self._process_manager.get(pid)
        self._sleep_until.pop(pid, None)
        self._ipc_wait_since.pop(pid, None)
        if p.state in (ProcessState.WAITING, ProcessState.BLOCKED) and pid not in self._paused:
            await self._process_manager.set_state(pid, ProcessState.READY)

    async def _housekeeping(self, now: float) -> None:
        pm = self._process_manager
        for pid, t in list(self._sleep_until.items()):
            if now >= t and pid not in self._paused:
                await self._wake(pid)
        for pid, since in list(self._ipc_wait_since.items()):
            if pid in self._paused:
                continue
            p = await pm.get(pid)
            if p.state != ProcessState.WAITING:          # woken by someone else
                self._ipc_wait_since.pop(pid, None)
            elif self._has_mail(pid):
                await self._wake(pid)
            elif self.ipc_wait_timeout is not None and now - since >= self.ipc_wait_timeout:
                self._ipc_timed_out.add(pid)
                self._note("ipc_timeout", pid=pid, name=p.name)
                await self._wake(pid)
        for p in await pm.list(state=ProcessState.BLOCKED):
            if p.process_id not in self._paused and not self._waiting_on(p.process_id):
                await self._wake(p.process_id)

    # ------------------------------------------------------------------
    # Synchronisation: ownership, inheritance, deadlocks, reclaim
    # ------------------------------------------------------------------

    def _held(self, pid: int) -> set[str]:
        sync = self._sync_manager
        held = {lid for lid, lock in sync._locks.items() if lock.owner == pid}
        held |= {f"sem:{sid}" for sid, sem in sync._semaphores.items() if pid in sem._holders}
        return held

    def _waiting_on(self, pid: int) -> tuple[str, str] | None:
        sync = self._sync_manager
        for lid, lock in sync._locks.items():
            if pid in lock.waiting_pids:
                return ("lock", lid)
        for sid, sem in sync._semaphores.items():
            if any(w == pid for w, _ in sem._waiting):
                return ("sem", sid)
        return None

    async def _priority_inheritance(self) -> None:
        pm = self._process_manager
        owners: set[int] = set()
        for lid, lock in self._sync_manager._locks.items():
            if lock.owner is None:
                continue
            owners.add(lock.owner)
            target = lock.get_inheritance_target()
            if not target:
                continue
            owner_pid, prio = target
            try:
                owner = await pm.get(owner_pid)
            except ProcessNotFound:
                continue
            if prio > owner.priority:
                old = owner.priority
                owner.set_inherited_priority(prio)
                self._note("inherit", pid=owner_pid, name=owner.name, lock=lid, old=old, new=prio)
        for p in await pm.list():
            if p.priority != p.original_priority and p.process_id not in owners:
                p.restore_priority()
                self._note("restore_priority", pid=p.process_id, name=p.name, priority=p.priority)

    def _wait_for_graph(self) -> DeadlockDetector:
        g = DeadlockDetector()
        for lock in self._sync_manager._locks.values():
            if lock.owner is not None:
                for w in lock.waiting_pids:
                    g.add_dependency(w, lock.owner)
        for sem in self._sync_manager._semaphores.values():
            for w, _ in sem._waiting:
                for h in sem._holders:
                    g.add_dependency(w, h)
        return g

    async def _check_deadlocks(self) -> None:
        cycle = self._wait_for_graph().detect_cycle()
        if not cycle:
            return
        pm = self._process_manager
        prios = {pid: (await pm.get(pid)).original_priority for pid in cycle}
        victim = DeadlockDetector().select_victim(cycle, prios)
        waiting = {pid: (self._waiting_on(pid) or ("?", "?"))[1] for pid in cycle}
        await self._event_manager.emit(EventType.DEADLOCK_DETECTED, metadata={
            "cycle": cycle, "victim_pid": victim, "waiting_on": waiting})
        vp = await pm.get(victim)
        self._note("deadlock", cycle=list(cycle), victim=victim, victim_name=vp.name,
                   names=[(await pm.get(p)).name for p in cycle], waiting_on=waiting)
        await self._fail(vp, FailureType.UNKNOWN, "deadlock victim (aborted by kernel)")

    async def _reclaim(self, proc: AgentProcess, why: str) -> None:
        """Release every lock/semaphore the process holds and leave all wait queues."""
        pid = proc.process_id
        sync = self._sync_manager
        for lid, lock in list(sync._locks.items()):
            if lock.owner == pid:
                await sync.release_lock(lid, pid)      # hands off to the next waiter
                self._note("reclaim", pid=pid, name=proc.name, lock=lid, why=why,
                           new_owner=lock.owner)
            lock._waiting = [w for w in lock._waiting if w[0] != pid]
        for sid, sem in list(sync._semaphores.items()):
            if pid in sem._holders:
                await sem.release(pid)
                self._note("reclaim", pid=pid, name=proc.name, lock=f"sem:{sid}", why=why)
            sem._waiting = [w for w in sem._waiting if w[0] != pid]
        sync.deadlock_detector.remove_process(pid)
        if proc.priority != proc.original_priority:
            proc.restore_priority()

    # ------------------------------------------------------------------
    # Failure, restart, termination
    # ------------------------------------------------------------------

    @staticmethod
    def _quota_breach(p: AgentProcess) -> str:
        l, u = p.resource_limits, p.resource_usage
        if u.steps >= l.step_limit:
            return f"step_limit {u.steps}/{l.step_limit}"
        if u.tool_calls >= l.tool_call_limit:
            return f"tool_call_limit {u.tool_calls}/{l.tool_call_limit}"
        if u.llm_calls >= l.llm_call_limit:
            return f"llm_call_limit {u.llm_calls}/{l.llm_call_limit}"
        if u.total_tokens >= l.token_limit:
            return f"token_limit {u.total_tokens}/{l.token_limit}"
        return f"wall_time {u.execution_time:.2f}s/{l.wall_time_limit}s"

    async def _quota_kill(self, proc: AgentProcess, reason: str) -> None:
        await self._event_manager.emit(EventType.RESOURCE_LIMIT, process_id=proc.process_id,
                                       metadata={"limit": reason})
        self._note("quota", pid=proc.process_id, name=proc.name, reason=reason)
        await self._fail(proc, FailureType.RESOURCE_LIMIT, reason, restartable=False)

    async def _to_running(self, proc: AgentProcess) -> None:
        pm = self._process_manager
        if proc.state in (ProcessState.WAITING, ProcessState.BLOCKED):
            await pm.set_state(proc.process_id, ProcessState.READY)
        if proc.state == ProcessState.READY:
            await pm.set_state(proc.process_id, ProcessState.RUNNING)

    async def _fail(self, proc: AgentProcess, ftype: FailureType, err: str,
                    restartable: bool = True, exc: Exception | None = None) -> None:
        pm = self._process_manager
        pid = proc.process_id
        await self._reclaim(proc, "failure")
        self._sleep_until.pop(pid, None)
        self._ipc_wait_since.pop(pid, None)
        await self._to_running(proc)
        await pm.set_state(pid, ProcessState.FAILED)
        self._note("failure", pid=pid, name=proc.name, type=ftype.value, error=err,
                   restartable=restartable, exception=exc)

        if not restartable:
            await pm.set_state(pid, ProcessState.TERMINATED)
            await self._after_death(proc)
            return

        await self._supervisor.handle_failure(pid, ftype, err)
        if proc.state != ProcessState.READY:
            self._note("gave_up", pid=pid, name=proc.name, policy=proc.restart_policy,
                       restarts=proc.restart_count)
            await self._after_death(proc)
            return

        latest = await self._latest_checkpoint(proc)
        on_restart = getattr(proc.agent, "on_restart", None)
        if callable(on_restart):
            on_restart(latest.agent_state if latest else None)
        self._note("restart", pid=pid, name=proc.name, count=proc.restart_count,
                   policy=proc.restart_policy,
                   checkpoint=latest.agent_state if latest else None)

        if proc.restart_policy == RestartPolicy.EXPONENTIAL_BACKOFF.value:
            delay = self._restart_manager.get_backoff_delay(proc.restart_count - 1)
            await pm.set_state(pid, ProcessState.RUNNING)
            await pm.set_state(pid, ProcessState.WAITING, wait_reason=WaitReason.SLEEP)
            self._sleep_until[pid] = time.time() + delay
            self._note("backoff", pid=pid, name=proc.name, delay=delay)

    async def _latest_checkpoint(self, proc: AgentProcess):
        """The checkpoint recorded on the process, else the most recently created one.

        (Timestamps are not usable for ordering: on Windows time.time() ticks
        every ~15 ms, so checkpoints taken close together compare equal.)"""
        if proc.checkpoint_id:
            cp = await self._checkpoint_manager.restore(proc.checkpoint_id)
            if cp is not None:
                return cp
        cps = await self._checkpoint_manager.list_for_process(proc.process_id)
        return cps[-1] if cps else None          # dict insertion order = creation order

    async def _terminate(self, proc: AgentProcess, why: str) -> None:
        pm = self._process_manager
        pid = proc.process_id
        await self._reclaim(proc, why)
        if proc.state == ProcessState.RESTARTING:
            await pm.set_state(pid, ProcessState.FAILED)
        if proc.state != ProcessState.TERMINATED:
            await pm.terminate(pid)
        await self._after_death(proc)

    async def _after_death(self, proc: AgentProcess) -> None:
        pid = proc.process_id
        self._paused.discard(pid)
        self._sleep_until.pop(pid, None)
        self._ipc_wait_since.pop(pid, None)
        self._ipc_timed_out.discard(pid)
        for sched in self._schedulers.values():
            sched.remove(pid)
        for ipc in self._mailboxes:                 # its unread mail can never be read now
            await ipc.discard_mailbox(pid)
        if proc.context_id:
            await self._context_manager.remove(proc.context_id)
            proc.context_id = None
        for child in await self._process_manager.list():
            if child.parent_process_id == pid and child.state in LIVE:
                if self._orphan_policy.get(child.process_id, "TERMINATE") == "TERMINATE":
                    self._note("orphan", pid=child.process_id, name=child.name, parent=proc.name)
                    await self._terminate(child, "orphaned")

    def _note(self, kind: str, **info: Any) -> None:
        info["t"] = time.time()
        m = self._metrics_collector
        if m is not None:
            if kind == "failure":
                m.record_failure(info["pid"])
            elif kind == "restart":
                m.record_restart(info["pid"])
            elif kind == "deadlock":
                m.record_deadlock()
        self.journal.append({"kind": kind, **info})
        for fn in self._observers:
            try:
                fn(kind, info)
            except Exception:  # noqa: BLE001 — observers must not break the kernel
                logger.exception("[Kernel] observer failed")

    # ------------------------------------------------------------------
    # Subsystem Properties (for advanced use)
    # ------------------------------------------------------------------

    @property
    def pm(self) -> ProcessManager:
        """The ProcessManager subsystem."""
        self._require_booted()
        return self._process_manager

    @property
    def ipc(self) -> IPCManager:
        """The IPCManager subsystem."""
        self._require_booted()
        return self._ipc_manager

    @property
    def events(self) -> EventManager:
        """The EventManager subsystem."""
        self._require_booted()
        return self._event_manager

    @property
    def supervisor(self) -> Supervisor:
        """The Supervisor subsystem."""
        self._require_booted()
        return self._supervisor

    @property
    def restart_manager(self) -> RestartManager:
        self._require_booted()
        return self._restart_manager

    @property
    def resources(self) -> ResourceManager:
        self._require_booted()
        return self._resource_manager

    @property
    def sync(self) -> SynchronizationManager:
        """Locks, semaphores and the deadlock detector."""
        self._require_booted()
        return self._sync_manager

    @property
    def contexts(self) -> ContextManager:
        self._require_booted()
        return self._context_manager

    @property
    def checkpoints(self) -> CheckpointManager:
        self._require_booted()
        return self._checkpoint_manager

    @property
    def capabilities(self) -> CapabilityManager:
        self._require_booted()
        return self._capability_manager

    @property
    def scheduler(self) -> Any:
        self._require_booted()
        return self._scheduler

    @property
    def metrics(self) -> MetricsCollector:
        """The MetricsCollector subsystem."""
        self._require_booted()
        return self._metrics_collector

    @property
    def settings(self) -> Settings:
        """The Settings object used by this kernel."""
        return self._settings

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_booted(self) -> None:
        if not self._booted:
            raise KernelNotBootedError(
                "Kernel is not booted. Call await kernel.boot() first."
            )
