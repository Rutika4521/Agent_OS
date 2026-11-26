"""
Orbital Research Lab — missions and scenarios.

Each mission boots a fresh native `agent_os.Kernel` with its own Settings; all
of its scenarios share that kernel and run concurrently under Kernel.run().
A scenario may be marked `known_bug="..."` to document an open Agent-OS defect:
its checks state the *correct* behaviour and it reports KNOWN until fixed.
"""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

from agent_os.config.settings import Settings
from agent_os.kernel.state_machine import InvalidStateTransition, ProcessState
from agent_os.metrics.events import EventType
from agent_os.resources.quota import ResourceLimits

from .agents.archive import Editor, Indexer, Librarian, PinHog
from .agents.budget import ChattyPlanner, InfiniteLooper, SlowPoke, TokenHog, ToolSpammer
from .agents.command import Courteous, FlightDirector, NightJanitor, TelemetryCruncher, Tenant
from .agents.comms import (Aggregator, Analyst, BlockingProducer, Collator, DeadLetterProbe, Dispatcher,
                           Drainer, Flooder, Ghost, Lonely, NobodyHome, Pinger, Sequencer)
from .agents.operations import (BatchReport, Director, Foreman, Founder, MailWatcher, Recruiter,
                                ReportWriter, RunawayCrawler, Stargazer, Worker)
from .agents.platform import Archivist, Beacon, Hoarder, Metronome
from .agents.reliability import Crasher, HungAgent, LLMFlaky, LLMStalled, MigrationJob, Quitter
from .agents.security import BuildBot, Contractor, Intruder, Probe, SandboxUser, ToolUser
from .agents.vault import (CacheReader, CrewMember, DoubleLocker, Gatekeeper, GPUJob, HangarWaiter,
                           HighCritical, LowLogger, MediumBatch, OrderedLocker, SloppyAgent, Squatter)
from .harness import Check, Mission, mission, scenario


# ═════════════════════════════ SETTINGS ══════════════════════════════════════
def lab_settings() -> Settings:
    """Fast aging/backoff and a small page budget so edge cases trigger quickly."""
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
    s.system.max_processes = 150
    return s


def fair_settings() -> Settings:
    s = lab_settings()
    s.system.default_scheduler = "weighted_fair"
    return s


def lockdown_settings() -> Settings:
    s = lab_settings()
    s.sandbox.enabled = False
    s.security.default_capabilities = ["telemetry.read"]
    return s


def capacity_settings() -> Settings:
    s = lab_settings()
    s.system.max_processes = 6
    return s


LAB_KERNEL = dict(default_step_timeout=2.0, ipc_wait_timeout=1.0, stall_timeout=3.0)

mission(Mission("M1", "Main shift",
                "~70 agents across every department share one kernel: scheduling, IPC, deadlocks, "
                "quotas, crashes, memory, security and operator actions all at once.",
                lab_settings, kernel_kw=LAB_KERNEL))
mission(Mission("M2", "Fair-share hour", "Three tenants on the weighted_fair scheduler.",
                fair_settings, kernel_kw=LAB_KERNEL))
mission(Mission("M3", "Lockdown", "Sandbox disabled by config; every process gets default capabilities.",
                lockdown_settings, kernel_kw=LAB_KERNEL))
mission(Mission("M4", "Hiring freeze", "Global process limit of 6.", capacity_settings, kernel_kw=LAB_KERNEL))
mission(Mission("M5", "Control room", "An operator drives the live kernel through the REST API.",
                lab_settings, kernel_kw=dict(LAB_KERNEL, stall_timeout=1.0)))
mission(Mission("M6", "Radio silence", "Two agents wait for each other's mail with no IPC timeout.",
                lab_settings, kernel_kw=dict(default_step_timeout=2.0, ipc_wait_timeout=None, stall_timeout=0.5)))
mission(Mission("M7", "Overtime", "Run budget of 1 s against an agent that never finishes.",
                lab_settings, kernel_kw=LAB_KERNEL, run_kw=dict(max_seconds=1.0)))
mission(Mission("M8", "Step budget", "Run capped at 25 steps against an endless agent.",
                lab_settings, kernel_kw=LAB_KERNEL, run_kw=dict(max_steps=25)))
mission(Mission("M9", "SDK onboarding", "Plain Python classes registered with @agent_os.register.",
                lab_settings, kernel_kw=LAB_KERNEL))


# ═════════════════════════════ SCHEDULING ════════════════════════════════════
@scenario("S01", "M1", "Scheduling", "Preemptive priority: Flight Director (prio 10) runs first")
class _:
    async def setup(c):
        await c.spawn(FlightDirector(), name="FlightDirector", priority=10)

    async def verify(c):
        first = c.os.trace[0][2] if c.os.trace else None
        return [Check("very first step of the whole mission is FlightDirector", first == "FlightDirector",
                      f"first={first} among {len(c.os.names)} agents"),
                Check("FlightDirector completed", await c.state("FlightDirector") == "TERMINATED")]


@scenario("S02", "M1", "Scheduling", "Starvation prevention via aging")
class _:
    async def setup(c):
        for i in (1, 2, 3):
            await c.spawn(TelemetryCruncher(), name=f"Cruncher-{i}", priority=7)
        await c.spawn(NightJanitor(), name="NightJanitor", priority=1)

    async def verify(c):
        jr = c.ev("janitor_first_run", [{}])[0]
        hog_end = max(c.last_tick(f"Cruncher-{i}") or 0 for i in (1, 2, 3))
        j = c.first_tick("NightJanitor")
        return [Check("prio-1 janitor ran before the prio-7 crunchers finished", j is not None and j < hog_end,
                      f"janitor tick {j} < last cruncher tick {hog_end}"),
                Check("scheduled while crunchers were still runnable", jr.get("crunchers_alive", 0) > 0,
                      f"waited {jr.get('waited')}s with {jr.get('crunchers_alive')} crunchers alive"),
                Check("janitor completed", await c.state("NightJanitor") == "TERMINATED")]


@scenario("S03", "M1", "Scheduling", "YIELD keeps an agent runnable until it finishes")
class _:
    async def setup(c):
        await c.spawn(Courteous(5), name="Courteous", priority=4)

    async def verify(c):
        return [Check("yielded 5 times and completed", len(c.ev("yields", [])) == 5
                      and await c.state("Courteous") == "TERMINATED", f"{len(c.ev('yields', []))} steps")]


@scenario("S04", "M2", "Scheduling", "Weighted fair share (weights 1:2:4)")
class _:
    async def setup(c):
        for name, w in (("Tenant-A", 1), ("Tenant-B", 2), ("Tenant-C", 4)):
            await c.spawn(Tenant(), name=name, priority=5, weight=w)

    async def verify(c):
        window = [n for _, _, n, _ in c.os.trace[:70]]
        a, b, cc = (window.count(f"Tenant-{x}") for x in "ABC")
        ok = a > 0 and 1.5 <= b / a <= 2.5 and 3.0 <= cc / a <= 5.0
        return [Check("kernel booted with the weighted_fair scheduler", c.k.scheduler_name == "weighted_fair"),
                Check("CPU share in the first 70 picks ≈ 1:2:4", ok, f"A={a} B={b} C={cc}"),
                Check("all tenants complete", await c.all_terminated("Tenant-A", "Tenant-B", "Tenant-C"))]


