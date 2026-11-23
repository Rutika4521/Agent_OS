# Agent-OS Showcase — Quick Start

## What This Is

An **Autonomous Incident Response System** built on `agent-os-kernel`.  
7 specialized agents run inside the Agent-OS kernel, demonstrating every OS primitive:

| Agent | Priority | Demonstrates |
|---|---|---|
| `IncidentCommander` | 10 | Preemptive scheduling, IPC send |
| `SecurityAuditor` | 8 | Resource quotas (token burn), multi-step, IPC send/receive |
| `BugFixer` | 7 | WAITING state, decoupled IPC receive |
| `ContendedWorkerA` | 6 | BLOCKED state, deadlock trigger |
| `ContendedWorkerB` | 6 | BLOCKED state, deadlock trigger |
| `FlakyTestRunner` | 5 | FAILED state, Supervisor auto-restart |
| `TelemetryAgent` | 2 | Starvation prevention (aging), background daemon |

---

## Setup (One-time)

### Option A — Install agent-os from local source (recommended during dev)

```powershell
# From the agent-os project root:
cd "C:\Users\RUTIKA\Desktop\LY\EDAI\Agent OS\agent-os"
pip install -e .

# Install showcase deps:
pip install uvicorn fastapi
```

### Option B — Build and install the wheel

```powershell
cd "C:\Users\RUTIKA\Desktop\LY\EDAI\Agent OS\agent-os"
pip install build
python -m build
pip install dist/agent_os_kernel-0.1.0-py3-none-any.whl

pip install uvicorn fastapi
```

---

## Run — Terminal Mode (no server needed)

```powershell
cd "C:\Users\RUTIKA\Desktop\LY\EDAI\showcase"
python main.py
```

You will see all 7 agents spawn, the IPC message flow, FlakyRunner fail+restart,
WorkerA/B deadlock, and a full OS feature coverage report.

---

## Run — Live Dashboard (UI mode)

**Terminal 1 — Start the showcase server:**
```powershell
cd "C:\Users\RUTIKA\Desktop\LY\EDAI\showcase"
python run_server.py
```

**Terminal 2 — Start the React frontend:**
```powershell
cd "C:\Users\RUTIKA\Desktop\LY\EDAI\Agent OS\agent-os\frontend"
npm run dev
```

**Browser:** Open [http://localhost:3000](http://localhost:3000)  
Then click **▶ Run Demo** to trigger the showcase pipeline.

The UI will show:
- ⚙️ **Processes** — 7 agents with live state changes (READY → RUNNING → COMPLETED/FAILED)
- 📅 **Scheduler** — priority ordering timeline
- 📨 **IPC** — Commander→Auditor→Fixer message flow
- 📊 **Resources** — Auditor token burn bars (2000+ tokens)
- 🔒 **Deadlock** — WorkerA/B BLOCKED states
- 📋 **Events** — 100+ OS events audit trail

---

## Project Structure

```
showcase/
├── main.py              # Standalone terminal demo
├── run_server.py        # FastAPI server + showcase demo wired in
├── pyproject.toml
├── QUICKSTART.md        # This file
└── agents/
    ├── __init__.py
    ├── incident_commander.py   # Priority 10, IPC send
    ├── security_auditor.py     # Priority 8, token burn, IPC
    ├── bug_fixer.py            # Priority 7, WAITING state
    ├── flaky_test_runner.py    # Priority 5, FAILED + restart
    ├── contended_workers.py    # Priority 6, BLOCKED + deadlock
    └── telemetry.py            # Priority 2, starvation prevention
```
