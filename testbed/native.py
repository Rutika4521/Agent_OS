"""
Run the testbed's multi-agent system on Agent-OS's OWN runtime — the public
`agent_os.Kernel().run()` loop in sdk/kernel.py — and compare it with the
testbed driver.

    python testbed/native.py

What is native here
-------------------
* Every runtime decision is sdk.Kernel: scheduling (priority + aging /
  weighted_fair), quota enforcement, step timeouts, supervisor restarts,
  checkpoint resume, backoff, BLOCK/WAIT handling, deadlock detection,
  lock/memory reclaim, orphan policy, pause/resume/cancel.
* The testbed agents use the kernel's own subsystems through their syscalls:
  kernel.sync, kernel.resources, kernel.contexts, kernel.checkpoints,
  kernel.capabilities, kernel.ipc.
* The testbed driver loop (TestbedKernel.run) is NOT used.

What the adapter does (observation only)
----------------------------------------
* hands the agent its `sys` syscall handle in ctx.data
* records the schedule trace (the kernel keeps no per-step trace)
* translates the kernel's journal (kernel.observe) into the evidence the
  scenario checks read: failures, deadlocks, backoff delays, reclaims, ...
* runs the operator hooks (pause / cancel / revoke) as a concurrent task,
  calling the kernel's own pause()/resume()/cancel()
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

from kernel import Sys, TestbedKernel, make_settings  # noqa: E402
from runner import run_testbed  # noqa: E402

from agent_os.resources.quota import ResourceLimits  # noqa: E402
from agent_os.security.capability import CapabilityDenied  # noqa: E402
from sdk.kernel import Kernel  # noqa: E402

G, R, Y, D, B, X = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[1m", "\033[0m"
NATIVE_MAX_SECONDS = 90.0    # same ceiling the driver uses
NATIVE_MAX_STEPS = 20_000


class Observer:
    """Transparent wrapper: injects `sys`, records the trace, changes nothing."""

    def __init__(self, agent, tb: "NativeTestbed"):
        self.agent, self.tb = agent, tb

    def __getattr__(self, item):            # forwards on_restart() etc. to the agent
        return getattr(self.agent, item)

    async def step(self, ctx):
        tb = self.tb
        proc = await tb.pm.get(ctx.process_id)
        tb.trace.append((tb.tick, proc.process_id, proc.name, time.time()))
        tb.tick += 1
        if ctx.data.get("ipc_timed_out"):
            tb.ipc_timeouts[proc.process_id] = True
        ctx.data["sys"] = Sys(tb, proc)
        return await self.agent.step(ctx)


class NativeTestbed(TestbedKernel):
    """The testbed's syscall layer + scenario plumbing, running on sdk.Kernel."""

    def __init__(self, k: Kernel, **kw):
        super().__init__(k.settings, event_manager=k.events, process_manager=k.pm,
                         ipc_manager=k.ipc, **kw)
        self.k = k
        # Share the kernel's subsystems so its loop sees every lock, quota, page, capability.
        self.sync, self.rm, self.cm = k.sync, k.resources, k.contexts
        self.ckpt, self.caps = k.checkpoints, k.capabilities
        self.sup, self.restart_mgr = k.supervisor, k.restart_manager
        k.attach_ipc(self.ipc_bounded)
        k.observe(self._on_kernel)
        self.phase_outcomes: list[tuple[float, str]] = []

    # ── kernel journal → scenario evidence ───────────────────────────────────
    def _on_kernel(self, kind: str, i: dict) -> None:
        ev = self.evidence
        if kind == "failure":
            self.failures.append({"name": i["name"], "type": i["type"], "error": i["error"],
                                  "t": i["t"], "restartable": i["restartable"]})
            if isinstance(i.get("exception"), CapabilityDenied):
                ev["denied"].append((i["name"], i["exception"].capability))
            self.log(f"✖ {i['name']} FAILED [{i['type']}] {i['error']}")
        elif kind == "deadlock":
            self.deadlocks.append({"cycle": i["names"], "victim": i["victim_name"],
                                   "t": i["t"], "tick": self.tick})
            self.log(f"💀 DEADLOCK {' → '.join(i['names'])} | victim: {i['victim_name']}")
        elif kind == "backoff":
            self.restart_delays[i["pid"]].append(i["delay"])
            self.log(f"⏳ backoff {i['delay']:.2f}s before {i['name']} may run again")
        elif kind == "restart":
            self.log(f"↻ kernel restarted {i['name']} (#{i['count']}, policy={i['policy']})")
        elif kind == "gave_up":
            self.log(f"⛔ supervisor gave up on {i['name']} (policy={i['policy']})")
        elif kind == "reclaim":
            if not i["lock"].startswith("sem:"):
                ev["reclaimed_locks"].append((i["name"], i["lock"], i["why"]))
            self.held_locks[i["pid"]].discard(i["lock"])
            self.log(f"♻ kernel reclaimed '{i['lock']}' from {i['name']} ({i['why']})")
        elif kind == "leak":
            ev["lock_leaks"].append((i["name"], i["locks"]))
        elif kind == "quota":
            ev["quota_kills"].append((i["name"], i["reason"]))
        elif kind == "orphan":
            ev["orphans_killed"].append(i["name"])
            self.log(f"🌳 orphan policy: terminating {i['name']} (parent {i['parent']} died)")
        elif kind == "ipc_timeout":
            ev["ipc_timeouts"].append(i["name"])
        elif kind == "pause":
            ev["paused_at_step"].append(i["step"])
        elif kind == "resume":
            ev["resumed_at_step"].append(i["step"])
        elif kind == "cancel":
            ev["cancelled"].append((i["name"], i["step"]))
        elif kind == "stall":
            self.finding("stall", f"system stalled with no runnable process: {', '.join(i['processes'])}")
        elif kind == "timeout":
            self.finding("timeout", f"run exceeded {i['seconds']}s; aborted remaining processes")

    # ── process creation and operator controls go through the kernel ─────────
    async def spawn(self, agent, *, name: str, priority: int = 5, weight: int = 1,
                    limits: ResourceLimits | None = None, restart: str = "N_TIMES",
                    caps: list[str] | None = None, step_timeout: float = 2.0,
                    parent: int | None = None, orphan_policy: str = "TERMINATE"):
        p = await self.k.spawn(Observer(agent, self), name=name, priority=priority, weight=weight,
                               resource_limits=limits or ResourceLimits(), capabilities=caps or [],
                               parent_process_id=parent, restart_policy=restart,
                               step_timeout=step_timeout, orphan_policy=orphan_policy)
        self.names[name] = p.process_id
        return p

    def use_scheduler(self, kind: str) -> None:
        self.k.use_scheduler(kind)
        self.log(f"⚙ scheduler switched → {kind}")

    async def pause(self, name: str) -> None:
        await self.k.pause(self.names[name])

    async def resume(self, name: str) -> None:
        await self.k.resume(self.names[name])

    async def cancel(self, name: str) -> None:
        await self.k.cancel(self.names[name])