# ═════════════════════════════════ IPC ═══════════════════════════════════════
@scenario("S05", "M1", "IPC", "Fan-out / fan-in with correlation IDs and WAITING(IPC)")
class _:
    async def setup(c):
        await c.spawn(Dispatcher(), name="Dispatcher", priority=4)
        for i in (1, 2, 3):
            await c.spawn(Analyst(), name=f"Analyst-{i}", priority=6)
        await c.spawn(Aggregator(), name="Aggregator", priority=5)

    async def verify(c):
        got = c.ev("aggregated", [{}])[0]
        waited = sorted(set(c.ev("analyst_waited", [])))
        return [Check("analysts parked in WAITING(IPC) before work arrived", len(waited) == 3, str(waited)),
                Check("all 3 jobs delivered", c.ev("dispatch", []) == ["DELIVERED"] * 3),
                Check("aggregator matched every correlation id", sorted(got) == ["job-1", "job-2", "job-3"], str(got)),
                Check("aggregator completed", await c.state("Aggregator") == "TERMINATED")]


@scenario("S06", "M1", "IPC", "Overflow policy REJECT: 8-message burst into a capacity-3 mailbox")
class _:
    async def setup(c):
        await c.spawn(Flooder("reject", "RejectReader"), name="RejectFlooder", priority=6)
        await c.spawn(Drainer("reject"), name="RejectReader", priority=3)

    async def verify(c):
        st = c.ev("flood:reject", [[]])[0]
        dropped = [e for e in await c.events(EventType.IPC_DROPPED, "RejectFlooder")]
        return [Check("3 delivered, 5 rejected", st.count("DELIVERED") == 3 and st.count("DROPPED") == 5, str(st)),
                Check("5 IPC_DROPPED events in the audit log", len(dropped) == 5, f"{len(dropped)} events"),
                Check("reader got the 3 oldest (0,1,2)", c.ev("drained:reject", [None])[0] == [0, 1, 2],
                      str(c.ev("drained:reject")))]


@scenario("S07", "M1", "IPC", "Overflow policy DROP: oldest messages evicted, newest kept")
class _:
    async def setup(c):
        await c.spawn(Flooder("drop", "DropReader"), name="DropFlooder", priority=6)
        await c.spawn(Drainer("drop"), name="DropReader", priority=3)

    async def verify(c):
        st = c.ev("flood:drop", [[]])[0]
        return [Check("every send accepted (DROP never rejects the sender)", st == ["DELIVERED"] * 8, str(st)),
                Check("reader got only the 3 newest (5,6,7)", c.ev("drained:drop", [None])[0] == [5, 6, 7],
                      str(c.ev("drained:drop")))]


@scenario("S08", "M1", "IPC", "Overflow policy BLOCK: a full mailbox blocks the sender; step timeout rescues it")
class _:
    async def setup(c):
        await c.spawn(BlockingProducer(), name="BlockingProducer", priority=5, restart="NEVER", step_timeout=0.3)
        await c.spawn(NobodyHome(), name="NobodyHome", priority=2)
        c.when("producer dead", lambda: c.os.proc_now("BlockingProducer").state == ProcessState.TERMINATED,
               lambda: c.board.__setitem__("producer_dead", True))

    async def verify(c):
        f = c.failures("BlockingProducer")
        return [Check("2 messages fit, the 3rd send blocked inside the step", c.ev("block_sent", []) == [0, 1, 2]),
                Check("kernel step timeout ended it (TOOL_TIMEOUT), the loop never froze",
                      bool(f) and f[0]["type"] == "TOOL_TIMEOUT", f[0]["error"] if f else "no failure")]


@scenario("S09", "M1", "IPC", "Per-sender FIFO ordering with sequence numbers")
class _:
    async def setup(c):
        await c.spawn(Sequencer(), name="Sequencer-A", priority=5)
        await c.spawn(Sequencer(), name="Sequencer-B", priority=5)
        await c.spawn(Collator(), name="Collator", priority=4)

    async def verify(c):
        got = c.ev("collated", [[]])[0]
        per = {s: [(q, n) for f, q, n in got if f == s] for s in ("Sequencer-A", "Sequencer-B")}
        ok = all([q for q, _ in v] == list(range(5)) and [n for _, n in v] == list(range(5)) for v in per.values())
        return [Check("all 10 messages arrived", len(got) == 10, f"{len(got)}"),
                Check("each sender's messages in order, channel sequence numbers 0..4", ok, str(per))]


@scenario("S10", "M1", "IPC", "Peer crashes: waiter is woken by the IPC deadline")
class _:
    async def setup(c):
        await c.spawn(Ghost(), name="Ghost", priority=8, restart="NEVER")
        await c.spawn(Pinger(), name="Pinger", priority=7)
        c.when("ghost dead", lambda: c.os.proc_now("Ghost").state == ProcessState.TERMINATED,
               lambda: c.board.__setitem__("ghost_dead", True))

    async def verify(c):
        return [Check("kernel woke the waiter with ipc_timed_out", bool(c.journal("ipc_timeout", "Pinger"))),
                Check("waiter degraded gracefully and completed",
                      bool(c.ev("pinger_gave_up")) and await c.state("Pinger") == "TERMINATED")]


@scenario("S11", "M1", "IPC", "Dead letters: mail to a dead or missing PID is refused")
class _:
    async def setup(c):
        await c.spawn(DeadLetterProbe(), name="DeadLetterProbe", priority=6)

    async def verify(c):
        return [Check("mail to the terminated Ghost is refused", c.ev("to_dead_peer", [None])[0] == "DROPPED",
                      f"status={c.ev('to_dead_peer', [None])[0]}"),
                Check("mail to PID 9999 is refused", c.ev("to_missing_pid", [None])[0] == "DROPPED",
                      f"status={c.ev('to_missing_pid', [None])[0]}")]


# ═══════════════════════════ DEADLOCK / SYNC ═════════════════════════════════
@scenario("S12", "M1", "Deadlock", "Two-agent lock deadlock (AB / BA ordering)")
class _:
    async def setup(c):
        await c.spawn(OrderedLocker("accounts", "audit-log", "pair", 2), name="Ledger", priority=6)
        await c.spawn(OrderedLocker("audit-log", "accounts", "pair", 2), name="Auditor", priority=5)

    async def verify(c):
        d = [x for x in c.deadlocks() if set(x["names"]) == {"Ledger", "Auditor"}]
        return [Check("cycle Ledger ↔ Auditor detected", bool(d), str(d[0]["names"]) if d else "none"),
                Check("victim = lowest priority (Auditor)", bool(d) and d[0]["victim_name"] == "Auditor"),
                Check("victim restarted by the supervisor", await c.restarts("Auditor") >= 1),
                Check("both completed", sorted(c.ev("pair_finished", [])) == ["Auditor", "Ledger"])]


