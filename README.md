# Agent-OS

Agent-OS is an operating system-inspired runtime for LLM agents.

## 1. What Agent-OS is
Agent-OS maps traditional OS concepts (processes, scheduling, memory, IPC) to LLM agent operations. It manages multi-agent systems, resource constraints, state swapping, and scheduling transparently.

## 2. Problem being solved
Complex multi-agent applications lack unified orchestration. State bloat, context window limits, lack of preemption, and single-threaded execution loops plague LLM agent architectures. Agent-OS solves this.

## 3. Architecture
```
+--------------------------------------------------------+
|                      Agent-OS Kernel                   |
|  +--------------+  +---------------+  +-------------+  |
|  | Process Mgr  |  | Scheduler     |  | IPC Manager |  |
|  +--------------+  +---------------+  +-------------+  |
|  +--------------+  +---------------+  +-------------+  |
|  | Context Mgr  |  | Resource Mgr  |  | Supervisor  |  |
|  +--------------+  +---------------+  +-------------+  |
+--------------------------------------------------------+
```

## 4. Core Components
- **Kernel & Processes**: Process table, PID assignment, PCB state machine.
- **Scheduler**: Priority, aging, and weighted fair queueing.
- **IPC Manager**: Inter-process message passing.
- **Memory**: Context manager, paging, swapping, LRU.
- **Resources**: Quotas on tokens, steps, and tool calls.
- **Supervisor**: Restarts and failure recovery.

## 5. Installation
```bash
pip install -r requirements.txt
pip install -e .
```

## 6. Configuration
The system uses `config.yaml` to specify paths, scheduler slices, token limits, and DB connections.

## 7. Running the Project
```bash
python run.py demo
python run.py server
```

## 8. Running Tests
```bash
pytest tests/ -v
```

## 9. Creating an Agent
```python
class MyAgent:
    async def step(self, context) -> AgentStepResult:
        return AgentStepResult(status=StepStatus.COMPLETED)
```

## 10. Scheduling
Supports strict priority, starvation prevention via aging, and optionally Weighted Fair Queueing (WFQ).

## 11. IPC
Agents can send messages blocking or non-blocking to other PIDs. Wait states seamlessly wake up when a message arrives.

## 12. Context Management
Maintains agent contexts. Swaps pages to disk (via LRU) to save active memory/token limits.

## 13. Resource Management
Limits and monitors LLM token usage, execution steps, and concurrent limits per process tree.

## 14. Failure Recovery
The Supervisor handles failures with policies: ALWAYS, ON_FAILURE, NEVER. Supports bounded retries with backoff.

## 15. API
- `POST /processes` - Create process
- `POST /processes/{pid}/start`
- `GET /processes/{pid}`
- `GET /processes`

## 16. Example Execution
See `python run.py demo` for a full trace of scheduling, memory swapping, and IPC routing.

## 17. Limitations (V1)
- Single node only
- In-memory event bus
- Mock filesystem isolation

## 18. Future Extensions
- Distributed clustering
- File system sandbox and mounts
- Hypervisor/Container integration
