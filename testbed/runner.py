"""
Agent-OS Testbed — run every scenario and print a scorecard.

    python testbed/runner.py            # live log + scorecard
    python testbed/runner.py --quiet    # scorecard only
    python testbed/runner.py --only S07,S08

Exit code 0 = every check passed.
"""
from __future__ import annotations

import argparse
import asyncio
import json
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

from kernel import TestbedKernel  # noqa: E402
from scenarios import SCENARIOS, Check, Scenario  # noqa: E402

G, R, Y, D, B, X = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[1m", "\033[0m"


async def run_testbed(kernel: TestbedKernel, only: set[str] | None = None,
                      reverse: bool = False, run_phase=None) -> list[Scenario]:
    """reverse=True spawns scenarios in reverse order so PID order can't hide scheduling bugs.
    run_phase(kernel) overrides how a phase is executed (default: kernel.run())."""
    chosen = [s for s in SCENARIOS if not only or s.id in only]
    for s in chosen:
        s.checks = []
    for phase in sorted({s.phase for s in chosen}):
        group = [s for s in chosen if s.phase == phase]
        kernel.log(f"══ phase {phase}: {len(group)} scenarios ══")
        for s in (reversed(group) if reverse else group):
            await s.setup(kernel)
        await (run_phase(kernel) if run_phase else kernel.run())
    for s in chosen:
        try:
            s.checks = await s.verify(kernel)
        except Exception as e:  # noqa: BLE001
            s.checks = [Check("verify() raised", False, f"{type(e).__name__}: {e}")]
    return chosen


def report(kernel: TestbedKernel, results: list[Scenario], elapsed: float) -> dict:
    print(f"\n{B}{'═' * 78}\n AGENT-OS TESTBED SCORECARD\n{'═' * 78}{X}")
    area = None
    for s in results:
        if s.area != area:
            area = s.area
            print(f"\n{B}{area}{X}")
        mark = f"{G}PASS{X}" if s.passed else f"{R}FAIL{X}"
        print(f"  {mark}  {s.id}  {s.title}")
        for c in s.checks:
            sym = f"{G}✓{X}" if c.ok else f"{R}✗{X}"
            ev = f"  {D}{c.evidence}{X}" if c.evidence else ""
            print(f"        {sym} {c.desc}{ev}")

    total_checks = sum(len(s.checks) for s in results)
    ok_checks = sum(c.ok for s in results for c in s.checks)
    ok_scen = sum(s.passed for s in results)
    procs = len(kernel.names)
    print(f"\n{B}Summary{X}: {ok_scen}/{len(results)} scenarios, {ok_checks}/{total_checks} checks passed "
          f"| {procs} processes, {kernel.tick} scheduler ticks, {len(kernel.deadlocks)} deadlocks resolved, "
          f"{len(kernel.failures)} failures handled | {elapsed:.1f}s")

    if kernel.findings:
        print(f"\n{Y}{B}Kernel findings (behaviour worth fixing in src/agent_os){X}")
        for i, text in enumerate(kernel.findings.values(), 1):
            print(f"  {Y}{i}.{X} {text}")

    data = {
        "elapsed_s": round(elapsed, 2),
        "ticks": kernel.tick,
        "processes": procs,
        "deadlocks": kernel.deadlocks,
        "findings": list(kernel.findings.values()),
        "scenarios": [{"id": s.id, "area": s.area, "title": s.title, "passed": s.passed,
                       "checks": [{"desc": c.desc, "ok": c.ok, "evidence": c.evidence} for c in s.checks]}
                      for s in results],
    }
    return data


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--only", help="comma-separated scenario ids, e.g. S07,S08")
    ap.add_argument("--reverse", action="store_true", help="spawn scenarios in reverse order")
    ap.add_argument("--json", default=str(HERE / "last_report.json"))
    a = ap.parse_args()
    only = set(a.only.split(",")) if a.only else None
    kernel = TestbedKernel(verbose=not a.quiet)
    t0 = time.time()
    results = await run_testbed(kernel, only, reverse=a.reverse)
    data = report(kernel, results, time.time() - t0)
    Path(a.json).write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return 0 if all(s.passed for s in results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