@scenario("S13", "M1", "Deadlock", "Three-way circular wait (dining philosophers)")
class _:
    async def setup(c):
        for i, prio in ((0, 4), (1, 6), (2, 5)):
            await c.spawn(OrderedLocker(f"fork-{i}", f"fork-{(i + 1) % 3}", "ring", 3),
                          name=f"Philosopher-{i}", priority=prio)

    async def verify(c):
        d = [x for x in c.deadlocks() if len(x["cycle"]) == 3]
        return [Check("3-node cycle detected", bool(d), " → ".join(d[0]["names"]) if d else "none"),
                Check("victim = Philosopher-0 (prio 4)", bool(d) and d[0]["victim_name"] == "Philosopher-0"),
                Check("all philosophers ate", len(c.ev("ring_finished", [])) == 3)]


@scenario("S14", "M1", "Deadlock", "Semaphore deadlock (two 1-slot valves, crossed order)")
class _:
    async def setup(c):
        await c.spawn(OrderedLocker("valve-1", "valve-2", "valves", 2, kind="sem"), name="Engineer-A", priority=5)
        await c.spawn(OrderedLocker("valve-2", "valve-1", "valves", 2, kind="sem"), name="Engineer-B", priority=4)

    async def verify(c):
        d = [x for x in c.deadlocks() if set(x["names"]) == {"Engineer-A", "Engineer-B"}]
        return [Check("cycle through semaphores detected", bool(d), str(d[0]["waiting_on"]) if d else "none"),
                Check("victim Engineer-B (prio 4) restarted", bool(d) and d[0]["victim_name"] == "Engineer-B"
                      and await c.restarts("Engineer-B") >= 1),
                Check("both completed", sorted(c.ev("valves_finished", [])) == ["Engineer-A", "Engineer-B"])]


@scenario("S15", "M1", "Deadlock", "Deadlock victim with restart NEVER is terminated, locks reclaimed")
class _:
    async def setup(c):
        await c.spawn(OrderedLocker("hatch-a", "hatch-b", "duel", 2), name="Pilot", priority=6)
        await c.spawn(OrderedLocker("hatch-b", "hatch-a", "duel", 2), name="Cadet", priority=3, restart="NEVER")

    async def verify(c):
        d = [x for x in c.deadlocks() if set(x["names"]) == {"Pilot", "Cadet"}]
        return [Check("Cadet chosen as victim", bool(d) and d[0]["victim_name"] == "Cadet"),
                Check("Cadet not restarted, terminated", await c.restarts("Cadet") == 0
                      and bool(c.journal("gave_up", "Cadet"))),
                Check("Cadet's hatch reclaimed; Pilot completed", c.ev("duel_finished", []) == ["Pilot"]
                      and any(r["lock"] == "hatch-b" for r in c.journal("reclaim", "Cadet")))]


@scenario("S16", "M1", "Sync", "Priority inversion → priority inheritance")
class _:
    async def setup(c):
        await c.spawn(LowLogger(), name="LowLogger", priority=2)
        await c.spawn(HighCritical(), name="HighCritical", priority=9)
        await c.spawn(MediumBatch(), name="MediumBatch", priority=5)

    async def verify(c):
        inh = c.journal("inherit", "LowLogger")
        released = c.board.get("disk_released_at_medium_step")
        return [Check("kernel boosted LowLogger 2 → 9", bool(inh) and inh[0]["new"] == 9,
                      str([(i["old"], i["new"]) for i in inh])),
                Check("LowLogger ran at priority 9 while holding 'disk'",
                      c.ev("low_prio_while_holding", [0])[0] == 9, str(c.ev("low_prio_while_holding"))),
                Check("'disk' freed before MediumBatch could hog the CPU", released is not None and released <= 3,
                      f"after {released}/25 medium steps"),
                Check("priority restored to 2", (await c.proc("LowLogger")).priority == 2)]


@scenario("S17", "M1", "Sync", "Counting semaphore: 4 GPU jobs, 2 slots")
class _:
    async def setup(c):
        for i in range(1, 5):
            await c.spawn(GPUJob(), name=f"GPUJob-{i}", priority=5)

    async def verify(c):
        peak = max(c.ev("sem_peak:gpu", [0]))
        return [Check("never more than 2 holders", peak == 2, f"peak={peak}"),
                Check("extra jobs BLOCKED on the semaphore", len(set(c.ev("gpu_blocked", []))) >= 2),
                Check("all 4 completed", await c.all_terminated(*(f"GPUJob-{i}" for i in range(1, 5))))]


@scenario("S18", "M1", "Sync", "Lock hand-off is FIFO, not by priority")
class _:
    async def setup(c):
        await c.spawn(Gatekeeper(), name="Gatekeeper", priority=5)
        for i, prio in ((1, 3), (2, 6), (3, 8)):
            await c.spawn(CrewMember(i), name=f"Crew-{i}", priority=prio)

    async def verify(c):
        order = c.ev("airlock_order", [])
        queue = [c.k.pm.process_table._processes[pid].name for pid in c.ev("airlock_queue", [[]])[0]]
        return [Check("queue formed as Crew-1, Crew-2, Crew-3 (priorities 3, 6, 8)",
                      queue == ["Crew-1", "Crew-2", "Crew-3"], str(queue)),
                Check("hand-off followed the queue (FIFO), not priority (which would be 3, 2, 1)",
                      order == queue, str(order))]


@scenario("S19", "M1", "Sync", "Lock leak: agent exits holding a lock")
class _:
    async def setup(c):
        await c.spawn(SloppyAgent(), name="SloppyAgent", priority=6)
        await c.spawn(CacheReader(), name="CacheReader", priority=4)

    async def verify(c):
        leak = c.journal("leak", "SloppyAgent")
        return [Check("kernel detected the leaked 'cache' lock", bool(leak) and leak[0]["locks"] == ["cache"]),
                Check("lock reclaimed and handed to the waiter", bool(c.ev("cache_reader_got_lock")))]


@scenario("S20", "M1", "Sync", "Re-entrant lock attempt is rejected")
class _:
    async def setup(c):
        await c.spawn(DoubleLocker(), name="DoubleLocker", priority=6, restart="NEVER")

    async def verify(c):
        f = c.failures("DoubleLocker")
        return [Check("LockError surfaced as a process failure", bool(f) and "LockError" in f[0]["error"],
                      f[0]["error"] if f else ""),
                Check("'config' freed after the crash", c.k.sync.get_lock("config").owner is None)]


