# Autonomous Incident Response System — Agent-OS Showcase

> A fully self-contained multi-agent application that **imports `agent-os` as a pip package**.
> Demonstrates every Agent-OS OS feature in a realistic enterprise scenario.

## Concept

An autonomous Software Incident Response Team — agents collaborate under OS control
to detect, analyse, patch, and verify security vulnerabilities.

## Agents

| Agent | Priority | OS Feature Demonstrated |
|-------|----------|------------------------|
| `IncidentCommanderAgent` | 10 | Priority scheduling — always dispatched first |
| `SecurityAuditorAgent` | 8 | Resource quotas — heavy token consumer; stops at hard limit |
| `BugFixerAgent` | 7 | IPC receive — waits for Auditor's vulnerability report |
| `FlakyTestRunnerAgent` | 5 | Supervisor auto-restart — intentionally crashes, recovers |
| `ContendedWorkerA/B` | 6 | Deadlock detection — both request the same lock |
| `TelemetryAgent` | 2 | Starvation prevention — aging raises effective priority |

## Setup

```bash
# Option A: Use local wheel (recommended for demo)
cd ../agent-os
pip install build
python -m build
pip install dist/agent_os_kernel-0.1.0-py3-none-any.whl

# Option B: Install from TestPyPI (after publishing)
pip install --index-url https://test.pypi.org/simple/ agent-os-kernel

# Install showcase
cd ../showcase
pip install -e .

# Run the showcase (standalone terminal output)
python main.py

# Run with live API + UI
python run_server.py          # Terminal 1 — API on port 8000
cd ../agent-os/frontend && npm run dev  # Terminal 2 — UI on port 3000
# Browser → http://localhost:3000 → Click ▶ Run Demo
```

## What You Will See in the UI

| Dashboard Tab | Live Observation |
|--------------|-----------------|
| ⚙️ Processes | 7 agents; states cycling READY→RUNNING→WAITING→FAILED→RESTARTING |
| 📅 Scheduler | Commander(10) always ahead of Telemetry(2); aging visible |
| 📨 IPC | Auditor→Fixer vulnerability report flowing through message queue |
| 📊 Resources | Auditor token bar hitting 80%+; hard preemption at limit |
| 🔒 Deadlock | ContendedWorkerA/B circular lock dependency detected & resolved |
| 📋 Events | 100+ events: `RESTART_STARTED`, `IPC_SENT`, `PROCESS_FAILED` |
