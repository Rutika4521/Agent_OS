"""
LabOS — the syscall surface the Orbital Research Lab agents use.

Every call goes straight to a subsystem owned by the *native* `agent_os.Kernel`
(kernel.sync, kernel.resources, kernel.contexts, kernel.checkpoints,
kernel.capabilities, kernel.ipc, kernel.metrics). LabOS adds only what the
kernel deliberately leaves to the platform: an LLM provider, a tool registry
with capability requirements, a sandbox, and a bounded mailbox.

Agents subclass `LabAgent` and implement `act(s)`, where `s` is a `Syscalls`
handle bound to the running process.
"""
from __future__ import annotations

import copy
import os
import sys
import time
from collections import defaultdict
from typing import Any

from agent_os.ipc.ipc_manager import IPCManager
from agent_os.kernel.state_machine import AgentStepResult, StepStatus, WaitReason
from agent_os.llm.base import LLMRequest
from agent_os.llm.manager import LLMManager
from agent_os.llm.mock import MockLLMProvider
from agent_os.metrics.events import EventType
from agent_os.resources.quota import ResourceLimits
from agent_os.sandbox.sandbox import SubprocessSandbox
from agent_os.security.capability import CapabilityDenied
from agent_os.security.policy import SecurityPolicy

PY = sys.executable

# Tool → capability it requires (tools not listed need no capability)
TOOLS = {
    "web_search": "net.http",
    "telemetry_read": "telemetry.read",
    "db_read": "db.read",
    "db_write": "db.write",
    "deploy": "prod.deploy",
    "notify": None,
}


class LLMError(Exception):
    """Provider failure. Declares its type so the kernel classifies it."""
    failure_type = "LLM_FAILURE"


class LLMTimeout(Exception):
    failure_type = "LLM_TIMEOUT"


class LabOS:
    """Per-mission platform services bound to one native Kernel."""

    def __init__(self, kernel):
        self.k = kernel
        self.board: dict[str, Any] = {}
        self.evidence: dict[str, list] = defaultdict(list)
        self.trace: list[tuple[int, int, str, float]] = []      # (tick, pid, name, t)
        self.tick = 0
        self.names: dict[str, int] = {}
        self.lines: list[str] = []
        self.verbose = False
        self.started = time.time()

        self.llm = LLMManager()
        self.llm.register_provider("mock", MockLLMProvider(default_latency=0.002))
        self.llm.register_provider("outage", MockLLMProvider(failure_mode=True))
        self.llm.register_provider("stalled", MockLLMProvider(timeout_mode=True, timeout_duration=0.15))

        self.policy = SecurityPolicy(kernel.settings)
        for tool, cap in TOOLS.items():
            if cap:
                self.policy.register_tool_capability(tool, cap)
        self.sandbox = SubprocessSandbox(kernel.settings)

        # Mailboxes: the kernel's own IPC plus three bounded ones, one per overflow policy.
        self.mailboxes: dict[str, IPCManager] = {"main": kernel.ipc}
        for box, cap, policy in (("reject", 3, "REJECT"), ("drop", 3, "DROP"), ("block", 2, "BLOCK")):
            st = copy.deepcopy(kernel.settings)
            st.ipc.queue_capacity, st.ipc.overflow_policy = cap, policy
            self.mailboxes[box] = IPCManager(st, kernel.events)
            kernel.attach_ipc(self.mailboxes[box])

    # ── helpers ──────────────────────────────────────────────────────────────
    def log(self, msg: str) -> None:
        line = f"{time.time() - self.started:6.2f}s  {msg}"
        self.lines.append(line)
        if self.verbose:
            print(line, flush=True)

    def pid(self, name: str) -> int:
        return self.names[name]

    def proc_now(self, name: str):
        """Synchronous peek (for operator predicates)."""
        return self.k.pm.process_table._processes.get(self.names.get(name, -1))

    async def spawn(self, agent, *, name: str, priority: int = 5, weight: int = 1,
                    limits: ResourceLimits | None = None, restart: str = "N_TIMES",
                    caps: list[str] | None = None, step_timeout: float = 2.0,
                    parent: int | None = None, orphan_policy: str = "TERMINATE"):
        if isinstance(agent, LabAgent):
            agent.os = self
        p = await self.k.spawn(agent, name=name, priority=priority, weight=weight,
                               resource_limits=limits or ResourceLimits(),
                               capabilities=caps, parent_process_id=parent,
                               restart_policy=restart, step_timeout=step_timeout,
                               orphan_policy=orphan_policy)
        self.names[name] = p.process_id
        return p