@scenario("S21", "M1", "Sync", "Cancelling a BLOCKED waiter removes it from the lock queue")
class _:
    async def setup(c):
        await c.spawn(Squatter(), name="Squatter", priority=4)
        await c.spawn(HangarWaiter(), name="Waiter-A", priority=5)
        await c.spawn(HangarWaiter(delay=0.05), name="Waiter-B", priority=5)

        async def cancel_a():
            await c.k.cancel(c.os.pid("Waiter-A"))
            c.board["quitter_cancelled"] = True

        c.when("cancel blocked Waiter-A",
               lambda: c.os.proc_now("Waiter-A").state == ProcessState.BLOCKED
               and c.os.proc_now("Waiter-B").state == ProcessState.BLOCKED, cancel_a)

    async def verify(c):
        return [Check("Waiter-A was cancelled while BLOCKED", bool(c.journal("cancel", "Waiter-A"))
                      and "Waiter-A" in c.ev("hangar_blocked", [])),
                Check("hand-off skipped the cancelled waiter: Waiter-B got the hangar",
                      c.ev("hangar_got", []) == ["Waiter-B"], str(c.ev("hangar_got"))),
                Check("lock free at the end", c.k.sync.get_lock("hangar").owner is None)]


# ═════════════════════════════════ QUOTAS ════════════════════════════════════
@scenario("S22", "M1", "Quotas", "Token budget (1000) enforced mid-call")
class _:
    async def setup(c):
        await c.spawn(TokenHog(), name="TokenHog", priority=6, limits=ResourceLimits(token_limit=1000))

    async def verify(c):
        p = await c.proc("TokenHog")
        f = c.failures("TokenHog")
        drift = p.resource_usage.total_tokens - 1000
        return [Check("killed with RESOURCE_LIMIT, never restarted", p.state == ProcessState.TERMINATED
                      and p.restart_count == 0 and bool(f) and f[0]["type"] == "RESOURCE_LIMIT"),
                Check("overshoot bounded by one call (kernel charges then checks)", 0 <= drift <= 300,
                      f"used {p.resource_usage.total_tokens}/1000")]


@scenario("S23", "M1", "Quotas", "LLM-call limit")
class _:
    async def setup(c):
        await c.spawn(ChattyPlanner(), name="ChattyPlanner", priority=3, limits=ResourceLimits(llm_call_limit=4))

    async def verify(c):
        p = await c.proc("ChattyPlanner")
        return [Check("stopped at 4 LLM calls", p.resource_usage.llm_calls == 4
                      and p.state == ProcessState.TERMINATED, f"llm_calls={p.resource_usage.llm_calls}")]


@scenario("S24", "M1", "Quotas", "Step limit stops an infinite loop")
class _:
    async def setup(c):
        await c.spawn(InfiniteLooper(), name="InfiniteLooper", priority=3, limits=ResourceLimits(step_limit=15))

    async def verify(c):
        p = await c.proc("InfiniteLooper")
        q = c.journal("quota", "InfiniteLooper")
        return [Check("stopped at exactly 15 steps", p.resource_usage.steps == 15, f"steps={p.resource_usage.steps}"),
                Check("quota kill recorded", bool(q) and q[0]["reason"].startswith("step_limit"))]


@scenario("S25", "M1", "Quotas", "Tool-call limit")
class _:
    async def setup(c):
        await c.spawn(ToolSpammer(), name="ToolSpammer", priority=3, caps=["net.http"],
                      limits=ResourceLimits(tool_call_limit=5))

    async def verify(c):
        p = await c.proc("ToolSpammer")
        return [Check("pre-step check stops it at 5 calls", p.resource_usage.tool_calls == 5
                      and p.state == ProcessState.TERMINATED, f"tool_calls={p.resource_usage.tool_calls}")]


@scenario("S26", "M1", "Quotas", "Wall-time limit")
class _:
    async def setup(c):
        await c.spawn(SlowPoke(), name="SlowPoke", priority=3, limits=ResourceLimits(wall_time_limit=0.6))

    async def verify(c):
        p = await c.proc("SlowPoke")
        t = p.resource_usage.execution_time
        return [Check("stopped after ~0.6 s of execution", p.state == ProcessState.TERMINATED and 0.6 <= t < 1.0,
                      f"{t:.2f}s over {p.resource_usage.steps} steps")]


# ═══════════════════════════════ SUPERVISOR ══════════════════════════════════
@scenario("S27", "M1", "Supervisor", "Restart policy NEVER")
class _:
    async def setup(c):
        await c.spawn(Crasher(99), name="CriticalService", priority=6, restart="NEVER")

    async def verify(c):
        return [Check("terminated after the first crash, 0 restarts",
                      await c.state("CriticalService") == "TERMINATED" and await c.restarts("CriticalService") == 0)]


@scenario("S28", "M1", "Supervisor", "Restart policy ONCE")
class _:
    async def setup(c):
        await c.spawn(Crasher(99), name="OneShot", priority=6, restart="ONCE")

    async def verify(c):
        n = len(c.failures("OneShot"))
        return [Check("restarted exactly once, then terminated", await c.restarts("OneShot") == 1 and n == 2,
                      f"failures={n}")]


@scenario("S29", "M1", "Supervisor", "N_TIMES: transient failure recovers")
class _:
    async def setup(c):
        await c.spawn(Crasher(2), name="FlakyLink", priority=6, restart="N_TIMES")

    async def verify(c):
        return [Check("2 crashes, completed on the 3rd run", len(c.failures("FlakyLink")) == 2
                      and bool(c.journal("completed", "FlakyLink")))]


@scenario("S30", "M1", "Supervisor", "Crash loop capped at max_restarts (3)")
class _:
    async def setup(c):
        await c.spawn(Crasher(99), name="CrashLoop", priority=6, restart="N_TIMES")

    async def verify(c):
        return [Check("gave up after 3 restarts (4 crashes)", await c.restarts("CrashLoop") == 3
                      and len(c.failures("CrashLoop")) == 4 and bool(c.journal("gave_up", "CrashLoop")))]


@scenario("S31", "M1", "Supervisor", "Exponential backoff is applied between restarts")
class _:
    async def setup(c):
        await c.spawn(Crasher(3), name="BackoffAgent", priority=6, restart="EXPONENTIAL_BACKOFF")

    async def verify(c):
        delays = [b["delay"] for b in c.journal("backoff", "BackoffAgent")]
        crashes, starts = c.ev("crash_at:BackoffAgent", []), c.ev("run_start:BackoffAgent", [])
        gaps = [round(starts[i + 1] - crashes[i], 2) for i in range(min(len(crashes), len(starts) - 1))]
        return [Check("delays double: 0.15 → 0.3 → 0.6", delays == [0.15, 0.3, 0.6], str(delays)),
                Check("agent really stayed asleep for each delay",
                      len(gaps) == 3 and all(g >= d * 0.95 for g, d in zip(gaps, delays)), f"gaps {gaps}"),
                Check("recovered on the 4th run", bool(c.journal("completed", "BackoffAgent")))]


