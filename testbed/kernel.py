"""
Agent-OS Testbed — Kernel Driver
================================

Boots EVERY real Agent-OS subsystem and drives them from one scheduling loop:

    ProcessManager + StateMachine      lifecycle, legal transitions only
    PriorityScheduler (+ AgingPolicy)  preemptive priority with starvation aging
    WeightedFairScheduler              deficit-based fair share (phase 2)
    ResourceManager                    token / LLM / tool / step / wall-time quotas
    IPCManager (x2)                    unbounded BLOCK mailbox + bounded REJECT mailbox
    SynchronizationManager             locks, semaphores, wait-for graph
    DeadlockDetector                   cycle detection + victim selection
    Supervisor + RestartManager        NEVER / ONCE / N_TIMES / EXPONENTIAL_BACKOFF
    CheckpointManager                  crash-consistent resume
    ContextManager (+ Swap, LRU)       paged agent memory with eviction
    CapabilityManager + SecurityPolicy capability-gated tools
    SubprocessSandbox                  isolated command execution with timeouts
    LLMManager (MockLLMProvider)       metered LLM calls
    EventManager                       full audit trail (feeds the dashboard)

Agents never touch kernel objects directly. They receive a `Sys` handle in
`ctx.data["sys"]` — the testbed's syscall interface.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "src", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from agent_os.config.settings import Settings
from agent_os.ipc.ipc_manager import IPCManager
from agent_os.kernel.process_manager import ProcessManager
from agent_os.kernel.process_table import ProcessTable
from agent_os.kernel.state_machine import (
    AgentStepResult, ProcessState, StepStatus, WaitReason,
)
from agent_os.llm.base import LLMRequest
from agent_os.llm.manager import LLMManager
from agent_os.llm.mock import MockLLMProvider
from agent_os.memory.checkpoint import CheckpointManager
from agent_os.memory.context_manager import ContextManager
from agent_os.metrics.events import EventManager, EventType
from agent_os.resources.manager import ResourceLimitExceeded, ResourceManager
from agent_os.resources.quota import ResourceLimits
from agent_os.runtime.timeout import StepTimeoutError, execute_with_timeout
from agent_os.sandbox.sandbox import SandboxError, SandboxTimeout, SubprocessSandbox
from agent_os.scheduler.priority import PriorityScheduler
from agent_os.scheduler.weighted_fair import WeightedFairScheduler
from agent_os.security.capability import CapabilityDenied, CapabilityManager
from agent_os.security.policy import SecurityPolicy
from agent_os.supervisor.failure import FailureType
from agent_os.supervisor.restart import RestartManager, RestartPolicy
from agent_os.supervisor.supervisor import Supervisor
from agent_os.synchronization.deadlock import DeadlockDetector
from agent_os.synchronization.lock import LockError
from agent_os.synchronization.sync_manager import SynchronizationManager
from sdk.agent import AgentContext

ACTIVE = (ProcessState.READY, ProcessState.RUNNING, ProcessState.WAITING,
          ProcessState.BLOCKED, ProcessState.RESTARTING, ProcessState.CANCELLING)
DEAD = (ProcessState.TERMINATED, ProcessState.CANCELLED, ProcessState.COMPLETED)


class LLMError(Exception):
    """Raised by Sys.llm when the provider fails."""
    failure_type = "LLM_FAILURE"     # lets any kernel classify it without importing testbed


def make_settings() -> Settings:
    """Testbed tuning: fast aging/backoff and a small page budget so edges trigger quickly."""
    s = Settings()
    s.scheduler.aging.enabled = True
    s.scheduler.aging.interval_seconds = 0.25
    s.scheduler.aging.max_bonus = 10
    s.supervisor.max_restarts = 3
    s.supervisor.failure_window_seconds = 60
    s.supervisor.backoff_initial = 0.15
    s.supervisor.backoff_multiplier = 2.0
    s.supervisor.backoff_max = 2.0
    s.memory.max_loaded_pages = 8
    s.sandbox.timeout_seconds = 5
    s.system.max_processes = 100
    return s


@dataclass
class Hook:
    """A one-shot operator action fired when `pred()` becomes true."""
    name: str
    pred: Callable[[], bool]
    action: Callable[[], Any]
    fired: bool = False


class Sys:
    """The syscall surface handed to an agent for one step."""

    def __init__(self, kernel: "TestbedKernel", proc):
        self._k = kernel
        self._proc = proc
        self.pid: int = proc.process_id
        self.name: str = proc.name

    # ── introspection ────────────────────────────────────────────────────────
    @property
    def board(self) -> dict:
        """Shared blackboard for test choreography (rendezvous flags)."""
        return self._k.board

    @property
    def ipc_timed_out(self) -> bool:
        """True if this step was woken because an IPC wait hit its deadline."""
        return self._k.ipc_timeouts.pop(self.pid, False)

    @property
    def restarts(self) -> int:
        return self._proc.restart_count

    def pid_of(self, name: str) -> int | None:
        return self._k.names.get(name)

    def log(self, msg: str) -> None:
        self._k.log(f"[{self.name}] {msg}")

    def record(self, key: str, value: Any = True) -> None:
        self._k.evidence[key].append(value)

    # ── step results (sugar) ─────────────────────────────────────────────────
    def sleep(self, seconds: float) -> AgentStepResult:
        return AgentStepResult(StepStatus.WAIT, output=seconds, wait_reason=WaitReason.SLEEP)

    def wait_ipc(self) -> AgentStepResult:
        return AgentStepResult(StepStatus.WAIT, wait_reason=WaitReason.IPC)

    # ── LLM ──────────────────────────────────────────────────────────────────
    async def llm(self, prompt: str, in_tokens: int = 50, out_tokens: int = 100,
                  fail: bool = False) -> str:
        k, p = self._k, self._proc
        k.rm.consume_llm_call(p)
        provider = k.failing_llm if fail else k.llm.get_provider("mock")
        try:
            resp = await provider.generate(LLMRequest(prompt=prompt))
        except Exception as exc:
            raise LLMError(str(exc)) from exc
        await k.em.emit(EventType.LLM_CALL, process_id=self.pid,
                        metadata={"prompt": prompt[:40], "latency": round(resp.latency, 4)})
        await k.em.emit(EventType.TOKEN_USAGE, process_id=self.pid,
                        metadata={"input": in_tokens, "output": out_tokens})
        k.rm.consume_tokens(p, in_tokens, out_tokens)      # raises past the quota
        return resp.content

    # ── tools (capability-gated) ─────────────────────────────────────────────
    async def tool(self, tool_name: str, *args) -> Any:
        k = self._k
        if not k.policy.check_tool_access(self.pid, tool_name, k.caps):
            raise CapabilityDenied(self.pid, k.policy.get_required_capability(tool_name))
        k.rm.consume_tool_call(self._proc)
        await k.em.emit(EventType.TOOL_CALL, process_id=self.pid, metadata={"tool": tool_name})
        return f"{tool_name}{args} ok"

    async def sandbox(self, argv: list[str], timeout: float | None = None):
        k = self._k
        if not k.caps.check(self.pid, "sys.exec"):
            raise CapabilityDenied(self.pid, "sys.exec")
        await k.em.emit(EventType.SANDBOX_STARTED, process_id=self.pid, metadata={"argv": argv[-1][:40]})
        env = {"SYSTEMROOT": os.environ.get("SYSTEMROOT", "")}
        try:
            res = await k.sandbox.execute(argv, env=env, timeout=timeout)
        except SandboxTimeout:
            await k.em.emit(EventType.SANDBOX_COMPLETED, process_id=self.pid, metadata={"timed_out": True})
            raise
        await k.em.emit(EventType.SANDBOX_COMPLETED, process_id=self.pid,
                        metadata={"exit_code": res.exit_code, "timed_out": False})
        return res

    # ── IPC ──────────────────────────────────────────────────────────────────
    async def send(self, to: str | int, payload: Any, *, mtype: str = "DATA",
                   corr: str | None = None, bounded: bool = False) -> str:
        """Returns delivery status: DELIVERED | DROPPED."""
        return await self._k.sys_send(self.pid, to, payload, mtype, corr, bounded)

    async def recv(self, bounded: bool = False):
        ipc = self._k.ipc_bounded if bounded else self._k.ipc
        return await ipc.receive(self.pid)

    # ── synchronisation ──────────────────────────────────────────────────────
    def holds(self, lock_id: str) -> bool:
        lock = self._k.sync.get_lock(lock_id)          # ground truth: the lock itself
        return lock is not None and lock.owner == self.pid

    async def acquire(self, lock_id: str) -> bool:
        """True = acquired. False = queued; the agent should return BLOCK."""
        return await self._k.sys_acquire(self._proc, lock_id)

    async def release(self, lock_id: str) -> None:
        await self._k.sys_release(self.pid, lock_id)

    def holds_sem(self, sem_id: str) -> bool:
        sem = self._k.sync.get_semaphore(sem_id)
        return sem is not None and self.pid in sem._holders

    async def sem_acquire(self, sem_id: str) -> bool:
        return await self._k.sys_sem_acquire(self.pid, sem_id)

    async def sem_release(self, sem_id: str) -> None:
        await self._k.sys_sem_release(self.pid, sem_id)

    # ── memory ───────────────────────────────────────────────────────────────
    async def page_add(self, content: str, pinned: bool = False) -> int:
        ctx = await self._k.context_of(self._proc)
        page = await self._k.cm.add_page(ctx, self.pid, content, pinned=pinned)
        return page.index

    async def page_read(self, index: int) -> str | None:
        ctx = await self._k.context_of(self._proc)
        page = await self._k.cm.get_page(ctx, index)
        return page.content if page else None

    async def page_is_loaded(self, index: int) -> bool:
        ctx = await self._k.context_of(self._proc)
        pages = await self._k.cm.load(ctx)
        return pages[index].loaded

    def loaded_pages_total(self) -> int:
        return self._k.cm._count_loaded_pages()

    # ── checkpoint ───────────────────────────────────────────────────────────
    async def checkpoint(self, state: dict) -> None:
        k, p = self._k, self._proc
        cp = await k.ckpt.create(p.process_id, p.state, context_id=p.context_id or "",
                                 resource_usage={"steps": p.resource_usage.steps},
                                 agent_state=dict(state))
        p.checkpoint_id = cp.checkpoint_id

    # ── process tree ─────────────────────────────────────────────────────────
    async def spawn(self, agent, name: str, priority: int = 5, **kw):
        return await self._k.spawn(agent, name=name, priority=priority,
                                   parent=self.pid, **kw)


class TestbedKernel:
    __test__ = False  # not a pytest test class

    def __init__(self, settings: Settings | None = None, *,
                 event_manager: EventManager | None = None,
                 process_manager: ProcessManager | None = None,
                 ipc_manager: IPCManager | None = None,
                 pace: float = 0.0, verbose: bool = True):
        s = self.settings = settings or make_settings()
        self.em = event_manager or EventManager()
        self.pm = process_manager or ProcessManager(ProcessTable(), self.em, s)
        self.rm = ResourceManager(s)
        self.ipc = ipc_manager or IPCManager(s, self.em)
        # Bounded mailbox: capacity 3, REJECT on overflow (backpressure scenarios)
        bounded = make_settings()
        bounded.ipc.queue_capacity = 3
        bounded.ipc.overflow_policy = "REJECT"
        self.ipc_bounded = IPCManager(bounded, self.em)
        self.sync = SynchronizationManager(self.em)
        self.ckpt = CheckpointManager(self.em)
        self.cm = ContextManager(s, self.em)
        # NOTE: ContextManager reads settings.max_loaded_pages (top-level) instead
        # of settings.memory.max_loaded_pages, so config is silently ignored.
        self.cm.max_loaded_pages = s.memory.max_loaded_pages
        self.restart_mgr = RestartManager(s.supervisor)
        self.sup = Supervisor(self.pm, self.restart_mgr, self.em, self.ckpt)
        self.caps = CapabilityManager(s.security.default_capabilities)
        self.policy = SecurityPolicy(s)
        for tool, cap in (("http_get", "net.http"), ("db_write", "db.write"),
                          ("db_read", "db.read"), ("deploy", "prod.deploy")):
            self.policy.register_tool_capability(tool, cap)
        self.sandbox = SubprocessSandbox(s)
        self.llm = LLMManager()
        self.llm.register_provider("mock", MockLLMProvider(default_latency=0.002))
        self.failing_llm = MockLLMProvider(failure_mode=True)
        self.priority_sched = PriorityScheduler(settings=s)
        self.fair_sched = WeightedFairScheduler()
        self.scheduler = self.priority_sched
        self.scheduler_name = "priority"

        self.pace, self.verbose = pace, verbose
        self.tick = 0
        self.names: dict[str, int] = {}
        self.board: dict[str, Any] = {}
        self.evidence: dict[str, list] = defaultdict(list)
        self.findings: dict[str, str] = {}
        self.trace: list[tuple[int, int, str, float]] = []      # (tick, pid, name, t)
        self.held_locks: dict[int, set[str]] = defaultdict(set)
        self.held_sems: dict[int, set[str]] = defaultdict(set)
        self.blocked_on: dict[int, tuple[str, str]] = {}
        self.sleep_until: dict[int, float] = {}
        self.ipc_wait_since: dict[int, float] = {}
        self.ipc_timeouts: dict[int, bool] = {}
        self.ipc_wait_timeout = 1.0
        self.step_timeouts: dict[int, float] = {}
        self.orphan_policy: dict[int, str] = {}
        self.paused: set[int] = set()
        self.hooks: list[Hook] = []
        self.deadlocks: list[dict] = []
        self.failures: list[dict] = []
        self.restart_delays: dict[int, list[float]] = defaultdict(list)
        self.lines: list[str] = []
        self.started = time.time()

    # ── helpers ──────────────────────────────────────────────────────────────
    def log(self, msg: str) -> None:
        line = f"{time.time() - self.started:6.2f}s  {msg}"
        self.lines.append(line)
        if self.verbose:
            print(line, flush=True)

    def finding(self, key: str, text: str) -> None:
        if key not in self.findings:
            self.findings[key] = text
            self.log(f"⚠ FINDING: {text}")

    def name_of(self, pid: int) -> str:
        for n, p in self.names.items():
            if p == pid:
                return n
        return f"pid{pid}"

    def when(self, name: str, pred: Callable[[], bool], action: Callable[[], Any]) -> None:
        self.hooks.append(Hook(name, pred, action))

    def use_scheduler(self, kind: str) -> None:
        self.scheduler = self.fair_sched if kind == "weighted_fair" else self.priority_sched
        self.scheduler_name = kind
        self.log(f"⚙ scheduler switched → {kind}")

    async def proc(self, name_or_pid: str | int):
        pid = self.names[name_or_pid] if isinstance(name_or_pid, str) else name_or_pid
        return await self.pm.get(pid)

    def proc_now(self, name: str):
        """Synchronous peek for hook predicates."""
        return self.pm.process_table._processes.get(self.names.get(name, -1))

    async def context_of(self, proc) -> str:
        if not proc.context_id:
            proc.context_id = await self.cm.create(proc.process_id)
        return proc.context_id

    async def _set(self, pid: int, state: ProcessState, reason: WaitReason | None = None):
        await self.pm.set_state(pid, state, wait_reason=reason)

    async def _to_running(self, proc) -> None:
        """Walk any live state legally into RUNNING."""
        if proc.state in (ProcessState.WAITING, ProcessState.BLOCKED):
            await self._set(proc.process_id, ProcessState.READY)
        if proc.state == ProcessState.READY:
            await self._set(proc.process_id, ProcessState.RUNNING)

    async def _wake(self, pid: int) -> None:
        p = await self.pm.get(pid)
        if p.state in (ProcessState.WAITING, ProcessState.BLOCKED) and pid not in self.paused:
            self.sleep_until.pop(pid, None)
            self.ipc_wait_since.pop(pid, None)
            await self._set(pid, ProcessState.READY)

    # ── process creation ─────────────────────────────────────────────────────
    async def spawn(self, agent, *, name: str, priority: int = 5, weight: int = 1,
                    limits: ResourceLimits | None = None, restart: str = "N_TIMES",
                    caps: list[str] | None = None, step_timeout: float = 2.0,
                    parent: int | None = None, orphan_policy: str = "TERMINATE"):
        p = await self.pm.spawn(agent, name=name, priority=priority, weight=weight,
                                resource_limits=limits or ResourceLimits(),
                                capabilities=caps or [], parent_process_id=parent,
                                restart_policy=restart)
        self.names[name] = p.process_id
        self.caps.initialize_process(p.process_id, caps or [])
        self.step_timeouts[p.process_id] = step_timeout
        self.orphan_policy[p.process_id] = orphan_policy
        self.fair_sched.add(p)
        if parent is not None:
            (await self.pm.get(parent)).resource_usage.child_processes += 1
        return p

    # ── IPC ──────────────────────────────────────────────────────────────────
    def mailbox(self, pid: int, bounded: bool = False) -> int:
        ipc = self.ipc_bounded if bounded else self.ipc
        q = ipc._queues.get(pid)
        return q.count() if q else 0

    async def sys_send(self, src: int, to, payload, mtype, corr, bounded) -> str:
        dst = self.names.get(to) if isinstance(to, str) else to
        alive = False
        if dst is not None:
            try:
                alive = (await self.pm.get(dst)).state not in DEAD + (ProcessState.FAILED,)
            except Exception:
                alive = False
        if not alive:
            # Kernel IPCManager would happily queue this forever (dead-letter leak).
            await self.em.emit(EventType.IPC_DROPPED, process_id=src, metadata={
                "sender_pid": src, "receiver_pid": dst, "reason": "receiver not alive"})
            self.evidence["dead_letters"].append((src, to))
            return "DROPPED"
        ipc = self.ipc_bounded if bounded else self.ipc
        msg = await ipc.send(src, dst, payload, message_type=mtype, correlation_id=corr)
        if msg.delivery_status == "DELIVERED":
            p = await self.pm.get(dst)
            if p.state == ProcessState.WAITING and p.waiting_for == WaitReason.IPC:
                await self._wake(dst)
        return msg.delivery_status

    # ── locks ────────────────────────────────────────────────────────────────
    async def sys_acquire(self, proc, lock_id: str) -> bool:
        pid = proc.process_id
        lock = self.sync.get_lock(lock_id) or self.sync.create_lock(lock_id)
        if pid in lock.waiting_pids:
            return False
        ok = await self.sync.acquire_lock(lock_id, pid, proc.priority)   # LockError if re-entrant
        if ok:
            self.held_locks[pid].add(lock_id)
            return True
        self.blocked_on[pid] = ("lock", lock_id)
        target = lock.get_inheritance_target()
        if target:
            owner_pid, prio = target
            owner = await self.pm.get(owner_pid)
            if prio > owner.priority:
                old = owner.priority
                owner.set_inherited_priority(prio)
                self.evidence["inheritance"].append((owner.name, old, prio))
                self.log(f"⇧ priority inheritance: {owner.name} {old}→{prio} (holds '{lock_id}', blocks {proc.name})")
        return False

    async def sys_release(self, pid: int, lock_id: str) -> None:
        lock = self.sync.get_lock(lock_id)
        if lock is None:
            return
        await self.sync.release_lock(lock_id, pid)
        self.held_locks[pid].discard(lock_id)
        me = await self.pm.get(pid)
        if not self.held_locks[pid] and me.priority != me.original_priority:
            me.restore_priority()
        new_owner = lock.owner
        if new_owner is not None:
            self.held_locks[new_owner].add(lock_id)
            self.blocked_on.pop(new_owner, None)
            self.log(f"🔑 '{lock_id}' handed {self.name_of(pid)} → {self.name_of(new_owner)}")
            await self._wake(new_owner)

    async def sys_sem_acquire(self, pid: int, sem_id: str) -> bool:
        sem = self.sync.get_semaphore(sem_id)
        if any(w == pid for w, _ in sem._waiting):
            return False
        if await sem.acquire(pid):
            self.held_sems[pid].add(sem_id)
            await self.em.emit(EventType.LOCK_ACQUIRED, process_id=pid, metadata={"lock_id": f"sem:{sem_id}"})
            self.evidence[f"sem_peak:{sem_id}"].append(sem.max_count - sem.available)
            return True
        self.blocked_on[pid] = ("sem", sem_id)
        return False

    async def sys_sem_release(self, pid: int, sem_id: str) -> None:
        sem = self.sync.get_semaphore(sem_id)
        nxt = await sem.release(pid)
        self.held_sems[pid].discard(sem_id)
        await self.em.emit(EventType.LOCK_RELEASED, process_id=pid, metadata={"lock_id": f"sem:{sem_id}"})
        if nxt is not None:
            self.held_sems[nxt].add(sem_id)
            self.blocked_on.pop(nxt, None)
            await self.em.emit(EventType.LOCK_ACQUIRED, process_id=nxt, metadata={"lock_id": f"sem:{sem_id}"})
            self.evidence[f"sem_peak:{sem_id}"].append(sem.max_count - sem.available)
            await self._wake(nxt)

    async def _reclaim(self, pid: int, why: str) -> None:
        """Kernel-side cleanup: release every lock/semaphore, leave wait queues, free memory."""
        for lock_id in list(self.held_locks[pid]):
            self.evidence["reclaimed_locks"].append((self.name_of(pid), lock_id, why))
            self.log(f"♻ kernel reclaimed lock '{lock_id}' from {self.name_of(pid)} ({why})")
            await self.sys_release(pid, lock_id)
        for sem_id in list(self.held_sems[pid]):
            await self.sys_sem_release(pid, sem_id)
        kind_id = self.blocked_on.pop(pid, None)
        if kind_id:
            kind, rid = kind_id
            if kind == "lock":
                lock = self.sync.get_lock(rid)
                lock._waiting = [w for w in lock._waiting if w[0] != pid]
            else:
                sem = self.sync.get_semaphore(rid)
                sem._waiting = [w for w in sem._waiting if w[0] != pid]
        self.sync.deadlock_detector.remove_process(pid)

    async def _free_memory(self, proc) -> None:
        if proc.context_id:
            await self.cm.remove(proc.context_id)
            proc.context_id = None

    # ── deadlock detection & recovery ────────────────────────────────────────
    def _wait_for_graph(self) -> DeadlockDetector:
        g = DeadlockDetector()
        for lock in self.sync._locks.values():
            if lock.owner is not None:
                for w in lock.waiting_pids:
                    g.add_dependency(w, lock.owner)
        for sem in self.sync._semaphores.values():
            for w, _ in sem._waiting:
                for h in sem._holders:
                    g.add_dependency(w, h)
        return g

    async def _check_deadlocks(self) -> None:
        cycle = self._wait_for_graph().detect_cycle()
        if not cycle:
            return
        if not self.sync.deadlock_detector.detect_cycle():
            self.finding("detector_stale",
                         "SynchronizationManager's incremental wait-for graph missed a real cycle "
                         "(edges are dropped on lock hand-off); testbed rebuilt it from lock state.")
        prios = {}
        for pid in cycle:
            prios[pid] = (await self.pm.get(pid)).original_priority
        victim = DeadlockDetector().select_victim(cycle, prios)
        names = [self.name_of(p) for p in cycle]
        locks = {self.name_of(p): self.blocked_on.get(p, ("?", "?"))[1] for p in cycle}
        await self.em.emit(EventType.DEADLOCK_DETECTED, metadata={
            "cycle": cycle, "victim_pid": victim, "waiting_on": locks})
        self.deadlocks.append({"cycle": names, "victim": self.name_of(victim),
                               "t": time.time(), "tick": self.tick})
        self.log(f"💀 DEADLOCK {' → '.join(names)} → {names[0]}  | victim: {self.name_of(victim)} (lowest priority)")
        vp = await self.pm.get(victim)
        await self._fail(vp, FailureType.UNKNOWN, "deadlock victim (aborted by kernel)")

    # ── failure handling ─────────────────────────────────────────────────────
    async def _fail(self, proc, ftype: FailureType, err: str, restartable: bool = True) -> None:
        pid = proc.process_id
        await self._reclaim(pid, "failure")
        await self._to_running(proc)
        await self._set(pid, ProcessState.FAILED)
        self.failures.append({"name": proc.name, "type": ftype.value, "error": err,
                              "t": time.time(), "restartable": restartable})
        self.log(f"✖ {proc.name} FAILED [{ftype.value}] {err}")
        if not restartable:
            await self._terminate(proc, "hard kill: " + ftype.value)
            return
        await self.sup.handle_failure(pid, ftype, err)
        proc = await self.pm.get(pid)
        if proc.state == ProcessState.READY:
            latest = (await self.ckpt.restore(proc.checkpoint_id)) if proc.checkpoint_id else None
            if latest is None:
                cps = await self.ckpt.list_for_process(pid)
                latest = cps[-1] if cps else None     # creation order; timestamps can tie
            if hasattr(proc.agent, "on_restart"):
                proc.agent.on_restart(latest.agent_state if latest else None)
            self.log(f"↻ supervisor restarted {proc.name} (#{proc.restart_count}, policy={proc.restart_policy})"
                     + (f" from checkpoint {latest.agent_state}" if latest else ""))
            if proc.restart_policy == RestartPolicy.EXPONENTIAL_BACKOFF.value:
                delay = self.restart_mgr.get_backoff_delay(proc.restart_count - 1)
                self.restart_delays[pid].append(delay)
                self.log(f"⏳ backoff {delay:.2f}s before {proc.name} may run again")
                await self._set(pid, ProcessState.RUNNING)
                await self._set(pid, ProcessState.WAITING, WaitReason.SLEEP)
                self.sleep_until[pid] = time.time() + delay
        else:
            self.log(f"⛔ supervisor gave up on {proc.name} (policy={proc.restart_policy}, restarts={proc.restart_count})")
            await self._after_death(proc)

    async def _terminate(self, proc, why: str) -> None:
        pid = proc.process_id
        await self._reclaim(pid, why)
        proc = await self.pm.get(pid)
        if proc.state not in (ProcessState.TERMINATED,):
            if proc.state in (ProcessState.READY, ProcessState.RUNNING,
                              ProcessState.WAITING, ProcessState.BLOCKED):
                await self.pm.cancel(pid)
            await self.pm.terminate(pid)
        await self._after_death(proc)

    async def _after_death(self, proc) -> None:
        pid = proc.process_id
        self.paused.discard(pid)
        self.sleep_until.pop(pid, None)
        self.ipc_wait_since.pop(pid, None)
        self.fair_sched.remove(pid)
        await self._free_memory(proc)
        # Orphan policy: cascade to children
        for child in await self.pm.list():
            if child.parent_process_id == pid and child.state in ACTIVE:
                if self.orphan_policy.get(child.process_id) == "TERMINATE":
                    self.log(f"🌳 orphan policy: terminating {child.name} (parent {proc.name} died)")
                    self.evidence["orphans_killed"].append(child.name)
                    await self._terminate(child, "orphaned")

    # ── operator controls (used by hooks) ────────────────────────────────────
    async def pause(self, name: str) -> None:
        p = await self.proc(name)
        if p.state == ProcessState.READY:
            await self._set(p.process_id, ProcessState.RUNNING)
            await self.pm.pause(p.process_id)          # RUNNING → WAITING(SLEEP)
            self.paused.add(p.process_id)
            self.evidence["paused_at_step"].append(p.resource_usage.steps)
            self.log(f"⏸ operator paused {name} at step {p.resource_usage.steps}")

    async def resume(self, name: str) -> None:
        p = await self.proc(name)
        self.paused.discard(p.process_id)
        await self.pm.resume(p.process_id)
        self.evidence["resumed_at_step"].append(p.resource_usage.steps)
        self.log(f"▶ operator resumed {name} at step {p.resource_usage.steps}")

    async def cancel(self, name: str) -> None:
        p = await self.proc(name)
        await self._reclaim(p.process_id, "cancelled")
        await self.pm.cancel(p.process_id)
        await self.pm.terminate(p.process_id)
        await self._after_death(p)
        self.evidence["cancelled"].append((name, p.resource_usage.steps))
        self.log(f"🛑 operator cancelled {name} at step {p.resource_usage.steps}")

    # ── one scheduling quantum ───────────────────────────────────────────────
    def _quota_breach(self, p) -> str:
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

    async def _quota_kill(self, proc, reason: str) -> None:
        await self.em.emit(EventType.RESOURCE_LIMIT, process_id=proc.process_id,
                           metadata={"limit": reason})
        self.evidence["quota_kills"].append((proc.name, reason))
        await self._fail(proc, FailureType.RESOURCE_LIMIT, reason, restartable=False)

    async def _run_one(self, proc) -> None:
        pid = proc.process_id
        if not self.rm.can_execute(proc):
            await self._quota_kill(proc, self._quota_breach(proc))
            return
        await self._set(pid, ProcessState.RUNNING)
        self.trace.append((self.tick, pid, proc.name, time.time()))
        ctx = AgentContext(process_id=pid, data={"sys": Sys(self, proc)})
        t0 = time.monotonic()
        try:
            result = await execute_with_timeout(proc.agent.step(ctx), self.step_timeouts.get(pid, 2.0))
        except StepTimeoutError as e:
            proc.resource_usage.execution_time += time.monotonic() - t0
            await self._fail(proc, FailureType.TOOL_TIMEOUT, str(e))
            return
        except ResourceLimitExceeded as e:
            proc.resource_usage.execution_time += time.monotonic() - t0
            await self._quota_kill(proc, f"{e.resource_type} exceeded mid-step "
                                         f"(tokens={proc.resource_usage.total_tokens})")
            return
        except CapabilityDenied as e:
            self.evidence["denied"].append((proc.name, e.capability))
            await self._fail(proc, FailureType.TOOL_FAILURE, str(e), restartable=False)
            return
        except LLMError as e:
            await self._fail(proc, FailureType.LLM_FAILURE, str(e))
            return
        except SandboxError as e:
            await self._fail(proc, FailureType.SANDBOX_FAILURE, str(e))
            return
        except LockError as e:
            await self._fail(proc, FailureType.AGENT_EXCEPTION, f"LockError: {e}")
            return
        except Exception as e:  # noqa: BLE001
            await self._fail(proc, FailureType.AGENT_EXCEPTION, f"{type(e).__name__}: {e}")
            return
        proc.resource_usage.execution_time += time.monotonic() - t0
        self.rm.consume_step(proc)
        await self._apply(proc, result)

    async def _apply(self, proc, result: AgentStepResult) -> None:
        pid, st = proc.process_id, result.status
        if st in (StepStatus.CONTINUE, StepStatus.YIELD):
            await self._set(pid, ProcessState.READY)
        elif st == StepStatus.WAIT:
            reason = result.wait_reason or WaitReason.IPC
            if reason == WaitReason.SLEEP:
                await self._set(pid, ProcessState.WAITING, WaitReason.SLEEP)
                self.sleep_until[pid] = time.time() + float(result.output or 0.05)
            elif self.mailbox(pid) or self.mailbox(pid, bounded=True):
                await self._set(pid, ProcessState.READY)
            else:
                await self._set(pid, ProcessState.WAITING, WaitReason.IPC)
                self.ipc_wait_since[pid] = time.time()
        elif st == StepStatus.BLOCK:
            if pid in self.blocked_on:
                kind = self.blocked_on[pid][0]
                await self._set(pid, ProcessState.BLOCKED,
                                WaitReason.LOCK if kind == "lock" else WaitReason.RESOURCE)
            else:
                await self._set(pid, ProcessState.READY)     # granted in the meantime
        elif st == StepStatus.COMPLETED:
            if self.held_locks[pid] or self.held_sems[pid]:
                self.evidence["lock_leaks"].append((proc.name, sorted(self.held_locks[pid])))
                await self._reclaim(pid, "exited while holding")
            await self._set(pid, ProcessState.COMPLETED)
            await self.pm.terminate(pid)
            self.log(f"✔ {proc.name} completed ({proc.resource_usage.steps} steps)")
            await self._after_death(proc)
        elif st == StepStatus.FAILED:
            await self._fail(proc, FailureType.AGENT_EXCEPTION, result.error or "agent returned FAILED")

    # ── main loop ────────────────────────────────────────────────────────────
    async def run(self, max_seconds: float = 90.0) -> None:
        deadline = time.time() + max_seconds
        idle_since: float | None = None
        while True:
            now = time.time()
            if now > deadline:
                self.finding("timeout", f"run exceeded {max_seconds}s; aborted remaining processes")
                for p in await self.pm.list():
                    if p.state in ACTIVE:
                        await self._terminate(p, "run timeout")
                break
            for pid, t in list(self.sleep_until.items()):
                if now >= t:
                    del self.sleep_until[pid]
                    await self._wake(pid)
            for pid, t in list(self.ipc_wait_since.items()):
                if now - t >= self.ipc_wait_timeout:
                    self.ipc_timeouts[pid] = True
                    self.evidence["ipc_timeouts"].append(self.name_of(pid))
                    self.log(f"⌛ IPC wait timeout for {self.name_of(pid)} — waking it")
                    await self._wake(pid)
            for h in self.hooks:
                if not h.fired:
                    try:
                        ok = h.pred()
                    except Exception:
                        ok = False
                    if ok:
                        h.fired = True
                        r = h.action()
                        if asyncio.iscoroutine(r):
                            await r
            await self._check_deadlocks()

            ready = [p for p in await self.pm.list(state=ProcessState.READY)]
            if not ready:
                active = [p for p in await self.pm.list() if p.state in ACTIVE]
                if not active:
                    break
                if not self.sleep_until and not self.ipc_wait_since and not self.paused:
                    idle_since = idle_since or now
                    if now - idle_since > 3.0:
                        names = ", ".join(f"{p.name}:{p.state.value}" for p in active)
                        self.finding("stall", f"system stalled with no runnable process: {names}")
                        for p in active:
                            await self._terminate(p, "stalled")
                        break
                else:
                    idle_since = None
                await asyncio.sleep(0.005)
                continue
            idle_since = None
            chosen = self.scheduler.select_next(ready)
            if chosen is None:
                await asyncio.sleep(0.005)
                continue
            await self._run_one(chosen)
            self.tick += 1
            await asyncio.sleep(self.pace)
