# Changelog

All notable changes to Agent-OS are documented here.

---

## [0.1.0] — 2026-11-03

### Added

#### Core Kernel
- `ProcessManager` — spawn, list, cancel, terminate, pause, resume agents
- `ProcessTable` — in-memory store with PID allocation
- `StateMachine` — 11-state FSM with validated transitions
- `AgentProcess` — dataclass holding full process state

#### Scheduler
- `PriorityScheduler` — preemptive priority queue (1–10)
- Starvation aging — priority bonus grows over wait time
- Weighted-fair scheduling support

#### IPC
- Per-PID `MessageQueue` with configurable capacity and overflow policy
- `DeduplicationFilter` — idempotency on message IDs
- `IPCManager` — high-level send/receive/wait interface

#### Memory
- `ContextManager` — context pages with LRU eviction and swap-in/swap-out
- `CheckpointManager` — save and restore process snapshots

#### Supervisor
- `Supervisor` — monitors for failures, triggers restarts
- `RestartManager` — policies: `NEVER`, `ONCE`, `N_TIMES`, `EXPONENTIAL_BACKOFF`

#### Deadlock Detection
- `DeadlockDetector` — cycle detection on resource wait graph
- `LockManager` — acquire/release with holder tracking

#### Resources
- `ResourceManager` — enforces token, step, LLM-call, tool-call, wall-time limits
- `ResourceLimits` / `ResourceUsage` — typed quota and consumption tracking

#### Metrics & Events
- `EventManager` — async event bus with full history
- `MetricsCollector` — aggregate stats per process

#### Security
- Capability system — per-process permission sets

#### API
- FastAPI REST server with OpenAPI docs (`/docs`)
- Endpoints: processes, events, IPC, metrics, health

#### SDK
- `@agent_os.register()` — class decorator for zero-boilerplate agent registration
- `Kernel` — one-call bootstrap for all subsystems
- `AutoWrapper` — wraps any `run()`/`execute()`/`__call__()` agent into step protocol
- `Agent` protocol + `AgentContext`

#### UI
- React 18 + Vite dashboard
- 6 live panels: Process Table, Event Log, Resource Meters, IPC Flow, Deadlock Graph, Scheduler Timeline

#### Demo
- `examples/demo/` — Research Intelligence Pipeline with 6 agents showcasing all OS features
- `examples/sdk_example/` — Minimal SDK quickstart

#### Tests
- 340+ tests across all subsystems (pytest + pytest-asyncio)

---

## Roadmap

- `[0.2.0]` Persistence layer (SQLite checkpointing)
- `[0.2.0]` Tool execution subsystem
- `[0.3.0]` Distributed multi-node scheduling
- `[0.3.0]` Pluggable LLM provider adapters