@scenario("S32", "M1", "Supervisor", "Hung step killed by the step timeout")
class _:
    async def setup(c):
        await c.spawn(HungAgent(), name="HungAgent", priority=6, restart="ONCE", step_timeout=0.4)

    async def verify(c):
        f = c.failures("HungAgent")
        return [Check("timeout fired (TOOL_TIMEOUT), not a 10 s hang", bool(f) and f[0]["type"] == "TOOL_TIMEOUT",
                      f[0]["error"] if f else ""),
                Check("restarted and completed", await c.restarts("HungAgent") == 1
                      and bool(c.journal("completed", "HungAgent")))]


@scenario("S33", "M1", "Supervisor", "LLM provider outage → LLM_FAILURE → retry")
class _:
    async def setup(c):
        await c.spawn(LLMFlaky(), name="LLMFlaky", priority=6)

    async def verify(c):
        f = c.failures("LLMFlaky")
        return [Check("classified LLM_FAILURE", bool(f) and f[0]["type"] == "LLM_FAILURE"),
                Check("succeeded after restart", bool(c.ev("llm_recovered")))]


@scenario("S34", "M1", "Supervisor", "LLM provider timeout → LLM_TIMEOUT → retry")
class _:
    async def setup(c):
        await c.spawn(LLMStalled(), name="LLMStalled", priority=6)

    async def verify(c):
        f = c.failures("LLMStalled")
        return [Check("classified LLM_TIMEOUT", bool(f) and f[0]["type"] == "LLM_TIMEOUT",
                      f[0]["type"] if f else ""),
                Check("succeeded after restart", bool(c.ev("llm_timeout_recovered")))]


@scenario("S35", "M1", "Supervisor", "Agent returns StepStatus.FAILED (no exception)")
class _:
    async def setup(c):
        await c.spawn(Quitter(), name="Quitter", priority=6)

    async def verify(c):
        f = c.failures("Quitter")
        return [Check("returned FAILED handled like a crash", bool(f) and "calibration" in f[0]["error"]),
                Check("restarted and completed", await c.restarts("Quitter") == 1
                      and bool(c.journal("completed", "Quitter")))]


# ═════════════════════════════════ MEMORY ════════════════════════════════════
@scenario("S36", "M1", "Memory", "Checkpoint / restore: resume, don't redo")
class _:
    async def setup(c):
        await c.spawn(MigrationJob(), name="MigrationJob", priority=5)

    async def verify(c):
        batches = c.ev("migration_batch", [])
        return [Check("resumed from the checkpoint at batch 6", c.ev("migration_resumed_from", [None])[0] == 6),
                Check("every batch processed exactly once", batches == list(range(10)), str(batches))]


@scenario("S37", "M1", "Memory", "LRU paging with pinned pages (8-page budget)")
class _:
    async def setup(c):
        await c.spawn(Librarian(), name="Librarian", priority=6)
        await c.spawn(Indexer(), name="Indexer", priority=5)

    async def verify(c):
        p0 = c.ev("indexer_page0", [{}])[0]
        swaps = await c.events(EventType.CONTEXT_SWAP_OUT, "Indexer")
        return [Check("old pages swapped out under pressure", len(swaps) >= 4, f"{len(swaps)} swap-outs"),
                Check("page fault swaps page 0 back in, content intact",
                      bool(p0.get("was_swapped_out") and p0.get("intact") and p0.get("loaded_now")), str(p0)),
                Check("pinned pages never evicted", c.ev("pinned_survived", [[]])[0] == [True, True])]


@scenario("S38", "M1", "Memory", "Page updates bump versions")
class _:
    async def setup(c):
        await c.spawn(Editor(), name="Editor", priority=4)

    async def verify(c):
        return [Check("versions 2,3,4 after three updates", c.ev("editor_versions", [None])[0] == [2, 3, 4],
                      str(c.ev("editor_versions"))),
                Check("latest content readable", c.ev("editor_content", [None])[0] == "draft v4")]


@scenario("S39", "M1", "Memory", "Pin storm: kernel survives; every context freed at exit")
class _:
    async def setup(c):
        await c.spawn(PinHog(), name="PinHog", priority=4)

    async def verify(c):
        loaded = c.ev("pinhog_loaded", [0])[0]
        return [Check("agent completed despite pinning past the budget", await c.state("PinHog") == "TERMINATED",
                      f"{loaded} pages loaded vs budget {c.k.contexts.max_loaded_pages} (over-commit, no crash)"),
                Check("no memory context leaked once all agents exited", len(c.k.contexts._contexts) == 0,
                      f"{len(c.k.contexts._contexts)} contexts left")]


# ════════════════════════════════ SECURITY ═══════════════════════════════════
@scenario("S40", "M1", "Security", "Capability-gated tools + live revocation")
class _:
    async def setup(c):
        await c.spawn(ToolUser(["web_search", "db_write"]), name="Intern", priority=5, caps=["net.http"])
        await c.spawn(ToolUser(["db_read", "db_write"]), name="DBA", priority=5, caps=["db.read", "db.write"])
        await c.spawn(Contractor(), name="Contractor", priority=5, caps=["db.write"])
        c.when("revoke contractor", lambda: len(c.os.evidence["contractor_writes"]) >= 3,
               lambda: c.k.capabilities.revoke(c.os.pid("Contractor"), "db.write"))

    async def verify(c):
        intern, contractor = c.failures("Intern"), c.failures("Contractor")
        return [Check("Intern denied db.write (TOOL_FAILURE), not restarted",
                      bool(intern) and "db.write" in intern[0]["error"] and await c.restarts("Intern") == 0),
                Check("DBA allowed", c.ev("tool_ok:DBA", []) == ["db_read", "db_write"]),
                Check("Contractor cut off right after revocation",
                      bool(contractor) and len(c.ev("contractor_writes", [])) == 3,
                      f"{len(c.ev('contractor_writes', []))} writes before revocation")]


@scenario("S41", "M1", "Security", "Sandboxed execution, runaway subprocess, missing sys.exec")
class _:
    async def setup(c):
        await c.spawn(BuildBot(), name="BuildBot", priority=5, caps=["sys.exec"])
        await c.spawn(Intruder(), name="Intruder", priority=5)

    async def verify(c):
        f = c.failures("Intruder")
        return [Check("subprocess ran, stdout captured", c.ev("sandbox_stdout", [None])[0] == "42"),
                Check("runaway subprocess killed at 0.5 s", c.ev("sandbox_timeout", [None])[0] == "SandboxTimeout"),
                Check("agent without sys.exec denied", bool(f) and "sys.exec" in f[0]["error"])]


@scenario("S42", "M3", "Security", "Default capabilities from config")
class _:
    async def setup(c):
        await c.spawn(Probe("telemetry_read"), name="Inheritor", priority=5)           # caps=None → defaults
        await c.spawn(Probe("telemetry_read"), name="Specialist", priority=5, caps=["net.http"])

    async def verify(c):
        return [Check("process spawned without caps inherits the defaults",
                      c.ev("caps:Inheritor", [None])[0] == ["telemetry.read"]
                      and c.ev("tool_ok:Inheritor", []) == ["telemetry_read"]),
                Check("explicit caps replace the defaults → denied",
                      c.ev("caps:Specialist", [None])[0] == ["net.http"] and bool(c.failures("Specialist")))]


