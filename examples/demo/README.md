# Agent-OS — Research Intelligence Pipeline Demo

> A production-quality multi-agent demo that exercises **every** Agent-OS OS feature.

## Run it

```bash
# From the project root:
python examples/demo/main.py
```

## What it shows

| OS Feature | Agent | What happens |
|-----------|-------|-------------|
| **Priority Scheduling** | All agents | Orchestrator(10) always ticks before Monitor(3) |
| **IPC** | Orchestrator → Researcher → Analyst → Writer | Task assignments and findings flow via message queues |
| **WAITING State** | Analyst, Writer | Agents yield back to scheduler when IPC queue is empty, auto-resume next tick |
| **Multi-step Execution** | Researcher (4 steps), Analyst (3 steps) | State machine cycles RUNNING→READY per step |
| **Resource Tracking** | Researcher, Writer | Token, LLM-call, step counters updated per step — visible in Resource Meters tab |
| **Supervisor Restart** | FaultAgent | Fails on step 2, Supervisor restarts it, recovers cleanly |
| **Background Daemon** | Monitor | Lowest priority (3), collects system snapshots every tick |
| **Event System** | All | 50+ events: spawns, state transitions, IPC, failures, restarts |

## Agents

```
OrchestratorAgent  (priority=10)
  └─ IPC: assigns tasks to Researcher, Analyst, Writer
  └─ 3 steps → COMPLETED

ResearchAgent  (priority=8)
  └─ 4 steps, each consuming 280–510 tokens
  └─ Sends findings to Analyst on completion

AnalystAgent  (priority=7)
  └─ Waits for IPC from Researcher (WAITING state shown)
  └─ 3 analysis phases, sends synthesis to Writer

WriterAgent  (priority=6)
  └─ Waits for IPC from Analyst
  └─ 2 steps: Draft (620 tokens) → Polish (390 tokens)

FaultAgent  (priority=5, restart_policy=N_TIMES)
  └─ Step 1: OK
  └─ Step 2: returns FAILED → Supervisor triggers restart
  └─ After restart: completes successfully

MonitorAgent  (priority=3)
  └─ Runs for 20 ticks, polls process table each time
  └─ Prints system stats every 3 ticks
```

## Expected output (abbreviated)

```
================================================================
  Agent-OS  ·  Research Intelligence Pipeline Demo
================================================================

── Booting OS Subsystems ──────────────────────────────────────
  ✓ EventManager, ProcessManager, IPC, Memory, Supervisor — all online

── Spawning Agents ────────────────────────────────────────────
  PID   Name               Priority   Restart Policy
  ───────────────────────────────────────────────────────
  1     Orchestrator       10         N_TIMES
  2     Researcher         8          N_TIMES
  3     Analyst            7          N_TIMES
  4     Writer             6          N_TIMES
  5     FaultAgent         5          N_TIMES
  6     Monitor            3          N_TIMES

── Running Pipeline ───────────────────────────────────────────
  [Orchestrator] Sent research task to Researcher (PID 2)
  [Researcher]   Step 1/4 — Quantum Computing (320 tokens)
  [Analyst]      Waiting for research data via IPC...
  ...
  [FaultAgent]   Step 2 — SIMULATING CRASH 💥
  [OS]           Supervisor: restarting PID 5 (restart #1)
  [FaultAgent]   Post-restart step 1 — recovered ✓
  ...

── Final Process States ───────────────────────────────────────
  1     Orchestrator       TERMINATED     3       0        0
  2     Researcher         TERMINATED     4       1560     4
  3     Analyst            TERMINATED     3       730      3
  4     Writer             TERMINATED     2       1010     2
  5     FaultAgent         TERMINATED     4       0        1
  6     Monitor            TERMINATED     1       0        0

── Event Log Summary ──────────────────────────────────────────
  Total events: 68

  PROCESS_READY              18  ██████████████████
  PROCESS_STARTED            18  ██████████████████
  PROCESS_COMPLETED           5  █████
  PROCESS_TERMINATED          6  ██████
  RESTART_STARTED             1  █
  ...

================================================================
  Demo Complete  🎉
================================================================
  ✓ Priority Scheduling   — Orchestrator(10) always ran before Monitor(3)
  ✓ IPC                   — Orchestrator → Researcher → Analyst → Writer
  ✓ WAITING State         — Analyst & Writer yielded until IPC message arrived
  ✓ Resource Tracking     — Researcher burned 1560 tokens across 4 steps
  ✓ Supervisor Restart    — FaultAgent failed, restarted 1x, recovered
  ✓ Background Daemon     — Monitor ran 20 ticks at priority 3
  ✓ Event System          — 68 events captured across entire run
```

## Watch it live in the dashboard

```bash
# Terminal 1 — API server
python run.py server

# Terminal 2 — React dashboard
cd frontend && npm run dev

# Terminal 3 — run the demo (populates the UI with live data)
python examples/demo/main.py
```

Then open **http://localhost:3000** and explore all 6 panels.
