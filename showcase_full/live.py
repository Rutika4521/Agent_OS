"""
Live dashboard mode for the Orbital Research Lab.

▶ Run Demo (POST /demo/run) calls `run_live()`. Every mission boots its own
native agent_os.Kernel exactly as `run.py` does, but:

  * all mission kernels share ONE EventManager, so the dashboard's event feed,
    scheduler timeline, IPC and deadlock views show the whole run;
  * each mission gets its own PID range (M1 = 1…, M2 = 1001…, …), so PIDs never
    collide and the process table accumulates all ~110 agents;
  * steps are paced (`pace` seconds apart) so states can be watched changing;
  * the REST routes are pointed at a `DashboardView` that spans every mission
    kernel: GET /processes lists them all, and cancel / pause / resume are
    dispatched to whichever kernel owns the PID.

The scorecard is published at GET /demo/report while the run progresses.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for p in (ROOT / "src", ROOT, HERE):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from agent_os.kernel.process_manager import ProcessNotFound  # noqa: E402
from agent_os.metrics.events import EventManager  # noqa: E402

from lab.harness import MISSIONS, SCENARIOS, run_mission  # noqa: E402
import lab.missions  # noqa: E402,F401

PID_STRIDE = 1000


class DashboardView:
    """ProcessManager- and Kernel-shaped facade over every mission kernel of a live run."""

    def __init__(self):
        self.kernels: list = []
        self.current = None

    def add(self, kernel) -> None:
        self.kernels.append(kernel)
        self.current = kernel

    @staticmethod
    def _pm(kernel):
        # Process tables stay readable after a mission's kernel has shut down.
        return kernel._process_manager

    def _owner(self, pid: int):
        for k in self.kernels:
            if pid in self._pm(k).process_table._processes:
                return k
        raise ProcessNotFound(f"Process {pid} not found")

    @property
    def process_table(self):
        return self._pm(self.current).process_table

    # ── ProcessManager surface used by the REST routes ───────────────────────
    async def list(self, state=None):
        out = []
        for k in self.kernels:
            out.extend(await self._pm(k).list(state=state))
        return out

    async def get(self, pid: int):
        return await self._pm(self._owner(pid)).get(pid)

    async def spawn(self, agent, **kw):
        return await self.current.spawn(agent, **kw)

    async def terminate(self, pid: int):
        await self._owner(pid).cancel(pid)

    async def remove(self, pid: int):
        return await self._pm(self._owner(pid)).remove(pid)

    # ── Kernel surface (operator actions) ────────────────────────────────────
    async def cancel(self, pid: int):
        await self._owner(pid).cancel(pid)

    async def pause(self, pid: int):
        await self._owner(pid).pause(pid)

    async def resume(self, pid: int):
        await self._owner(pid).resume(pid)


def _scorecard(done: list, running: str | None, started: float) -> dict:
    rows, counts = [], {"PASS": 0, "FAIL": 0, "KNOWN": 0, "XPASS": 0}
    for mission, scenarios, secs in done:
        for s in scenarios:
            o = ("XPASS" if s.passed else "KNOWN") if s.known_bug else ("PASS" if s.passed else "FAIL")
            counts[o] += 1
            rows.append({"id": s.id, "mission": mission.id, "mission_title": mission.title, "area": s.area,
                         "title": s.title, "outcome": o, "known_bug": s.known_bug,
                         "checks": [{"desc": c.desc, "ok": c.ok, "evidence": c.evidence} for c in s.checks]})
    return {
        "status": "running" if running else "done",
        "current_mission": running,
        "missions_done": [m.id for m, _, _ in done],
        "missions_total": len(MISSIONS),
        "scenarios_total": len(SCENARIOS),
        "elapsed_s": round(time.time() - started, 1),
        "counts": counts,
        "scenarios": rows,
    }


async def run_live(ks, *, pace: float = 0.02, publish=None) -> dict:
    """Run every mission against the live server. `ks` is routes._ks; `publish(report)`
    is called after each mission so GET /demo/report can show progress."""
    from agent_os.api import routes

    events = EventManager(max_history=500_000)
    view = DashboardView()
    started, done = time.time(), []

    def attach(kernel):
        view.add(kernel)
        routes.set_kernel_state(view, events, kernel.metrics, kernel.ipc, kernel=view)

    for i, (mid, m) in enumerate(MISSIONS.items()):
        chosen = [s for s in SCENARIOS if s.mission == mid]
        if publish:
            publish(_scorecard(done, f"{mid} · {m.title}", started))
        print(f"[Orbital Lab] ▶ mission {mid}: {m.title} ({len(chosen)} scenarios)", flush=True)
        r = await run_mission(m, chosen, pace=pace, on_boot=attach,
                              kernel_extra={"event_manager": events, "pid_base": 1 + i * PID_STRIDE})
        # M5's REST scenarios point the routes at their own kernel; restore the view.
        k = r.ctx.k   # already shut down: use its subsystems directly
        routes.set_kernel_state(view, events, k._metrics_collector, k._ipc_manager, kernel=view)
        done.append((m, r.scenarios, r.seconds))
        ok = sum(s.passed for s in r.scenarios)
        print(f"[Orbital Lab]   {ok}/{len(r.scenarios)} passed in {r.seconds:.1f}s", flush=True)

    report = _scorecard(done, None, started)
    if publish:
        publish(report)
    c = report["counts"]
    print(f"[Orbital Lab] ✔ done: {c['PASS']} passed, {c['FAIL']} failed, {c['KNOWN']} known bugs "
          f"in {report['elapsed_s']}s", flush=True)
    return report