@scenario("S43", "M3", "Security", "Sandbox disabled by config → SANDBOX_FAILURE")
class _:
    async def setup(c):
        await c.spawn(SandboxUser(), name="SandboxUser", priority=5, caps=["sys.exec"], restart="NEVER")

    async def verify(c):
        f = c.failures("SandboxUser")
        return [Check("classified SANDBOX_FAILURE", bool(f) and f[0]["type"] == "SANDBOX_FAILURE",
                      f[0]["error"] if f else "")]


# ════════════════════════════════ LIFECYCLE ══════════════════════════════════
@scenario("S44", "M1", "Lifecycle", "Operator pause / resume")
class _:
    async def setup(c):
        await c.spawn(BatchReport(), name="BatchReport", priority=4)

        async def pause():
            await c.k.pause(c.os.pid("BatchReport"))
            c.board["paused_t"] = time.time()

        async def resume():
            c.board["resumed_t"] = time.time()
            await c.k.resume(c.os.pid("BatchReport"))

        c.when("pause", lambda: c.os.proc_now("BatchReport").resource_usage.steps >= 5
               and c.os.proc_now("BatchReport").state == ProcessState.READY, pause)
        c.when("resume", lambda: time.time() - c.board.get("paused_t", 1e18) >= 0.4, resume)

    async def verify(c):
        pt, rt = c.board.get("paused_t"), c.board.get("resumed_t")
        during = [t for t in c.ev("batch_step_t", []) if pt and rt and pt < t < rt]
        return [Check("paused ≥0.4 s with zero steps while paused", pt is not None and rt is not None and not during,
                      f"{len(during)} steps during pause"),
                Check("resumed and finished all 20 steps", len(c.ev("batch_step_t", [])) == 20)]


@scenario("S45", "M1", "Lifecycle", "Pause while asleep: the sleep timer must not wake it")
class _:
    async def setup(c):
        await c.spawn(Stargazer(), name="Stargazer", priority=4)

        async def pause():
            await c.k.pause(c.os.pid("Stargazer"))
            c.board["sg_paused_t"] = time.time()

        async def resume():
            c.board["sg_resumed_t"] = time.time()
            await c.k.resume(c.os.pid("Stargazer"))

        c.when("pause sleeping", lambda: c.board.get("stargazer_asleep")
               and c.os.proc_now("Stargazer").state == ProcessState.WAITING, pause)
        c.when("resume sleeping", lambda: time.time() - c.board.get("sg_paused_t", 1e18) >= 0.4, resume)

    async def verify(c):
        pt, rt = c.board.get("sg_paused_t"), c.board.get("sg_resumed_t")
        ts = c.ev("stargazer_t", [])
        during = [t for t in ts if pt and rt and pt < t < rt]
        return [Check("its 0.1 s sleep expired during the 0.4 s pause, yet it did not run",
                      pt is not None and rt is not None and not during, f"{len(during)} steps during pause"),
                Check("resumed and completed 3 observations", len(ts) == 3
                      and await c.state("Stargazer") == "TERMINATED")]


@scenario("S46", "M1", "Lifecycle", "Cancel a runaway agent; its lock is reclaimed")
class _:
    async def setup(c):
        await c.spawn(RunawayCrawler(), name="RunawayCrawler", priority=3)
        await c.spawn(ReportWriter(), name="ReportWriter", priority=4)
        c.when("cancel crawler", lambda: c.os.proc_now("RunawayCrawler").resource_usage.steps >= 8
               and c.os.proc_now("ReportWriter").state == ProcessState.BLOCKED,
               lambda: c.k.cancel(c.os.pid("RunawayCrawler")))

    async def verify(c):
        cancelled = await c.events(EventType.PROCESS_CANCELLED, "RunawayCrawler")
        return [Check("crawler went through CANCELLED → TERMINATED", bool(cancelled)
                      and await c.state("RunawayCrawler") == "TERMINATED"),
                Check("'crawl-db' reclaimed; blocked ReportWriter completed", bool(c.ev("report_writer_got_lock"))
                      and any(r["lock"] == "crawl-db" for r in c.journal("reclaim", "RunawayCrawler")))]


@scenario("S47", "M1", "Lifecycle", "Cancel an agent while it is WAITING for mail")
class _:
    async def setup(c):
        await c.spawn(MailWatcher(), name="MailWatcher", priority=3)
        c.when("cancel watcher", lambda: c.board.get("watcher_waiting")
               and c.os.proc_now("MailWatcher").state == ProcessState.WAITING,
               lambda: c.k.cancel(c.os.pid("MailWatcher")))

    async def verify(c):
        return [Check("cancelled from WAITING(IPC) and terminated", bool(c.journal("cancel", "MailWatcher"))
                      and await c.state("MailWatcher") == "TERMINATED")]


@scenario("S48", "M1", "Lifecycle", "Process tree: child limit + orphan cascade")
class _:
    async def setup(c):
        await c.spawn(Foreman(), name="Foreman", priority=6, restart="NEVER",
                      limits=ResourceLimits(child_process_limit=3))

    async def verify(c):
        kids = c.ev("children_spawned", [])
        orphans = sorted(o["name"] for o in c.journal("orphan") if o["parent"] == "Foreman")
        return [Check("3 children spawned, the 4th refused", len(kids) == 3 and len(c.ev("child_rejected", [])) == 1),
                Check("orphan policy terminated every child when Foreman died", orphans == sorted(kids), str(orphans))]


@scenario("S49", "M1", "Lifecycle", "Orphan cascade reaches grandchildren")
class _:
    async def setup(c):
        await c.spawn(Director(), name="Director", priority=5, restart="NEVER")

    async def verify(c):
        orphans = {o["name"]: o["parent"] for o in c.journal("orphan")}
        return [Check("Manager terminated because Director died", orphans.get("Manager") == "Director"),
                Check("Intern terminated because Manager died", orphans.get("Intern") == "Manager"),
                Check("whole tree gone", await c.all_terminated("Director", "Manager", "Intern"))]


@scenario("S50", "M1", "Lifecycle", "orphan_policy=KEEP: child outlives its parent")
class _:
    async def setup(c):
        await c.spawn(Founder(), name="Founder", priority=5)

    async def verify(c):
        return [Check("Successor kept running after Founder exited and finished its work",
                      "Successor" in c.ev("worker_finished", [])
                      and not c.journal("orphan", "Successor"))]