async def _operator(tb: NativeTestbed, stop: asyncio.Event):
    while not stop.is_set():
        for h in tb.hooks:
            if not h.fired:
                try:
                    ok = h.pred()
                except Exception:
                    ok = False
                if ok:
                    h.fired = True
                    try:
                        r = h.action()
                        if asyncio.iscoroutine(r):
                            await r
                    except Exception as e:  # noqa: BLE001
                        tb.log(f"operator action '{h.name}' failed: {e!r}")
        await asyncio.sleep(0.002)


async def native_phase(tb: NativeTestbed):
    stop = asyncio.Event()
    op = asyncio.create_task(_operator(tb, stop))
    t0 = time.time()
    try:
        await tb.k.run(max_steps=NATIVE_MAX_STEPS, max_seconds=NATIVE_MAX_SECONDS)
        live = [p for p in await tb.pm.list()
                if p.state.value in ("READY", "WAITING", "BLOCKED", "RUNNING")]
        outcome = (f"hit max_steps={NATIVE_MAX_STEPS} with {len(live)} processes still live"
                   if live else "all processes reached a terminal state")
    except Exception as e:  # noqa: BLE001
        outcome = f"Kernel.run() crashed: {type(e).__name__}: {e}"
    finally:
        stop.set()
        await op
    tb.phase_outcomes.append((round(time.time() - t0, 1), outcome))
    tb.log(f"native run loop ended: {outcome}")


async def run_native(verbose: bool = False) -> tuple[NativeTestbed, list]:
    sdk_kernel = Kernel(make_settings(), default_step_timeout=2.0,
                        ipc_wait_timeout=1.0, stall_timeout=3.0)
    await sdk_kernel.boot()
    tb = NativeTestbed(sdk_kernel, verbose=verbose)
    results = await run_testbed(tb, reverse=True, run_phase=native_phase)
    return tb, [(s.id, s.area, s.title, s.passed, list(s.checks)) for s in results]


async def run_driver() -> tuple[TestbedKernel, list]:
    tb = TestbedKernel(verbose=False)
    results = await run_testbed(tb, reverse=True)
    return tb, [(s.id, s.area, s.title, s.passed, list(s.checks)) for s in results]


async def main() -> int:
    verbose = "--verbose" in sys.argv
    print(f"{B}Running testbed on the testbed driver…{X}")
    t0 = time.time()
    drv_k, drv = await run_driver()
    t_drv = time.time() - t0
    print(f"{B}Running the SAME agents on native agent_os.Kernel().run()…{X}")
    t0 = time.time()
    nat_k, nat = await run_native(verbose)
    t_nat = time.time() - t0

    print(f"\n{B}{'═' * 96}\n SAME MULTI-AGENT SYSTEM, TWO RUNTIMES   (spawn order reversed)\n{'═' * 96}{X}")
    print(f"  {'ID':<4} {'Scenario':<58} {'Driver':<8} Native Kernel.run()")
    for (sid, area, title, dp, _), (_, _, _, np_, nchecks) in zip(drv, nat):
        dm = f"{G}PASS{X}" if dp else f"{R}FAIL{X}"
        nm = f"{G}PASS{X}" if np_ else f"{R}FAIL{X}"
        print(f"  {sid:<4} {title[:58]:<58} {dm}     {nm}")
        if not np_:
            for c in nchecks:
                if not c.ok:
                    print(f"         {D}✗ {c.desc}{('  — ' + c.evidence) if c.evidence else ''}{X}")

    dn, nn = sum(r[3] for r in drv), sum(r[3] for r in nat)
    print(f"\n{B}Driver{X}: {dn}/{len(drv)} scenarios in {t_drv:.1f}s | "
          f"{drv_k.tick} steps, {len(drv_k.deadlocks)} deadlocks resolved")
    print(f"{B}Native{X}: {nn}/{len(nat)} scenarios in {t_nat:.1f}s | "
          f"{nat_k.tick} steps, {len(nat_k.deadlocks)} deadlocks resolved")
    for i, (secs, outcome) in enumerate(nat_k.phase_outcomes, 1):
        print(f"        phase {i}: {outcome} ({secs}s)")
    live = [f"{p.name}:{p.state.value}" for p in await nat_k.pm.list()
            if p.state.value != "TERMINATED"]
    print(f"        processes NOT terminated at the end: {len(live)}")
    if live:
        print(f"        {D}{', '.join(live)}{X}")
    return 0 if nn >= dn else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
