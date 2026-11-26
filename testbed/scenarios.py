"""
Scenario catalogue. Each scenario = setup (spawn agents, register operator hooks)
+ verify (assertions over process table, trace, evidence and events).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from agent_os.kernel.state_machine import InvalidStateTransition, ProcessState
from agent_os.metrics.events import EventType
from agent_os.resources.quota import ResourceLimits

from agents.ipc import Aggregator, Dispatcher, Flooder, Ghost, OrphanWaiter, SlowConsumer, Worker
from agents.lifecycle import BatchReport, Foreman, ReportWriter, RunawayCrawler
from agents.memory import Indexer, Librarian, PinHog
from agents.reliability import Crasher, HungAgent, LLMFlaky, MigrationJob
from agents.resources import InfiniteLooper, SlowPoke, TokenHog, ToolSpammer
from agents.scheduling import Commander, CPUHog, Janitor, Tenant
from agents.security import BuildBot, Contractor, Hacker, ToolUser
from agents.sync import (CacheReader, DoubleLocker, GPUJob, HighCritical, LowLogger,
                         MediumBatch, OrderedLocker, SloppyAgent)


@dataclass
class Check:
    desc: str
    ok: bool
    evidence: str = ""


@dataclass
class Scenario:
    id: str
    area: str
    title: str
    setup: Callable[..., Awaitable[None]]
    verify: Callable[..., Awaitable[list[Check]]]
    phase: int = 1
    checks: list[Check] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.ok for c in self.checks)


# ── helpers ──────────────────────────────────────────────────────────────────
async def state(k, name) -> str:
    return (await k.proc(name)).state.value


async def restarts(k, name) -> int:
    return (await k.proc(name)).restart_count


def ev(k, key, default=None):
    v = k.evidence.get(key)
    return v if v else default


def first_tick(k, name) -> int | None:
    return next((t for t, _, n, _ in k.trace if n == name), None)


def last_tick(k, name) -> int | None:
    ticks = [t for t, _, n, _ in k.trace if n == name]
    return ticks[-1] if ticks else None


def failures_of(k, name):
    return [f for f in k.failures if f["name"] == name]


SCENARIOS: list[Scenario] = []


def scenario(id, area, title, phase=1):
    def deco(cls):
        SCENARIOS.append(Scenario(id, area, title, cls.setup, cls.verify, phase))
        return cls
    return deco


# ═════════════════════════════ SCHEDULING ════════════════════════════════════
@scenario("S01", "Scheduling", "Preemptive priority: highest priority runs first")
class _:
    async def setup(k):
        await k.spawn(Commander(), name="Commander", priority=10)

    async def verify(k):
        first = k.trace[0][2] if k.trace else None
        return [Check("first process ever scheduled is Commander (prio 10)", first == "Commander", f"first={first}"),
                Check("Commander completed", await state(k, "Commander") == "TERMINATED")]


@scenario("S02", "Scheduling", "Starvation prevention via aging")
class _:
    async def setup(k):
        for i in (1, 2, 3):
            await k.spawn(CPUHog(), name=f"CPUHog-{i}", priority=7)
        await k.spawn(Janitor(), name="Janitor", priority=1)

    async def verify(k):
        jr = ev(k, "janitor_first_run", [{}])[0]
        hog_end = max(last_tick(k, f"CPUHog-{i}") or 0 for i in (1, 2, 3))
        j_first = first_tick(k, "Janitor")
        return [Check("Janitor (prio 1) ran before the prio-7 hogs finished",
                      j_first is not None and j_first < hog_end,
                      f"janitor tick {j_first} < last hog tick {hog_end}"),
                Check("it was scheduled while hogs were still runnable", jr.get("hogs_alive", 0) > 0,
                      f"waited {jr.get('waited')}s, {jr.get('hogs_alive')} hogs alive"),
                Check("Janitor completed", await state(k, "Janitor") == "TERMINATED")]


@scenario("S03", "Scheduling", "Weighted fair share (weights 1:2:4)", phase=2)
class _:
    async def setup(k):
        k.use_scheduler("weighted_fair")
        k.board["wfq_start_tick"] = k.tick
        for name, w in (("Tenant-A", 1), ("Tenant-B", 2), ("Tenant-C", 4)):
            await k.spawn(Tenant(), name=name, priority=5, weight=w)

    async def verify(k):
        start = k.board["wfq_start_tick"]
        window = [n for t, _, n, _ in k.trace if start <= t < start + 70]
        a, b, c = (window.count(f"Tenant-{x}") for x in "ABC")
        ratio_ok = a > 0 and 1.5 <= b / a <= 2.5 and 3.0 <= c / a <= 5.0
        if not ratio_ok:
            k.finding("wfq", "WeightedFairScheduler adds weight to every runnable process each pick "
                             "but only subtracts 1 from the winner, so deficits diverge and the "
                             f"heaviest tenant monopolises the CPU (first 70 picks A/B/C = {a}/{b}/{c}).")
        return [Check("CPU share in first 70 picks ≈ 1:2:4", ratio_ok, f"A={a} B={b} C={c}"),
                Check("all tenants eventually complete",
                      all([await state(k, f"Tenant-{x}") == "TERMINATED" for x in "ABC"]))]


# ═══════════════════════════════ IPC ═════════════════════════════════════════
@scenario("S04", "IPC", "Fan-out / fan-in with correlation IDs and WAITING(IPC)")
class _:
    async def setup(k):
        await k.spawn(Dispatcher(), name="Dispatcher", priority=4)
        for i in (1, 2, 3):
            await k.spawn(Worker(), name=f"Worker-{i}", priority=6)
        await k.spawn(Aggregator(), name="Aggregator", priority=5)

    async def verify(k):
        got = ev(k, "aggregated", [{}])[0]
        return [Check("workers parked in WAITING(IPC) before work arrived",
                      len(set(ev(k, "worker_waited", []))) == 3, f"{sorted(set(ev(k, 'worker_waited', [])))}"),
                Check("all 3 jobs delivered", ev(k, "dispatch", []) == ["DELIVERED"] * 3),
                Check("aggregator matched every correlation id", sorted(got) == ["job-1", "job-2", "job-3"], str(got)),
                Check("aggregator completed", await state(k, "Aggregator") == "TERMINATED")]


@scenario("S05", "IPC", "Backpressure: bounded mailbox (cap 3, REJECT)")
class _:
    async def setup(k):
        await k.spawn(Flooder(), name="Flooder", priority=6)
        await k.spawn(SlowConsumer(), name="SlowConsumer", priority=3)

    async def verify(k):
        flood = ev(k, "flood", [[]])[0]
        dropped = [e for e in await k.em.get_history()
                   if e.event_type == EventType.IPC_DROPPED and e.process_id == k.names["Flooder"]]
        return [Check("exactly 3 of 8 delivered, 5 rejected",
                      flood.count("DELIVERED") == 3 and flood.count("DROPPED") == 5, str(flood)),
                Check("5 IPC_DROPPED events in audit log", len(dropped) == 5, f"{len(dropped)} events"),
                Check("consumer drained exactly the 3 accepted", ev(k, "consumed", [None])[0] == 3)]


@scenario("S06", "IPC", "Dead letters + wait timeout when peer dies")
class _:
    async def setup(k):
        await k.spawn(Ghost(), name="Ghost", priority=8, restart="NEVER")
        await k.spawn(OrphanWaiter(), name="OrphanWaiter", priority=7)
        k.when("ghost dead", lambda: k.proc_now("Ghost").state in (ProcessState.TERMINATED, ProcessState.FAILED),
               lambda: k.board.__setitem__("ghost_dead", True))

    async def verify(k):
        return [Check("message to crashed peer is dropped, not queued forever",
                      ev(k, "to_dead_peer", [None])[0] == "DROPPED"),
                Check("message to non-existent PID 9999 is dropped", ev(k, "to_missing_pid", [None])[0] == "DROPPED"),
                Check("waiter woken by IPC deadline and exited cleanly",
                      ev(k, "orphan_gave_up") and await state(k, "OrphanWaiter") == "TERMINATED")]


# ═════════════════════════════ SYNCHRONISATION ═══════════════════════════════
@scenario("S07", "Deadlock", "Two-process deadlock (AB / BA lock ordering)")
class _:
    async def setup(k):
        await k.spawn(OrderedLocker("accounts", "audit-log", "pair", 2), name="Ledger", priority=6)
        await k.spawn(OrderedLocker("audit-log", "accounts", "pair", 2), name="Auditor", priority=5)

    async def verify(k):
        d = [x for x in k.deadlocks if set(x["cycle"]) == {"Ledger", "Auditor"}]
        return [Check("cycle Ledger ↔ Auditor detected", bool(d), str(d[0]["cycle"]) if d else "none"),
                Check("victim = lowest priority (Auditor, 5)", bool(d) and d[0]["victim"] == "Auditor"),
                Check("victim restarted by supervisor", await restarts(k, "Auditor") >= 1),
                Check("both eventually completed", sorted(ev(k, "pair_finished", [])) == ["Auditor", "Ledger"],
                      str(ev(k, "pair_finished", [])))]


@scenario("S08", "Deadlock", "Three-way circular wait (dining philosophers)")
class _:
    async def setup(k):
        for i, prio in ((0, 4), (1, 6), (2, 5)):
            await k.spawn(OrderedLocker(f"fork-{i}", f"fork-{(i + 1) % 3}", "ring", 3),
                          name=f"Philosopher-{i}", priority=prio)

    async def verify(k):
        d = [x for x in k.deadlocks if len(x["cycle"]) == 3]
        return [Check("3-node cycle detected", bool(d), " → ".join(d[0]["cycle"]) if d else "none"),
                Check("victim = Philosopher-0 (lowest prio 4)", bool(d) and d[0]["victim"] == "Philosopher-0"),
                Check("all philosophers ate", len(ev(k, "ring_finished", [])) == 3, str(ev(k, "ring_finished", [])))]


@scenario("S09", "Sync", "Priority inversion → priority inheritance")
class _:
    async def setup(k):
        await k.spawn(LowLogger(), name="LowLogger", priority=2)
        await k.spawn(HighCritical(), name="HighCritical", priority=9)
        await k.spawn(MediumBatch(), name="MediumBatch", priority=5)

    async def verify(k):
        inh = [x for x in ev(k, "inheritance", []) if x[0] == "LowLogger"]
        released_at = k.board.get("disk_released_at_medium_step")
        return [Check("LowLogger boosted 2 → 9 while blocking HighCritical", bool(inh) and inh[0][2] == 9, str(inh)),
                Check("ran at inherited priority while holding 'disk'",
                      ev(k, "low_prio_while_holding", [0])[0] == 9, str(ev(k, "low_prio_while_holding"))),
                Check("lock freed before MediumBatch (prio 5) could hog the CPU",
                      released_at is not None and released_at <= 3, f"after {released_at}/25 medium steps"),
                Check("priority restored after release", (await k.proc("LowLogger")).priority == 2)]


@scenario("S10", "Sync", "Counting semaphore: 4 GPU jobs, 2 slots")
class _:
    async def setup(k):
        k.sync.create_semaphore("gpu", 2)
        for i in range(1, 5):
            await k.spawn(GPUJob(), name=f"GPUJob-{i}", priority=5)

    async def verify(k):
        peak = max(ev(k, "sem_peak:gpu", [0]))
        return [Check("never more than 2 concurrent holders", peak == 2, f"peak={peak}"),
                Check("excess jobs BLOCKED on the semaphore", len(set(ev(k, "gpu_blocked", []))) >= 2,
                      str(sorted(set(ev(k, "gpu_blocked", []))))),
                Check("all 4 jobs completed",
                      all([await state(k, f"GPUJob-{i}") == "TERMINATED" for i in range(1, 5)]))]


@scenario("S11", "Sync", "Lock leak: agent exits holding a lock")
class _:
    async def setup(k):
        await k.spawn(SloppyAgent(), name="SloppyAgent", priority=6)
        await k.spawn(CacheReader(), name="CacheReader", priority=4)

    async def verify(k):
        leaks = [x for x in ev(k, "lock_leaks", []) if x[0] == "SloppyAgent"]
        return [Check("kernel detected the leaked 'cache' lock", bool(leaks), str(leaks)),
                Check("lock reclaimed and handed to the waiter", bool(ev(k, "cache_reader_got_lock")))]


@scenario("S12", "Sync", "Re-entrant lock attempt is rejected")
class _:
    async def setup(k):
        await k.spawn(DoubleLocker(), name="DoubleLocker", priority=6, restart="NEVER")

    async def verify(k):
        f = failures_of(k, "DoubleLocker")
        return [Check("LockError surfaced as process failure", bool(f) and "LockError" in f[0]["error"],
                      f[0]["error"] if f else ""),
                Check("lock 'config' freed after the crash", k.sync.get_lock("config").owner is None)]


# ═════════════════════════════ RESOURCES ═════════════════════════════════════
@scenario("S13", "Quotas", "Token budget (1000) enforced mid-call")
class _:
    async def setup(k):
        await k.spawn(TokenHog(), name="TokenHog", priority=6,
                      limits=ResourceLimits(token_limit=1000))

    async def verify(k):
        p = await k.proc("TokenHog")
        drift = p.resource_usage.total_tokens - 1000
        if drift > 0:
            k.finding("token_drift", f"Token quota is checked after the call is charged: TokenHog "
                                     f"overshot its 1000-token budget by {drift} tokens (one call).")
        return [Check("killed by RESOURCE_LIMIT, not restarted",
                      p.state == ProcessState.TERMINATED and p.restart_count == 0
                      and failures_of(k, "TokenHog")[0]["type"] == "RESOURCE_LIMIT"),
                Check("budget overshoot bounded by one call (≤400)", 0 <= drift <= 400,
                      f"used {p.resource_usage.total_tokens}/1000")]


@scenario("S14", "Quotas", "Step limit stops an infinite loop")
class _:
    async def setup(k):
        await k.spawn(InfiniteLooper(), name="InfiniteLooper", priority=3, limits=ResourceLimits(step_limit=15))

    async def verify(k):
        p = await k.proc("InfiniteLooper")
        return [Check("stopped at exactly 15 steps", p.resource_usage.steps == 15, f"steps={p.resource_usage.steps}"),
                Check("terminated", p.state == ProcessState.TERMINATED)]


@scenario("S15", "Quotas", "Tool-call limit")
class _:
    async def setup(k):
        await k.spawn(ToolSpammer(), name="ToolSpammer", priority=3, caps=["net.http"],
                      limits=ResourceLimits(tool_call_limit=5))

    async def verify(k):
        p = await k.proc("ToolSpammer")
        return [Check("pre-step quota check stops it at 5 calls (never a 6th)", p.resource_usage.tool_calls == 5
                      and p.state == ProcessState.TERMINATED, f"tool_calls={p.resource_usage.tool_calls}/5")]


@scenario("S16", "Quotas", "Wall-time limit")
class _:
    async def setup(k):
        await k.spawn(SlowPoke(), name="SlowPoke", priority=3, limits=ResourceLimits(wall_time_limit=0.6))

    async def verify(k):
        p = await k.proc("SlowPoke")
        return [Check("stopped after ~0.6s of execution time", p.state == ProcessState.TERMINATED
                      and 0.6 <= p.resource_usage.execution_time < 1.0,
                      f"{p.resource_usage.execution_time:.2f}s over {p.resource_usage.steps} steps")]


# ═════════════════════════════ RELIABILITY ═══════════════════════════════════
@scenario("S17", "Supervisor", "Restart policy NEVER")
class _:
    async def setup(k):
        await k.spawn(Crasher(fail_runs=99), name="CriticalService", priority=6, restart="NEVER")

    async def verify(k):
        return [Check("terminated after first crash, 0 restarts",
                      await state(k, "CriticalService") == "TERMINATED" and await restarts(k, "CriticalService") == 0)]


@scenario("S18", "Supervisor", "Restart policy ONCE")
class _:
    async def setup(k):
        await k.spawn(Crasher(fail_runs=99), name="OneShot", priority=6, restart="ONCE")

    async def verify(k):
        return [Check("restarted exactly once, then terminated",
                      await restarts(k, "OneShot") == 1 and len(failures_of(k, "OneShot")) == 2,
                      f"restarts={await restarts(k, 'OneShot')} failures={len(failures_of(k, 'OneShot'))}")]


@scenario("S19", "Supervisor", "N_TIMES: transient failure recovers")
class _:
    async def setup(k):
        await k.spawn(Crasher(fail_runs=2), name="FlakyNet", priority=6, restart="N_TIMES")

    async def verify(k):
        return [Check("2 crashes, then completed on 3rd run",
                      len(failures_of(k, "FlakyNet")) == 2 and await state(k, "FlakyNet") == "TERMINATED"
                      and not any("gave up" in l and "FlakyNet" in l for l in k.lines))]


@scenario("S20", "Supervisor", "Crash loop capped at max_restarts (3)")
class _:
    async def setup(k):
        await k.spawn(Crasher(fail_runs=99), name="CrashLoop", priority=6, restart="N_TIMES")

    async def verify(k):
        return [Check("supervisor gave up after 3 restarts (4 crashes)",
                      await restarts(k, "CrashLoop") == 3 and len(failures_of(k, "CrashLoop")) == 4,
                      f"restarts={await restarts(k, 'CrashLoop')}")]


@scenario("S21", "Supervisor", "Exponential backoff between restarts")
class _:
    async def setup(k):
        await k.spawn(Crasher(fail_runs=3), name="BackoffAgent", priority=6, restart="EXPONENTIAL_BACKOFF")

    async def verify(k):
        delays = k.restart_delays.get(k.names["BackoffAgent"], [])
        crashes = ev(k, "crash_at:BackoffAgent", [])
        starts = ev(k, "run_start:BackoffAgent", [])
        gaps = [round(starts[i + 1] - crashes[i], 2) for i in range(min(len(crashes), len(starts) - 1))]
        honoured = len(gaps) == 3 and all(g >= d * 0.95 for g, d in zip(gaps, delays))
        return [Check("delays double each time (0.15 → 0.3 → 0.6)", delays == [0.15, 0.3, 0.6], str(delays)),
                Check("agent really stayed asleep for each delay", honoured, f"observed gaps {gaps}"),
                Check("recovered on 4th run", await state(k, "BackoffAgent") == "TERMINATED"
                      and len(failures_of(k, "BackoffAgent")) == 3)]


@scenario("S22", "Supervisor", "Hung step killed by step timeout")
class _:
    async def setup(k):
        await k.spawn(HungAgent(), name="HungAgent", priority=6, restart="ONCE", step_timeout=0.4)

    async def verify(k):
        f = failures_of(k, "HungAgent")
        return [Check("timeout fired (not a 10s hang)", bool(f) and "timed out" in f[0]["error"],
                      f[0]["error"] if f else ""),
                Check("restarted and completed", await restarts(k, "HungAgent") == 1
                      and await state(k, "HungAgent") == "TERMINATED" and len(f) == 1)]


@scenario("S23", "Supervisor", "LLM provider outage → LLM_FAILURE → retry")
class _:
    async def setup(k):
        await k.spawn(LLMFlaky(), name="LLMFlaky", priority=6)

    async def verify(k):
        f = failures_of(k, "LLMFlaky")
        return [Check("failure classified LLM_FAILURE", bool(f) and f[0]["type"] == "LLM_FAILURE"),
                Check("succeeded after restart", bool(ev(k, "llm_recovered")))]


@scenario("S24", "Memory", "Checkpoint / restore: resume, don't redo")
class _:
    async def setup(k):
        await k.spawn(MigrationJob(), name="MigrationJob", priority=5)

    async def verify(k):
        batches = ev(k, "migration_batch", [])
        return [Check("resumed from checkpoint at batch 6", ev(k, "migration_resumed_from", [None])[0] == 6),
                Check("every batch processed exactly once", batches == list(range(10)), str(batches))]


# ═════════════════════════════ MEMORY ════════════════════════════════════════
@scenario("S25", "Memory", "LRU paging with pinned pages (8-page budget)")
class _:
    async def setup(k):
        await k.spawn(Librarian(), name="Librarian", priority=6)
        await k.spawn(Indexer(), name="Indexer", priority=5)

    async def verify(k):
        p0 = ev(k, "indexer_page0", [{}])[0]
        swaps = [e for e in await k.em.get_history()
                 if e.event_type == EventType.CONTEXT_SWAP_OUT and e.process_id == k.names["Indexer"]]
        return [Check("old pages swapped out under pressure", len(swaps) >= 4, f"{len(swaps)} swap-outs"),
                Check("page fault swaps page 0 back in, content intact",
                      p0.get("was_swapped_out") and p0.get("intact") and p0.get("loaded_now"), str(p0)),
                Check("pinned pages never evicted", ev(k, "pinned_survived", [[]])[0] == [True, True])]


@scenario("S26", "Memory", "Memory pressure: everything pinned")
class _:
    async def setup(k):
        await k.spawn(PinHog(), name="PinHog", priority=4)

    async def verify(k):
        loaded = ev(k, "pinhog_loaded", [0])[0]
        if loaded > k.cm.max_loaded_pages:
            k.finding("overcommit", f"ContextManager swallows MemoryPressureError: with all pages pinned "
                                    f"it over-commits ({loaded} loaded > budget {k.cm.max_loaded_pages}).")
        return [Check("kernel survived pin storm and agent completed", await state(k, "PinHog") == "TERMINATED"),
                Check("contexts freed when processes exit (no leak)", len(k.cm._contexts) == 0,
                      f"{len(k.cm._contexts)} contexts left")]


# ═════════════════════════════ SECURITY ══════════════════════════════════════
@scenario("S27", "Security", "Capability-gated tools + live revocation")
class _:
    async def setup(k):
        await k.spawn(ToolUser(["http_get", "db_write"]), name="Intern", priority=5, caps=["net.http"])
        await k.spawn(ToolUser(["db_read", "db_write"]), name="DBA", priority=5, caps=["db.read", "db.write"])
        c = await k.spawn(Contractor(), name="Contractor", priority=5, caps=["db.write"])
        k.when("revoke contractor", lambda: len(k.evidence["contractor_writes"]) >= 3,
               lambda: (k.caps.revoke(c.process_id, "db.write"), k.log("🔐 operator revoked db.write from Contractor")))

    async def verify(k):
        denied = dict(ev(k, "denied", []))
        return [Check("Intern denied db.write, killed without restart",
                      denied.get("Intern") == "db.write" and await restarts(k, "Intern") == 0),
                Check("DBA (has db.write) allowed", ev(k, "tool_ok:DBA", []) == ["db_read", "db_write"]),
                Check("Contractor cut off right after revocation",
                      denied.get("Contractor") == "db.write" and len(ev(k, "contractor_writes", [])) == 3,
                      f"{len(ev(k, 'contractor_writes', []))} writes before revocation")]


@scenario("S28", "Security", "Sandboxed execution + timeout + no-exec capability")
class _:
    async def setup(k):
        await k.spawn(BuildBot(), name="BuildBot", priority=5, caps=["sys.exec"])
        await k.spawn(Hacker(), name="Hacker", priority=5)

    async def verify(k):
        return [Check("sandbox ran subprocess and captured stdout", ev(k, "sandbox_stdout", [None])[0] == "42"),
                Check("runaway subprocess killed at 0.5s", ev(k, "sandbox_timeout", [False])[0] is True),
                Check("agent without sys.exec blocked", dict(ev(k, "denied", [])).get("Hacker") == "sys.exec")]


# ═════════════════════════════ LIFECYCLE ═════════════════════════════════════
@scenario("S29", "Lifecycle", "Operator pause / resume")
class _:
    async def setup(k):
        await k.spawn(BatchReport(), name="BatchReport", priority=4)

        def pred():
            p = k.proc_now("BatchReport")
            return p.resource_usage.steps >= 5 and p.state == ProcessState.READY

        async def do_pause():
            await k.pause("BatchReport")
            k.board["paused_t"] = time.time()

        async def do_resume():
            k.board["resumed_t"] = time.time()
            await k.resume("BatchReport")

        k.when("pause", pred, do_pause)
        k.when("resume", lambda: time.time() - k.board.get("paused_t", 1e18) >= 0.4, do_resume)

    async def verify(k):
        pt, rt = k.board.get("paused_t"), k.board.get("resumed_t")
        during = [t for t in ev(k, "batch_step_t", []) if pt and rt and pt < t < rt]
        return [Check("paused ≥0.4s with zero steps executed while paused",
                      pt is not None and rt is not None and not during, f"{len(during)} steps during pause"),
                Check("resumed and finished all 20 steps", len(ev(k, "batch_step_t", [])) == 20
                      and await state(k, "BatchReport") == "TERMINATED")]


@scenario("S30", "Lifecycle", "Cancel a runaway process; its lock is reclaimed")
class _:
    async def setup(k):
        await k.spawn(RunawayCrawler(), name="RunawayCrawler", priority=3)
        await k.spawn(ReportWriter(), name="ReportWriter", priority=4)
        k.when("cancel crawler", lambda: k.proc_now("RunawayCrawler").resource_usage.steps >= 8
               and k.proc_now("ReportWriter").state == ProcessState.BLOCKED,
               lambda: k.cancel("RunawayCrawler"))

    async def verify(k):
        return [Check("crawler cancelled", bool(ev(k, "cancelled"))
                      and await state(k, "RunawayCrawler") == "TERMINATED"),
                Check("blocked ReportWriter got 'crawl-db' and completed", bool(ev(k, "report_writer_got_lock")))]


@scenario("S31", "Lifecycle", "Process tree: child limit + orphan cascade")
class _:
    async def setup(k):
        await k.spawn(Foreman(), name="Foreman", priority=6, restart="NEVER",
                      limits=ResourceLimits(child_process_limit=3))

    async def verify(k):
        kids = ev(k, "children_spawned", [])
        return [Check("3 children spawned, 4th refused by kernel",
                      len(kids) == 3 and len(ev(k, "child_rejected", [])) == 1),
                Check("orphan policy terminated all children when Foreman died",
                      sorted(ev(k, "orphans_killed", [])) == sorted(kids) and
                      all([await state(k, c) == "TERMINATED" for c in kids]))]


@scenario("S32", "Kernel", "State machine rejects illegal transitions")
class _:
    async def setup(k):
        pass

    async def verify(k):
        from agents.scheduling import Tenant as Probe
        p = await k.spawn(Probe(1), name="Probe", priority=1)
        bad = []
        for target in (ProcessState.COMPLETED, ProcessState.FAILED, ProcessState.BLOCKED):
            try:
                await k.pm.set_state(p.process_id, target)
            except InvalidStateTransition:
                bad.append(target.value)
        await k._terminate(p, "probe done")
        return [Check("READY → COMPLETED / FAILED / BLOCKED all rejected", len(bad) == 3, str(bad)),
                Check("no process left behind in a live state",
                      not [x.name for x in await k.pm.list() if x.state.value not in ("TERMINATED",)])]