@scenario("S51", "M4", "Lifecycle", "Global process limit + spawning a non-agent")
class _:
    async def setup(c):
        try:
            await c.spawn(object(), name="NotAnAgent")
        except TypeError as e:
            c.os.evidence["not_an_agent"].append(str(e))
        await c.spawn(Recruiter(), name="Recruiter", priority=5)

    async def verify(c):
        return [Check("spawning an object without step() raises TypeError", bool(c.ev("not_an_agent"))),
                Check("5 hires fit (6 processes total), the next is refused",
                      len(c.ev("hired", [])) == 5 and bool(c.ev("hire_refused")),
                      f"hired={len(c.ev('hired', []))}"),
                Check("every hire still ran to completion", await c.all_terminated(*c.ev("hired", [])))]


# ═════════════════════════════════ RUNTIME ═══════════════════════════════════
@scenario("S52", "M6", "Runtime", "Stall detection: nothing can ever run again")
class _:
    async def setup(c):
        await c.spawn(Lonely(), name="Lonely-A", priority=5)
        await c.spawn(Lonely(), name="Lonely-B", priority=5)

    async def verify(c):
        return [Check("kernel detected the stall", bool(c.journal("stall")),
                      str(c.journal("stall")[0]["processes"]) if c.journal("stall") else ""),
                Check("both waiters terminated instead of hanging forever",
                      await c.all_terminated("Lonely-A", "Lonely-B"))]


@scenario("S53", "M7", "Runtime", "run(max_seconds): wall-clock budget terminates survivors")
class _:
    async def setup(c):
        await c.spawn(Worker(), name="NightWatch", priority=5)

    async def verify(c):
        return [Check("kernel hit its 1 s budget", bool(c.journal("timeout"))),
                Check("NightWatch terminated", await c.state("NightWatch") == "TERMINATED")]


@scenario("S54", "M8", "Runtime", "run(max_steps): hard ceiling on steps")
class _:
    async def setup(c):
        await c.spawn(InfiniteLooper(), name="Treadmill", priority=5, limits=ResourceLimits(step_limit=1000))

    async def verify(c):
        p = await c.proc("Treadmill")
        steps, state = p.resource_usage.steps, p.state.value
        await c.k.cancel(p.process_id)           # clean up the survivor
        return [Check("run() returned after exactly 25 steps", c.k.steps_taken == 25 and steps == 25,
                      f"kernel steps={c.k.steps_taken}"),
                Check("the survivor is left schedulable (READY) for the caller", state == "READY", state)]


# ═══════════════════════════════════ SDK ═════════════════════════════════════
@scenario("S55", "M9", "SDK", "@agent_os.register + AutoWrapper on plain Python classes")
class _:
    async def setup(c):
        import agent_os
        agent_os.clear_registry()
        log = c.os.evidence

        @agent_os.register(name="Planner", priority=7, steps=[{"args": ["orbit"]}, {"args": ["landing"]}])
        class Planner:
            async def run(self, topic: str) -> str:
                log["planner"].append(topic)
                return f"plan:{topic}"

        @agent_os.register(name="Greeter", priority=6, init_args=["hello"], method="execute")
        class Greeter:
            def __init__(self, word):
                self.word = word

            def execute(self) -> str:                # sync method
                log["greeter"].append(self.word)
                return self.word

        @agent_os.register(name="FlakySDK", priority=5, restart_policy="N_TIMES")
        class FlakySDK:
            calls = 0

            async def run(self) -> str:
                FlakySDK.calls += 1
                log["flaky_calls"].append(FlakySDK.calls)
                if FlakySDK.calls == 1:
                    raise RuntimeError("first contact failed")
                return "ok"

        for p in await c.k.spawn_registered():
            c.os.names[p.name] = p.process_id
        agent_os.clear_registry()

    async def verify(c):
        f = c.failures("FlakySDK")
        return [Check("Planner ran each declared step in order", c.ev("planner", []) == ["orbit", "landing"]),
                Check("init_args + sync method worked", c.ev("greeter", []) == ["hello"]),
                Check("exception → AutoWrapper FAILED → kernel restart → success",
                      bool(f) and "first contact" in f[0]["error"] and c.ev("flaky_calls", []) == [1, 2]),
                Check("all three terminated", await c.all_terminated("Planner", "Greeter", "FlakySDK"))]


# ════════════════════════════════ PLATFORM ═══════════════════════════════════
def _api(c):
    """An HTTP client for the real FastAPI router, bound to this mission's kernel."""
    if "api" not in c.board:
        import httpx
        from fastapi import FastAPI
        from agent_os.api import routes
        view = routes._ks.kernel
        if c.k not in getattr(view, "kernels", ()):     # live dashboard already routes to this kernel
            routes.use_kernel(c.k)
        app = FastAPI()
        app.include_router(routes.router)
        c.board["api"] = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://lab")
    return c.board["api"]


@scenario("S56", "M5", "Platform", "REST API on the live kernel: observe, message, spawn")
class _:
    async def setup(c):
        await c.spawn(Beacon(), name="Beacon", priority=5)

        async def spawn_over_http():
            r = await _api(c).post("/processes", json={"name": "api-agent", "priority": 4})
            c.os.evidence["api_spawn"].append(r.json())

        async def message_over_http():
            r = await _api(c).post("/ipc/send", json={"sender_pid": 0, "receiver_pid": c.os.pid("Beacon"),
                                                      "payload": {"cmd": "deploy-antenna"}})
            c.os.evidence["api_send"].append(r.status_code)

        c.when("spawn via REST", lambda: True, spawn_over_http)
        c.when("message via REST", lambda: c.board.get("beacon_waiting"), message_over_http)

    async def verify(c):
        api = _api(c)
        procs = (await api.get("/processes")).json()
        health = (await api.get("/health")).json()
        done = (await api.get("/events", params={"event_type": "PROCESS_COMPLETED"})).json()
        spawned = c.ev("api_spawn", [{}])[0]
        api_proc = next((p for p in procs if p["process_id"] == spawned.get("process_id")), {})
        return [Check("POST /ipc/send woke the WAITING Beacon", c.ev("api_send") == [200]
                      and c.ev("beacon_got", [None])[0] == {"cmd": "deploy-antenna"}),
                Check("agent spawned over HTTP was run to completion by the native loop",
                      api_proc.get("state") == "TERMINATED", str(api_proc.get("state"))),
                Check("GET /health and /processes reflect the kernel", health.get("status") == "healthy"
                      and health.get("process_count") == len(procs)),
                Check("GET /events filters the audit trail", len(done) >= 2, f"{len(done)} completions")]


@scenario("S57", "M5", "Platform", "REST cancel reclaims the cancelled agent's locks")
class _:
    async def setup(c):
        await c.spawn(Hoarder(), name="Hoarder", priority=4)
        await c.spawn(Archivist(), name="Archivist", priority=5)

        async def cancel_over_http():
            r = await _api(c).post(f"/processes/{c.os.pid('Hoarder')}/cancel")
            c.os.evidence["api_cancel"].append(r.status_code)

        c.when("cancel via REST", lambda: c.os.proc_now("Archivist").state == ProcessState.BLOCKED, cancel_over_http)

    async def verify(c):
        return [Check("REST cancel accepted", c.ev("api_cancel") == [200]),
                Check("Hoarder ends TERMINATED", await c.state("Hoarder") == "TERMINATED",
                      await c.state("Hoarder")),
                Check("its lock went to the waiting Archivist", bool(c.ev("archivist_got_lock")))]


