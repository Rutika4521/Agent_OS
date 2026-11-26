"""
Mission harness.

A *mission* is one boot of the native `agent_os.Kernel` with its own Settings.
All scenarios of a mission spawn their agents into that one kernel, so they
run concurrently and compete for the scheduler, locks and memory, the way a
real multi-agent workload would. The run loop is `Kernel.run()` itself.

Evidence comes from three native sources:
  * kernel.journal   every kernel decision (failure, restart, deadlock, reclaim, ...)
  * kernel.events    the audit trail (EventManager history)
  * os.evidence      facts the agents record about themselves
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from agent_os.config.settings import Settings
from agent_os.kernel.state_machine import ProcessState
from sdk.kernel import Kernel

from .os_api import LabOS


@dataclass
class Check:
    desc: str
    ok: bool
    evidence: str = ""


@dataclass
class Scenario:
    id: str
    mission: str
    area: str
    title: str
    setup: Callable[["Ctx"], Awaitable[None]]
    verify: Callable[["Ctx"], Awaitable[list[Check]]]
    known_bug: str | None = None
    checks: list[Check] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(c.ok for c in self.checks)


@dataclass
class Mission:
    id: str
    title: str
    story: str
    settings: Callable[[], Settings]
    kernel_kw: dict = field(default_factory=dict)
    run_kw: dict = field(default_factory=dict)
    os_kw: dict = field(default_factory=dict)


@dataclass
class Hook:
    name: str
    pred: Callable[[], bool]
    action: Callable[[], Any]
    fired: bool = False


SCENARIOS: list[Scenario] = []
MISSIONS: dict[str, Mission] = {}


def mission(m: Mission) -> Mission:
    MISSIONS[m.id] = m
    return m


def scenario(id: str, mission_id: str, area: str, title: str, known_bug: str | None = None):
    def deco(cls):
        SCENARIOS.append(Scenario(id, mission_id, area, title, cls.setup, cls.verify, known_bug))
        return cls
    return deco


class Ctx:
    """What setup()/verify() see: the kernel, the lab OS, and query helpers."""

    def __init__(self, kernel: Kernel, los: LabOS):
        self.k, self.os = kernel, los
        self.hooks: list[Hook] = []
        self.t0 = time.time()                # events before this belong to earlier missions

    # ── setup helpers ────────────────────────────────────────────────────────
    async def spawn(self, agent, **kw):
        return await self.os.spawn(agent, **kw)

    def when(self, name: str, pred: Callable[[], bool], action: Callable[[], Any]) -> None:
        self.hooks.append(Hook(name, pred, action))

    @property
    def board(self) -> dict:
        return self.os.board

    # ── verify helpers ───────────────────────────────────────────────────────
    async def proc(self, name: str):
        return await self.k.pm.get(self.os.names[name])

    async def state(self, name: str) -> str:
        return (await self.proc(name)).state.value

    async def restarts(self, name: str) -> int:
        return (await self.proc(name)).restart_count

    def ev(self, key: str, default: Any = None):
        v = self.os.evidence.get(key)
        return v if v else default

    def journal(self, kind: str, name: str | None = None) -> list[dict]:
        return [j for j in self.k.journal if j["kind"] == kind
                and (name is None or j.get("name") == name)]

    def failures(self, name: str) -> list[dict]:
        return self.journal("failure", name)

    def deadlocks(self) -> list[dict]:
        return self.journal("deadlock")

    async def events(self, etype=None, name: str | None = None) -> list:
        hist = await self.k.events.get_history()
        pid = self.os.names.get(name) if name else None
        return [e for e in hist if e.timestamp >= self.t0 and (etype is None or e.event_type == etype)
                and (name is None or e.process_id == pid)]

    def first_tick(self, name: str) -> int | None:
        return next((t for t, _, n, _ in self.os.trace if n == name), None)

    def last_tick(self, name: str) -> int | None:
        ticks = [t for t, _, n, _ in self.os.trace if n == name]
        return ticks[-1] if ticks else None

    def steps_of(self, name: str) -> list[float]:
        return [t for _, _, n, t in self.os.trace if n == name]

    async def all_terminated(self, *names: str) -> bool:
        return all([await self.state(n) == "TERMINATED" for n in names])


async def _operator(ctx: Ctx, stop: asyncio.Event) -> None:
    """Fires one-shot operator hooks while the kernel runs (pause, cancel, revoke, REST calls)."""
    while not stop.is_set():
        for h in ctx.hooks:
            if h.fired:
                continue
            try:
                ok = h.pred()
            except Exception:  # noqa: BLE001
                ok = False
            if ok:
                h.fired = True
                try:
                    r = h.action()
                    if asyncio.iscoroutine(r):
                        await r
                except Exception as e:  # noqa: BLE001
                    ctx.os.log(f"operator action '{h.name}' failed: {e!r}")
        await asyncio.sleep(0.002)


@dataclass
class MissionResult:
    mission: Mission
    scenarios: list[Scenario]
    ctx: Ctx
    seconds: float
    live_after: list[str]


async def run_mission(m: Mission, scenarios: list[Scenario], *, reverse: bool = True,
                      verbose: bool = False, pace: float = 0.0, kernel_extra: dict | None = None,
                      on_boot: Callable[[Kernel], Any] | None = None) -> MissionResult:
    """pace: seconds between steps (live dashboard). kernel_extra: extra Kernel kwargs
    (shared event_manager, pid_base). on_boot(kernel): called once the kernel is up."""
    kernel = Kernel(m.settings(), **{**m.kernel_kw, **(kernel_extra or {})})
    await kernel.boot()
    if on_boot:
        on_boot(kernel)
    los = LabOS(kernel, **m.os_kw)
    los.verbose = verbose
    kernel.observe(lambda kind, i: _narrate(los, kind, i))
    ctx = Ctx(kernel, los)
    los.log(f"══ mission {m.id}: {m.title} ({len(scenarios)} scenarios) ══")
    for s in (reversed(scenarios) if reverse else scenarios):
        s.checks = []
        await s.setup(ctx)

    stop = asyncio.Event()
    op = asyncio.create_task(_operator(ctx, stop))
    t0 = time.time()
    try:
        run_kw = {"max_steps": 20_000, "max_seconds": 60.0, **m.run_kw}
        if pace:
            run_kw["tick_interval"] = pace
            if "max_seconds" not in m.run_kw:
                run_kw["max_seconds"] = 180.0
        await kernel.run(**run_kw)
    finally:
        stop.set()
        await op
    secs = time.time() - t0

    for s in scenarios:
        try:
            s.checks = await s.verify(ctx)
        except Exception as e:  # noqa: BLE001
            s.checks = [Check("verify() raised", False, f"{type(e).__name__}: {e}")]
    live = [f"{p.name}:{p.state.value}" for p in await kernel.pm.list()
            if p.state != ProcessState.TERMINATED]
    await kernel.shutdown()
    return MissionResult(m, scenarios, ctx, secs, live)


def _narrate(los: LabOS, kind: str, i: dict) -> None:
    msg = {
        "failure": lambda: f"✖ {i['name']} FAILED [{i['type']}] {i['error']}",
        "restart": lambda: f"↻ supervisor restarted {i['name']} (#{i['count']}, {i['policy']})"
                           + (f" from checkpoint {i['checkpoint']}" if i.get("checkpoint") else ""),
        "gave_up": lambda: f"⛔ supervisor gave up on {i['name']} ({i['policy']}, {i['restarts']} restarts)",
        "backoff": lambda: f"⏳ backoff {i['delay']:.2f}s before {i['name']} runs again",
        "deadlock": lambda: f"💀 DEADLOCK {' → '.join(i['names'])} | victim {i['victim_name']}",
        "reclaim": lambda: f"♻ reclaimed '{i['lock']}' from {i['name']} ({i['why']})",
        "inherit": lambda: f"⇧ {i['name']} inherits priority {i['old']}→{i['new']} (holds '{i['lock']}')",
        "quota": lambda: f"🚫 {i['name']} hit quota: {i['reason']}",
        "orphan": lambda: f"🌳 orphan {i['name']} terminated (parent {i['parent']} died)",
        "ipc_timeout": lambda: f"⌛ IPC wait timeout → waking {i['name']}",
        "pause": lambda: f"⏸ paused {i['name']} at step {i['step']}",
        "resume": lambda: f"▶ resumed {i['name']} at step {i['step']}",
        "cancel": lambda: f"🛑 cancelled {i['name']} at step {i['step']}",
        "stall": lambda: f"🧊 stall detected: {', '.join(i['processes'])}",
        "timeout": lambda: f"⏰ run exceeded {i['seconds']}s, terminating survivors",
        "completed": lambda: f"✔ {i['name']} completed ({i['steps']} steps)",
        "scheduler": lambda: f"⚙ scheduler = {i['scheduler']}",
    }.get(kind)
    if msg:
        los.log(msg())