class Syscalls:
    """Bound to one process for one step."""

    def __init__(self, los: LabOS, proc, ctx):
        self._os, self._p, self._ctx = los, proc, ctx
        self.k = los.k
        self.pid: int = proc.process_id
        self.name: str = proc.name

    # ── introspection ────────────────────────────────────────────────────────
    @property
    def board(self) -> dict:
        return self._os.board

    @property
    def restarts(self) -> int:
        return self._p.restart_count

    @property
    def priority(self) -> int:
        return self._p.priority

    @property
    def ipc_timed_out(self) -> bool:
        """Set by the kernel when a WAIT(IPC) hit ipc_wait_timeout."""
        return bool(self._ctx.data.get("ipc_timed_out"))

    def log(self, msg: str) -> None:
        self._os.log(f"[{self.name}] {msg}")

    def record(self, key: str, value: Any = True) -> None:
        self._os.evidence[key].append(value)

    # ── step results ─────────────────────────────────────────────────────────
    CONTINUE = AgentStepResult(StepStatus.CONTINUE)
    YIELD = AgentStepResult(StepStatus.YIELD)
    BLOCK = AgentStepResult(StepStatus.BLOCK)

    @staticmethod
    def done(output: Any = None) -> AgentStepResult:
        return AgentStepResult(StepStatus.COMPLETED, output=output)

    @staticmethod
    def failed(error: str) -> AgentStepResult:
        return AgentStepResult(StepStatus.FAILED, error=error)

    @staticmethod
    def sleep(seconds: float) -> AgentStepResult:
        return AgentStepResult(StepStatus.WAIT, output=seconds, wait_reason=WaitReason.SLEEP)

    @staticmethod
    def wait_ipc() -> AgentStepResult:
        return AgentStepResult(StepStatus.WAIT, wait_reason=WaitReason.IPC)

    # ── LLM (metered) ────────────────────────────────────────────────────────
    async def llm(self, prompt: str, in_tokens: int = 50, out_tokens: int = 100,
                  provider: str = "mock") -> str:
        k, p = self.k, self._p
        k.resources.consume_llm_call(p)                        # raises past llm_call_limit
        t0 = time.monotonic()
        try:
            resp = await self._os.llm.get_provider(provider).generate(LLMRequest(prompt=prompt))
        except TimeoutError as exc:
            raise LLMTimeout(str(exc)) from exc
        except Exception as exc:
            raise LLMError(str(exc)) from exc
        k.metrics.record_llm_call(self.pid, time.monotonic() - t0)
        k.metrics.record_tokens(self.pid, in_tokens, out_tokens)
        await k.events.emit(EventType.LLM_CALL, process_id=self.pid, metadata={"prompt": prompt[:40]})
        await k.events.emit(EventType.TOKEN_USAGE, process_id=self.pid,
                            metadata={"input": in_tokens, "output": out_tokens})
        k.resources.consume_tokens(p, in_tokens, out_tokens)   # raises past token_limit
        return resp.content

    # ── tools (capability-gated) ─────────────────────────────────────────────
    async def tool(self, tool_name: str, *args) -> str:
        k = self.k
        if not self._os.policy.check_tool_access(self.pid, tool_name, k.capabilities):
            raise CapabilityDenied(self.pid, self._os.policy.get_required_capability(tool_name))
        k.resources.consume_tool_call(self._p)
        k.metrics.record_tool_call(self.pid, 0.0)
        await k.events.emit(EventType.TOOL_CALL, process_id=self.pid, metadata={"tool": tool_name})
        return f"{tool_name}{args} ok"

    async def sandbox(self, code: str, timeout: float | None = None):
        """Run Python code in the subprocess sandbox (needs sys.exec)."""
        k = self.k
        if not k.capabilities.check(self.pid, "sys.exec"):
            raise CapabilityDenied(self.pid, "sys.exec")
        await k.events.emit(EventType.SANDBOX_STARTED, process_id=self.pid, metadata={"code": code[:40]})
        env = {"SYSTEMROOT": os.environ.get("SYSTEMROOT", "")}
        try:
            res = await self._os.sandbox.execute([PY, "-c", code], env=env, timeout=timeout)
        finally:
            await k.events.emit(EventType.SANDBOX_COMPLETED, process_id=self.pid)
        return res

    # ── IPC ──────────────────────────────────────────────────────────────────
    def _resolve(self, to) -> int:
        return self._os.names.get(to, -1) if isinstance(to, str) else to

    async def send(self, to, payload: Any, *, mtype: str = "DATA", corr: str | None = None,
                   box: str = "main") -> str:
        """box: main (kernel IPC) | reject | drop | block — bounded mailboxes, capacity 3/3/2."""
        ipc = self._os.mailboxes[box]
        msg = await ipc.send(self.pid, self._resolve(to), payload, message_type=mtype, correlation_id=corr)
        if msg.delivery_status == "DELIVERED":
            self.k.metrics.record_ipc_message()
        return msg.delivery_status

    async def recv(self, box: str = "main"):
        ipc = self._os.mailboxes[box]
        return await ipc.receive(self.pid)

    # ── locks & semaphores (kernel.sync) ─────────────────────────────────────
    def holds(self, lock_id: str) -> bool:
        lock = self.k.sync.get_lock(lock_id)
        return lock is not None and lock.owner == self.pid

    async def acquire(self, lock_id: str) -> bool:
        """True = owned now. False = queued; return BLOCK and the kernel wakes you on hand-off."""
        lock = self.k.sync.get_lock(lock_id) or self.k.sync.create_lock(lock_id)
        if self.pid in lock.waiting_pids:
            return False
        return await self.k.sync.acquire_lock(lock_id, self.pid, self._p.priority)

    async def release(self, lock_id: str) -> None:
        await self.k.sync.release_lock(lock_id, self.pid)

    def sem(self, sem_id: str, slots: int):
        return self.k.sync.get_semaphore(sem_id) or self.k.sync.create_semaphore(sem_id, slots)

    def holds_sem(self, sem_id: str) -> bool:
        sem = self.k.sync.get_semaphore(sem_id)
        return sem is not None and self.pid in sem._holders

    async def sem_acquire(self, sem_id: str, slots: int = 1) -> bool:
        sem = self.sem(sem_id, slots)
        if any(w == self.pid for w, _ in sem._waiting):
            return False
        ok = await sem.acquire(self.pid)
        if ok:
            self.record(f"sem_peak:{sem_id}", sem.max_count - sem.available)
        return ok

    async def sem_release(self, sem_id: str) -> None:
        sem = self.k.sync.get_semaphore(sem_id)
        await sem.release(self.pid)
        self.record(f"sem_peak:{sem_id}", sem.max_count - sem.available)

    # ── memory (kernel.contexts) ─────────────────────────────────────────────
    async def _ctx_id(self) -> str:
        if not self._p.context_id:
            self._p.context_id = await self.k.contexts.create(self.pid)
        return self._p.context_id

    async def page_add(self, content: str, pinned: bool = False) -> int:
        page = await self.k.contexts.add_page(await self._ctx_id(), self.pid, content, pinned=pinned)
        return page.index

    async def page_read(self, index: int) -> str | None:
        page = await self.k.contexts.get_page(await self._ctx_id(), index)
        return page.content if page else None

    async def page_update(self, index: int, content: str) -> int:
        cid = await self._ctx_id()
        await self.k.contexts.update_page(cid, index, content)
        return (await self.k.contexts.load(cid))[index].version

    async def page_loaded(self, index: int) -> bool:
        return (await self.k.contexts.load(await self._ctx_id()))[index].loaded

    def loaded_pages_total(self) -> int:
        return self.k.contexts._count_loaded_pages()

    # ── checkpoints ──────────────────────────────────────────────────────────
    async def checkpoint(self, state: dict) -> None:
        p = self._p
        cp = await self.k.checkpoints.create(p.process_id, p.state, context_id=p.context_id or "",
                                             resource_usage={"steps": p.resource_usage.steps},
                                             agent_state=dict(state))
        p.checkpoint_id = cp.checkpoint_id

    # ── process tree ─────────────────────────────────────────────────────────
    async def spawn(self, agent, name: str, priority: int = 5, **kw):
        return await self._os.spawn(agent, name=name, priority=priority, parent=self.pid, **kw)


class LabAgent:
    """Base class: the kernel calls step(); subclasses implement act(s)."""

    os: LabOS | None = None

    async def step(self, ctx):
        los = self.os
        proc = await los.k.pm.get(ctx.process_id)
        los.trace.append((los.tick, proc.process_id, proc.name, time.time()))
        los.tick += 1
        return await self.act(Syscalls(los, proc, ctx))

    async def act(self, s: Syscalls):  # pragma: no cover - abstract
        raise NotImplementedError
