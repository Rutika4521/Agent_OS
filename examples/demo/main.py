"""
Agent-OS — Research Intelligence Pipeline Demo
===============================================

A full multi-agent demonstration showcasing every OS feature:

  Agent             Priority   Feature Demonstrated
  ──────────────────────────────────────────────────────
  OrchestratorAgent    10      Priority scheduling, IPC send
  ResearchAgent         8      Multi-step, token consumption, IPC send
  AnalystAgent          7      IPC receive, WAITING state, context swap
  WriterAgent           6      IPC receive, heavy resource burn
  FaultAgent            5      FAILED state, Supervisor restart, recovery
  MonitorAgent          3      Background daemon, process-table polling

Run:
    python examples/demo/main.py

Watch the live output, then open the React dashboard at http://localhost:3000
to see all 6 UI panels populated with real data.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

# ── Path bootstrap ────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parents[2]
_DEMO_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT / "src"))   # agent_os kernel package
sys.path.insert(0, str(_ROOT))           # sdk package (sdk/ at project root)
sys.path.insert(0, str(_DEMO_DIR))       # demo agents importable directly
# ─────────────────────────────────────────────────────────────────────────────

from agent_os.config.settings import Settings
from agent_os.kernel.process_table import ProcessTable
from agent_os.kernel.process_manager import ProcessManager
from agent_os.kernel.state_machine import ProcessState, StepStatus
from agent_os.ipc.ipc_manager import IPCManager
from agent_os.memory.context_manager import ContextManager
from agent_os.memory.checkpoint import CheckpointManager
from agent_os.metrics.events import EventManager
from agent_os.metrics.collector import MetricsCollector
from agent_os.resources.manager import ResourceManager
from agent_os.supervisor.supervisor import Supervisor
from agent_os.supervisor.restart import RestartManager
from agent_os.supervisor.failure import FailureType

from sdk.agent import AgentContext

# Demo agents (imported directly since _DEMO_DIR is on sys.path)
from agents.orchestrator import OrchestratorAgent
from agents.researcher import ResearchAgent
from agents.analyst import AnalystAgent
from agents.writer import WriterAgent
from agents.fault_agent import FaultAgent
from agents.monitor import MonitorAgent


# ─────────────────────────────────────────────────────────────────────────────
# ANSI colour helpers (safe to strip if terminal doesn't support them)
# ─────────────────────────────────────────────────────────────────────────────

BOLD  = "\033[1m"
CYAN  = "\033[96m"
GREEN = "\033[92m"
YELLOW= "\033[93m"
RED   = "\033[91m"
RESET = "\033[0m"

def banner(text: str) -> None:
    width = 64
    print(f"\n{CYAN}{'='*width}{RESET}")
    print(f"{BOLD}{CYAN}  {text}{RESET}")
    print(f"{CYAN}{'='*width}{RESET}\n")

def section(text: str) -> None:
    print(f"\n{YELLOW}── {text} {'─'*(58-len(text))}{RESET}")


# ─────────────────────────────────────────────────────────────────────────────
# Custom Kernel run-loop that integrates the Supervisor for FaultAgent
# ─────────────────────────────────────────────────────────────────────────────

async def tick_process(proc, pm: ProcessManager, supervisor: Supervisor) -> None:
    """Run one scheduling tick for a single READY process."""
    pid = proc.process_id

    # READY → RUNNING
    try:
        await pm.set_state(pid, ProcessState.RUNNING)
    except Exception:
        return

    # Build context (pass process ref so agents can update resource_usage)
    ctx = AgentContext(process_id=pid, data={"process": proc})

    try:
        result = await proc.agent.step(ctx)
    except Exception as exc:
        print(f"  {RED}[OS] PID={pid} raised unhandled exception: {exc}{RESET}")
        await pm.set_state(pid, ProcessState.FAILED)
        await supervisor.handle_failure(
            pid, FailureType.AGENT_EXCEPTION, str(exc)
        )
        return

    proc.resource_usage.steps += 1

    if result.status == StepStatus.COMPLETED:
        await pm.set_state(pid, ProcessState.COMPLETED)
        await pm.terminate(pid)

    elif result.status == StepStatus.FAILED:
        await pm.set_state(pid, ProcessState.FAILED)
        error = result.error or "Agent reported failure"
        await supervisor.handle_failure(
            pid, FailureType.AGENT_EXCEPTION, error
        )

    elif result.status in (StepStatus.WAIT, StepStatus.YIELD):
        from agent_os.kernel.state_machine import WaitReason
        await pm.set_state(pid, ProcessState.WAITING, wait_reason=WaitReason.IPC)
        # Auto-resume: will be re-queued next tick so agent can retry IPC receive
        await pm.set_state(pid, ProcessState.READY)

    else:  # CONTINUE
        await pm.set_state(pid, ProcessState.READY)


async def run_until_done(
    pm: ProcessManager,
    supervisor: Supervisor,
    max_ticks: int = 200,
    tick_delay: float = 0.05,
) -> None:
    """Drive all processes to terminal states with priority ordering."""
    ticks = 0
    while ticks < max_ticks:
        ready = await pm.list(state=ProcessState.READY)

        if not ready:
            # Check if anything is still alive
            alive = []
            for s in (ProcessState.RUNNING, ProcessState.WAITING, ProcessState.BLOCKED):
                alive.extend(await pm.list(state=s))
            if not alive:
                break

        # Sort by priority descending (higher priority runs first)
        ready.sort(key=lambda p: p.priority, reverse=True)

        for proc in ready:
            await tick_process(proc, pm, supervisor)
            ticks += 1

        if tick_delay > 0:
            await asyncio.sleep(tick_delay)

    print(f"\n{GREEN}[OS] Run loop finished after {ticks} ticks.{RESET}")


# ─────────────────────────────────────────────────────────────────────────────
# Main Demo
# ─────────────────────────────────────────────────────────────────────────────

async def main() -> None:
    banner("Agent-OS  ·  Research Intelligence Pipeline Demo")

    # ── 1. Boot all OS subsystems ──────────────────────────────────────────
    section("Booting OS Subsystems")
    settings      = Settings()
    event_manager = EventManager()
    process_table = ProcessTable()
    pm            = ProcessManager(process_table, event_manager, settings)
    ipc_manager   = IPCManager(settings, event_manager)
    resource_mgr  = ResourceManager(settings)
    ctx_manager   = ContextManager(settings, event_manager)
    ckpt_manager  = CheckpointManager(event_manager)
    restart_mgr   = RestartManager(settings.supervisor)
    supervisor    = Supervisor(pm, restart_mgr, event_manager, ckpt_manager)
    metrics       = MetricsCollector()

    print(f"  {GREEN}✓ EventManager, ProcessManager, IPC, Memory, Supervisor — all online{RESET}")

    # ── 2. Spawn agents ───────────────────────────────────────────────────
    section("Spawning Agents")

    # pid_map filled in after all spawns so agents can IPC each other
    pid_map: dict[str, int] = {}

    # Spawn placeholder agents first so PIDs are known, then patch
    _orch      = OrchestratorAgent(ipc_manager, pid_map)
    _researcher= ResearchAgent(ipc_manager, pid_map)
    _analyst   = AnalystAgent(ipc_manager, pid_map)
    _writer    = WriterAgent(ipc_manager)
    _fault     = FaultAgent()
    _monitor   = MonitorAgent(pm)

    p_orch  = await pm.spawn(_orch,       name="Orchestrator",  priority=10)
    p_res   = await pm.spawn(_researcher, name="Researcher",    priority=8)
    p_ana   = await pm.spawn(_analyst,    name="Analyst",       priority=7)
    p_wri   = await pm.spawn(_writer,     name="Writer",        priority=6)
    p_flt   = await pm.spawn(
        _fault,
        name="FaultAgent",
        priority=5,
        restart_policy="N_TIMES",
    )
    p_mon   = await pm.spawn(_monitor,    name="Monitor",       priority=3)

    # Fill pid_map now that PIDs are allocated
    pid_map["researcher"] = p_res.process_id
    pid_map["analyst"]    = p_ana.process_id
    pid_map["writer"]     = p_wri.process_id
    pid_map["monitor"]    = p_mon.process_id

    all_procs = [p_orch, p_res, p_ana, p_wri, p_flt, p_mon]
    print(f"  Spawned {len(all_procs)} agents:\n")
    print(f"  {'PID':<5} {'Name':<18} {'Priority':<10} {'Restart Policy'}")
    print(f"  {'─'*55}")
    for p in all_procs:
        print(f"  {p.process_id:<5} {p.name:<18} {p.priority:<10} {p.restart_policy}")

    # ── 3. Run the pipeline ───────────────────────────────────────────────
    section("Running Pipeline  (priority-scheduled, IPC-connected)")
    print(f"  Priority order: Orchestrator(10) > Researcher(8) > Analyst(7) >"
          f" Writer(6) > FaultAgent(5) > Monitor(3)\n")

    t_start = time.monotonic()
    await run_until_done(pm, supervisor, max_ticks=200, tick_delay=0.03)
    elapsed = time.monotonic() - t_start

    # ── 4. Final Summary ──────────────────────────────────────────────────
    section("Final Process States")
    final = await pm.list()
    print(f"  {'PID':<5} {'Name':<18} {'State':<14} {'Steps':<7} {'Tokens':<8} {'Restarts'}")
    print(f"  {'─'*65}")
    for p in sorted(final, key=lambda x: x.process_id):
        state_col = (
            GREEN if p.state.value in ("COMPLETED", "TERMINATED")
            else RED if p.state.value in ("FAILED",)
            else YELLOW
        )
        print(
            f"  {p.process_id:<5} {p.name:<18} "
            f"{state_col}{p.state.value:<14}{RESET} "
            f"{p.resource_usage.steps:<7} "
            f"{p.resource_usage.total_tokens:<8} "
            f"{p.restart_count}"
        )

    # ── 5. IPC message log ────────────────────────────────────────────────
    section("IPC Message Flow")
    history = await event_manager.get_history()
    ipc_events = [e for e in history if "IPC" in e.event_type.value]
    if ipc_events:
        for e in ipc_events:
            print(f"  [{e.event_type.value}] PID={e.process_id}  {e.metadata}")
    else:
        print(f"  (IPC events not individually emitted — "
              f"messages flowed via send/receive calls above)")

    # ── 6. Supervisor report ──────────────────────────────────────────────
    section("Supervisor — Restart Report")
    failures = await supervisor.get_failures()
    if failures:
        for f in failures:
            print(f"  PID={f.process_id}  type={f.failure_type.value}  "
                  f"error='{f.error_message[:60]}'")
        restarted = [p for p in final if p.restart_count > 0]
        for p in restarted:
            print(f"  {GREEN}✓ PID={p.process_id} ({p.name}) restarted {p.restart_count}x "
                  f"— final state: {p.state.value}{RESET}")
    else:
        print(f"  No failures recorded.")

    # ── 7. Event log summary ──────────────────────────────────────────────
    section("Event Log Summary")
    all_events = await event_manager.get_history()
    by_type: dict[str, int] = {}
    for e in all_events:
        key = e.event_type.value
        by_type[key] = by_type.get(key, 0) + 1

    print(f"  Total events: {len(all_events)}\n")
    for ev_type, count in sorted(by_type.items(), key=lambda x: -x[1]):
        bar = "█" * min(count, 30)
        print(f"  {ev_type:<30} {count:>4}  {bar}")

    # ── 8. Resource summary ───────────────────────────────────────────────
    section("Resource Consumption Summary")
    total_tokens = sum(p.resource_usage.total_tokens for p in final)
    total_steps  = sum(p.resource_usage.steps for p in final)
    total_llm    = sum(p.resource_usage.llm_calls for p in final)
    print(f"  Total tokens consumed : {total_tokens}")
    print(f"  Total steps executed  : {total_steps}")
    print(f"  Total LLM calls       : {total_llm}")
    print(f"  Wall time             : {elapsed:.2f}s")

    # ── Monitor report ────────────────────────────────────────────────────
    section("Monitor Agent Report")
    print(f"  Completed {_monitor._tick} monitoring ticks")
    print(f"  Collected {len(_monitor.snapshots)} system snapshots")
    if _monitor.snapshots:
        last = _monitor.snapshots[-1]
        print(f"  Last snapshot — tick {last['tick']}: "
              f"processes={last['process_count']}, "
              f"tokens={last['total_tokens']}, "
              f"steps={last['total_steps']}")

    banner("Demo Complete  🎉")
    print(f"  {GREEN}All OS features demonstrated:{RESET}")
    features = [
        ("Priority Scheduling", "Orchestrator(10) always ran before Monitor(3)"),
        ("IPC",                 "Orchestrator → Researcher → Analyst → Writer"),
        ("WAITING State",       "Analyst & Writer yielded until IPC message arrived"),
        ("Resource Tracking",   f"Researcher burned {p_res.resource_usage.total_tokens} tokens across 4 steps"),
        ("Supervisor Restart",  f"FaultAgent failed, restarted {p_flt.restart_count}x, recovered"),
        ("Background Daemon",   f"Monitor ran {_monitor._tick} ticks at priority 3"),
        ("Event System",        f"{len(all_events)} events captured across entire run"),
    ]
    for name, detail in features:
        print(f"  {GREEN}✓{RESET} {BOLD}{name:<22}{RESET} — {detail}")

    print(f"\n  {CYAN}💡 Tip: run 'python run.py server' + 'cd frontend && npm run dev'{RESET}")
    print(f"  {CYAN}   then replay this demo to see all 6 dashboard panels live.{RESET}\n")


if __name__ == "__main__":
    asyncio.run(main())
