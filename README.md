# Agent-OS 🤖

> An operating-system kernel for LLM agents.  
> Scheduling · IPC · Memory · Supervisor · Deadlock Detection · Persistence

Agent-OS treats LLM agents as first-class OS processes — each agent gets a PID,
priority, resource quota, and lifecycle managed by a real scheduler and supervisor,
just like threads in an operating system.

---

## Features

| OS Concept | Agent-OS Implementation |
|---|---|
| **Process Management** | Spawn, list, pause, resume, cancel, terminate agents |
| **Priority Scheduling** | Preemptive priority queue with starvation prevention via aging |
| **IPC** | Per-PID message queues, point-to-point routing, and deduplication |
| **Memory / Context** | Context pages, swap-in/swap-out, LRU eviction |
| **Supervisor** | Auto-restart on failure with configurable policies (`ONCE`, `N_TIMES`, `EXPONENTIAL_BACKOFF`) |
| **Deadlock Detection** | Cycle detection on resource wait graphs with automatic kernel resolution |
| **Resource Quotas** | Hard kernel limits: token, step, LLM-call, and wall-time quotas |
| **Persistence Layer** | Async SQLite storage via SQLAlchemy for processes, states, checkpoints, and events |
| **Event System** | Full audit log of every kernel transition and state change |
| **REST API** | FastAPI server with interactive Swagger documentation at `/docs` |
| **React Dashboard** | Real-time UI: 6 live panels, one-click `▶ Run Demo`, adaptive polling |

---

## Installation & Quick Start

### 1. From PyPI / Wheel

```bash
# Core kernel + SDK
pip install agent-os-kernel

# With SQLite persistence support
pip install "agent-os-kernel[persistence]"

# Or full dev environment
pip install "agent-os-kernel[all,dev]"
```

### 2. From Source

```bash
# Clone repository
git clone https://github.com/Rutika4521/Agent_OS.git
cd Agent_OS

# Install in editable mode
pip install -e ".[all,dev]"
```

### 3. Run the CLI / API Server

```bash
# Start the API server via CLI
agent-os server --host 0.0.0.0 --port 8000

# Or using the run script
python run.py server
# Interactive Swagger UI available at: http://localhost:8000/docs
```

### 4. Start the React UI Dashboard

```bash
cd frontend
npm install
npm run dev
# Dashboard available at: http://localhost:3000
```
Click **`▶ Run Demo`** on the top bar to trigger the multi-agent pipeline and watch live process transitions, scheduler ordering, IPC messages, and resource meters in real time!

---

## SDK — 10-line Quickstart

```python
import agent_os
import asyncio

@agent_os.register(priority=8, name="Researcher", steps=[
    {"args": ["quantum computing"]},
    {"args": ["neural networks"]},
])
class ResearchAgent:
    async def run(self, topic: str) -> str:
        return f"Findings on {topic}"

@agent_os.register(priority=6, name="Writer")
class WriterAgent:
    async def run(self) -> str:
        return "Report compiled."

async def main():
    kernel = agent_os.Kernel()
    await kernel.boot()
    await kernel.spawn_registered()
    await kernel.run()

asyncio.run(main())
```

---

## Showcase Application — Autonomous Incident Response

A standalone enterprise incident response system demonstrating every Agent-OS capability:

```bash
# Run standalone terminal demo
cd showcase
python main.py

# Or start the showcase live server
python run_server.py
# (Open http://localhost:3000 and click ▶ Run Demo)
```

| Agent | Priority | OS Feature Demonstrated |
|---|---|---|
| `IncidentCommanderAgent` | 10 | Preemptive Priority Scheduling (always scheduled first) |
| `SecurityAuditorAgent` | 8 | Resource Quotas (token burn) & IPC report dispatch |
| `BugFixerAgent` | 7 | WAITING state & decoupled IPC receipt |
| `ContendedWorkerA / B` | 6 | Circular lock dependency & Deadlock Detection |
| `FlakyTestRunnerAgent` | 5 | FAILED state & Supervisor auto-restart (`N_TIMES`) |
| `TelemetryAgent` | 2 | Starvation prevention via dynamic Priority Aging |

---

## Architecture

```
agent-os/
├── src/agent_os/          # Core OS Kernel
│   ├── kernel/            #   Process table, state machine, process manager
│   ├── scheduler/         #   Priority scheduler with aging
│   ├── ipc/               #   Message queues, routing, deduplication
│   ├── memory/            #   Context manager, checkpointing, LRU eviction
│   ├── resources/         #   Hard quota enforcement (tokens, steps, wall-time)
│   ├── supervisor/        #   Failure detection & auto-restart manager
│   ├── deadlock/          #   Resource wait graph cycle detection
│   ├── persistence/       #   Async SQLite database, models, and repositories
│   ├── metrics/           #   Event manager & metrics collector
│   ├── api/               #   FastAPI REST server & demo endpoints
│   └── cli.py             #   CLI entrypoint (`agent-os`)
├── sdk/                   # Developer SDK
│   ├── __init__.py        #   Public API exports
│   ├── kernel.py          #   Kernel bootstrap class
│   ├── registry.py        #   @agent_os.register() decorator
│   ├── wrapper.py         #   AutoWrapper (run/execute/__call__ → step)
│   └── agent.py           #   Agent protocol & AgentContext
├── frontend/              # React Dashboard (Vite, Recharts, Lucide)
├── examples/              # Research pipeline demo & SDK examples
├── showcase/              # Standalone 7-agent showcase application
└── tests/                 # 340+ unit and integration tests
```

---

## Process States

```
CREATED → READY → RUNNING → COMPLETED → TERMINATED
                    ↓  ↑
                 WAITING / BLOCKED
                    ↓
                 CANCELLING → CANCELLED → TERMINATED
                    ↓
                  FAILED → RESTARTING → READY
```

---

## REST API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/processes` | List all processes in the system |
| `POST` | `/processes` | Spawn an agent process |
| `GET` | `/processes/{pid}` | Inspect state and resource usage for PID |
| `POST` | `/processes/{pid}/pause` | Pause process execution |
| `POST` | `/processes/{pid}/resume` | Resume paused process |
| `POST` | `/processes/{pid}/cancel` | Gracefully cancel a process |
| `POST` | `/processes/{pid}/terminate` | Force terminate a process |
| `POST` | `/ipc/send` | Send an IPC message between two PIDs |
| `GET` | `/ipc/receive/{pid}` | Retrieve queued message for a PID |
| `GET` | `/events` | Query audit trail of kernel events |
| `GET` | `/metrics` | Aggregated CPU/tokens/state metrics |
| `GET` | `/health` | System health check and status |
| `POST` | `/demo/run` | Trigger multi-agent pipeline in background |
| `GET` | `/demo/status` | Current status of running pipeline |
| `POST` | `/demo/reset` | Clear process table and reset demo state |

---

## Running Tests

```bash
# Run complete test suite (340+ tests)
python run_tests.py

# Or via pytest directly
pytest tests/ -v

# Run with test coverage
pytest tests/ --cov=agent_os
```

---

## License

MIT — see [LICENSE](LICENSE)