@scenario("S58", "M5", "Platform", "REST pause / resume actually pause and resume")
class _:
    async def setup(c):
        await c.spawn(Metronome(), name="Metronome", priority=3)

        async def pause_over_http():
            r = await _api(c).post(f"/processes/{c.os.pid('Metronome')}/pause")
            c.board["metronome_paused_t"] = time.time()
            c.os.evidence["api_pause"].append((r.json().get("status"), r.json().get("state"),
                                               c.os.proc_now("Metronome").resource_usage.steps))

        async def resume_over_http():
            c.os.evidence["steps_at_resume"].append(c.os.proc_now("Metronome").resource_usage.steps)
            r = await _api(c).post(f"/processes/{c.os.pid('Metronome')}/resume")
            c.os.evidence["api_resume"].append(r.json().get("status"))

        c.when("pause via REST", lambda: c.os.proc_now("Metronome").resource_usage.steps >= 5, pause_over_http)
        c.when("resume via REST", lambda: time.time() - c.board.get("metronome_paused_t", 1e18) >= 0.3,
               resume_over_http)

    async def verify(c):
        status, state, at = c.ev("api_pause", [(None, None, 0)])[0]
        held = c.ev("steps_at_resume", [None])[0]
        return [Check("API paused it (state WAITING)", status == "paused" and state == "WAITING", f"{status}/{state}"),
                Check("no step ran during the 0.3 s pause", held == at, f"paused at step {at}, {held} at resume"),
                Check("REST resume let it finish all 30 ticks", c.ev("api_resume") == ["resumed"]
                      and (await c.proc("Metronome")).resource_usage.steps == 30
                      and await c.state("Metronome") == "TERMINATED")]


@scenario("S59", "M1", "Platform", "MetricsCollector matches the kernel's own accounting")
class _:
    async def setup(c):
        pass

    async def verify(c):
        g = c.k.metrics.get_global_metrics()
        exp = {"total_steps": c.k.steps_taken, "failures": len(c.journal("failure")),
               "restarts": len(c.journal("restart")), "deadlocks": len(c.deadlocks())}
        got = {k: g[k] for k in exp}
        return [Check("steps / failures / restarts / deadlocks agree with the journal", got == exp,
                      f"metrics={got} journal={exp}"),
                Check("LLM, tool and IPC traffic metered", g["total_llm_calls"] > 0 and g["total_tool_calls"] > 0
                      and g["ipc_messages"] > 0, f"llm={g['total_llm_calls']} tool={g['total_tool_calls']} "
                                                 f"ipc={g['ipc_messages']}")]


@scenario("S60", "M1", "Platform", "Audit trail: every lifecycle step is an event")
class _:
    async def setup(c):
        pass

    async def verify(c):
        types = [e.event_type.value for e in await c.events(name="FlightDirector")]
        want = ["PROCESS_CREATED", "PROCESS_READY", "PROCESS_STARTED", "PROCESS_COMPLETED", "PROCESS_TERMINATED"]
        it = iter(types)
        in_order = all(w in it for w in want)
        live = [p.name for p in await c.k.pm.list() if p.state != ProcessState.TERMINATED]
        hist = await c.events()
        kinds = {e.event_type for e in hist}
        must = {EventType.DEADLOCK_DETECTED, EventType.RESOURCE_LIMIT, EventType.RESTART_COMPLETED,
                EventType.LOCK_ACQUIRED, EventType.CONTEXT_SWAP_OUT, EventType.CHECKPOINT_CREATED,
                EventType.IPC_DROPPED, EventType.SANDBOX_COMPLETED, EventType.LLM_CALL, EventType.TOOL_CALL}
        return [Check("FlightDirector: CREATED → READY → STARTED → COMPLETED → TERMINATED", in_order, str(types)),
                Check("every agent in the mission ended TERMINATED", not live, str(live)),
                Check("every subsystem left its mark in the trail", must <= kinds,
                      f"{len(hist)} events; missing {sorted(k.value for k in must - kinds)}")]


@scenario("S61", "M1", "Platform", "Persistence: processes and events round-trip through SQLite")
class _:
    async def setup(c):
        pass

    async def verify(c):
        from agent_os.persistence.database import DatabaseManager
        from agent_os.persistence.repository import Repository
        with tempfile.TemporaryDirectory() as d:
            db = DatabaseManager(f"sqlite+aiosqlite:///{Path(d, 'lab.db').as_posix()}")
            await db.initialize()
            repo = Repository(db)
            procs = await c.k.pm.list()
            for p in procs:
                await repo.save_process({"process_id": p.process_id, "name": p.name, "state": p.state.value,
                                         "priority": p.original_priority, "weight": p.weight,
                                         "parent_process_id": p.parent_process_id,
                                         "restart_count": p.restart_count, "failure_count": p.failure_count,
                                         "creation_time": p.creation_time, "start_time": p.start_time,
                                         "completion_time": p.completion_time})
            events = [e for e in await c.events() if e.event_type in (EventType.DEADLOCK_DETECTED,
                                                                       EventType.RESOURCE_LIMIT)]
            for e in events:
                await repo.save_event({"event_id": e.event_id, "event_type": e.event_type.value,
                                       "process_id": e.process_id, "timestamp": e.timestamp,
                                       "metadata_json": json.dumps(e.metadata, default=str)})
            stored = await repo.list_processes()
            fd = await repo.get_process(c.os.pid("FlightDirector"))
            dl = await repo.get_events(event_type="DEADLOCK_DETECTED")
            await db.close()
        return [Check("every process persisted and read back", len(stored) == len(procs), f"{len(stored)} rows"),
                Check("FlightDirector row intact", bool(fd) and fd["state"] == "TERMINATED" and fd["priority"] == 10),
                Check("deadlock events persisted", len(dl) == len(c.deadlocks()) and len(dl) >= 4, f"{len(dl)} rows")]


@scenario("S62", "M1", "Platform", "State machine rejects illegal transitions")
class _:
    async def setup(c):
        pass

    async def verify(c):
        p = await c.spawn(Tenant(1), name="Probe", priority=1)
        rejected = []
        for target in (ProcessState.COMPLETED, ProcessState.FAILED, ProcessState.BLOCKED, ProcessState.WAITING):
            try:
                await c.k.pm.set_state(p.process_id, target)
            except InvalidStateTransition:
                rejected.append(target.value)
        await c.k.cancel(p.process_id)
        try:
            await c.k.pm.set_state(p.process_id, ProcessState.READY)
            resurrected = True
        except InvalidStateTransition:
            resurrected = False
        return [Check("READY → COMPLETED / FAILED / BLOCKED / WAITING all rejected", len(rejected) == 4, str(rejected)),
                Check("TERMINATED is final (cannot be resurrected)", not resurrected)]
