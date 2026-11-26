"""
Orbital Research Lab — the full Agent-OS showcase, on the native kernel.

    python showcase_full/run.py                  # all missions, live log + scorecard
    python showcase_full/run.py --quiet          # scorecard only
    python showcase_full/run.py --only S12,S13   # selected scenarios
    python showcase_full/run.py --mission M1     # one mission
    python showcase_full/run.py --forward        # spawn in declaration order (default: reversed)

Exit code 0 = every scenario passed except the documented known bugs.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for p in (ROOT / "src", ROOT, HERE):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

from lab.harness import MISSIONS, SCENARIOS, MissionResult, run_mission  # noqa: E402
import lab.missions  # noqa: E402,F401  (registers missions + scenarios)

G, R, Y, D, B, X = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[1m", "\033[0m"


async def run_all(only: set[str] | None = None, missions: set[str] | None = None,
                  reverse: bool = True, verbose: bool = False) -> list[MissionResult]:
    results = []
    for mid, m in MISSIONS.items():
        if missions and mid not in missions:
            continue
        chosen = [s for s in SCENARIOS if s.mission == mid and (not only or s.id in only)]
        if chosen:
            results.append(await run_mission(m, chosen, reverse=reverse, verbose=verbose))
    return results


def outcome(s) -> str:
    if s.known_bug:
        return "XPASS" if s.passed else "KNOWN"
    return "PASS" if s.passed else "FAIL"


def report(results: list[MissionResult], elapsed: float) -> dict:
    print(f"\n{B}{'═' * 88}\n ORBITAL RESEARCH LAB — AGENT-OS FULL SHOWCASE (native agent_os.Kernel)\n{'═' * 88}{X}")
    rows, counts = [], {"PASS": 0, "FAIL": 0, "KNOWN": 0, "XPASS": 0}
    for r in results:
        k = r.ctx.k
        print(f"\n{B}{r.mission.id} · {r.mission.title}{X}  {D}{r.mission.story}{X}")
        print(f"   {D}{len(r.ctx.os.names)} agents, {k.steps_taken} steps, {len(r.ctx.deadlocks())} deadlocks, "
              f"{len(r.ctx.journal('failure'))} failures, {len(r.ctx.journal('restart'))} restarts, "
              f"{r.seconds:.1f}s, {len(r.live_after)} left alive{X}")
        for s in r.scenarios:
            o = outcome(s)
            counts[o] += 1
            color = {"PASS": G, "FAIL": R, "KNOWN": Y, "XPASS": Y}[o]
            print(f"  {color}{o:<5}{X} {s.id} {D}[{s.area}]{X} {s.title}")
            for c in s.checks:
                if o != "PASS" or not c.ok:
                    sym = f"{G}✓{X}" if c.ok else f"{R}✗{X}"
                    print(f"          {sym} {c.desc}" + (f"  {D}{c.evidence}{X}" if c.evidence else ""))
            if s.known_bug and o == "KNOWN":
                print(f"          {Y}↳ known Agent-OS bug: {s.known_bug}{X}")
            rows.append({"id": s.id, "mission": s.mission, "area": s.area, "title": s.title, "outcome": o,
                         "known_bug": s.known_bug,
                         "checks": [{"desc": c.desc, "ok": c.ok, "evidence": c.evidence} for c in s.checks]})
    total = sum(counts.values())
    print(f"\n{B}Summary{X}: {G}{counts['PASS']} passed{X}, {R}{counts['FAIL']} failed{X}, "
          f"{Y}{counts['KNOWN']} known bugs{X}" + (f", {Y}{counts['XPASS']} known bugs now FIXED{X}"
                                                   if counts["XPASS"] else "")
          + f"  —  {total} scenarios in {len(results)} missions, {elapsed:.1f}s")
    return {"elapsed_s": round(elapsed, 2), "counts": counts, "scenarios": rows}


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--only", help="comma-separated scenario ids, e.g. S12,S13")
    ap.add_argument("--mission", help="comma-separated mission ids, e.g. M1,M5")
    ap.add_argument("--forward", action="store_true", help="spawn in declaration order")
    ap.add_argument("--json", default=str(HERE / "last_report.json"))
    a = ap.parse_args()
    logging.basicConfig(level=logging.ERROR)
    t0 = time.time()
    results = await run_all(set(a.only.split(",")) if a.only else None,
                            set(a.mission.split(",")) if a.mission else None,
                            reverse=not a.forward, verbose=not a.quiet)
    data = report(results, time.time() - t0)
    Path(a.json).write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return 0 if data["counts"]["FAIL"] == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
