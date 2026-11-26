# Agent-OS Testbed

A multi-agent system that exercises **every real Agent-OS subsystem**: about 60 agents across 32 scenarios.
Each scenario includes edge cases and actual deadlocks, and comes with pass/fail checks backed by evidence.

The `showcase/` app mostly *narrates* features (its "deadlock" agents just print).
The testbed uses the kernel's actual `SynchronizationManager`, `PriorityScheduler` + `AgingPolicy`,
`WeightedFairScheduler`, `ContextManager`/LRU swap, `CapabilityManager`, `SubprocessSandbox`,
`Supervisor`, `CheckpointManager`, `ResourceManager` and `IPCManager`.

## Run

```powershell
# Terminal scorecard (~5 s)
python testbed/runner.py
python testbed/runner.py --quiet          # scorecard only
python testbed/runner.py --only S07,S08   # just the deadlock scenarios

# As part of the test suite (one pytest test per scenario)
python -m pytest tests/test_testbed.py

# Live on the dashboard (paced, ~22 s)
python testbed/run_server.py              # Terminal 1
cd frontend; npm run dev                  # Terminal 2 → http://localhost:3000 → ▶ Run Demo
# scorecard JSON: http://localhost:8000/testbed/report
```

On Windows, set `$env:PYTHONUTF8=1` if your console can't print the emoji in the log.

## Scenarios

| ID | Area | What is forced to happen | Verified |
|---|---|---|---|
| S01 | Scheduling | Prio-10 Commander among ~50 agents | it is the very first pick |
| S02 | Scheduling | Prio-1 Janitor vs three prio-7 CPU hogs | aging schedules it while hogs are still runnable |
| S03 | Scheduling | Tenants weighted 1:2:4 under `weighted_fair` | CPU share ≈ 1:2:4 |
| S04 | IPC | Dispatcher → 3 Workers → Aggregator | workers park in WAITING(IPC); correlation IDs all match |
| S05 | IPC | 8-message burst into a cap-3 REJECT mailbox | exactly 3 delivered, 5 `IPC_DROPPED` |
| S06 | IPC | Send to a crashed peer and to PID 9999; wait for a reply that never comes | dead letters dropped; IPC deadline wakes the waiter |
| S07 | Deadlock | Ledger/Auditor take locks in AB/BA order | 2-cycle detected; lowest-priority victim restarted; both finish |
| S08 | Deadlock | Three dining philosophers | 3-cycle detected; victim Philosopher-0; all eat |
| S09 | Sync | Priority inversion (Low holds lock, High blocked, Medium busy) | Low inherits 2→9, releases before Medium runs, priority restored |
| S10 | Sync | 4 GPU jobs, semaphore with 2 slots | peak 2 holders, extras BLOCKED, all complete |
| S11 | Sync | Agent exits while holding a lock | leak detected, lock reclaimed and handed to the waiter |
| S12 | Sync | Re-entrant lock acquire | `LockError` → FAILED, lock freed |
| S13–S16 | Quotas | Token / step / tool-call / wall-time runaways | each killed by `RESOURCE_LIMIT`, never restarted |
| S17–S20 | Supervisor | NEVER, ONCE, N_TIMES recovery, crash loop | restart counts match each policy; loop capped at 3 |
| S21 | Supervisor | EXPONENTIAL_BACKOFF | delays 0.15 → 0.3 → 0.6 s and actually honoured |
| S22 | Supervisor | Step hangs for 10 s | 0.4 s step timeout fires; restart succeeds |
| S23 | Supervisor | LLM provider outage | classified `LLM_FAILURE`; retry succeeds |
| S24 | Memory | 10-batch job loses power at batch 6 | resumes from checkpoint; every batch exactly once |
| S25 | Memory | 12 pages into an 8-page budget plus 2 pinned | LRU swap-outs; page fault restores intact content; pinned pages survive |
| S26 | Memory | Pin more pages than the budget | kernel survives; all contexts freed at exit |
| S27 | Security | Intern without `db.write`, DBA with it, Contractor revoked mid-run | deny / allow / cut off right after revocation |
| S28 | Security | Sandboxed subprocess, runaway subprocess, no-`sys.exec` agent | stdout captured; killed at 0.5 s; denied |
| S29 | Lifecycle | Operator pauses then resumes a job | zero steps run while paused; finishes all 20 |
| S30 | Lifecycle | Operator cancels a runaway that holds a lock | lock reclaimed; blocked writer completes |
| S31 | Lifecycle | Parent spawns 4 children (limit 3), then crashes | 4th refused; orphans cascade-terminated |
| S32 | Kernel | Illegal transitions READY→COMPLETED/FAILED/BLOCKED | all rejected; nothing left alive |

## Kernel findings

The testbed reports behaviour in `src/agent_os` that is worth fixing:

1. ~~**`WeightedFairScheduler` starves low-weight processes.**~~ *Fixed: the winner now pays back the total runnable weight.* Every pick adds `weight` to all runnable deficits but subtracts only 1 from the winner. The deficits diverge, so the heaviest tenant always wins (observed A/B/C = 0/10/60 instead of 10/20/40).
2. **Token quota overshoot.** `consume_tokens` charges first and checks afterwards, so a process can exceed its budget by up to one call. TokenHog used 1200 of a 1000-token budget.
3. **`ContextManager` over-commits under pressure.** When every page is pinned it swallows `MemoryPressureError` and keeps loading (10 loaded with a budget of 8).
4. **`ContextManager` ignores `memory.max_loaded_pages`.** It reads `settings.max_loaded_pages` (top level, which doesn't exist), so it always uses 100. The testbed sets the limit directly.
5. **`Supervisor` never applies backoff.** It computes nothing with `get_backoff_delay`, and EXPONENTIAL_BACKOFF restarts immediately. The testbed driver applies the delay itself.
6. ~~**`IPCManager` accepts mail for dead or non-existent PIDs** and queues it forever.~~ *Fixed: the kernel installs a receiver check on its mailboxes.* The testbed's send syscall still drops such mail itself, with `IPC_DROPPED`.
7. **`IPCManager` deduplication can't trigger through `send()`**, because each call mints a fresh UUID message id.
8. **Orphan policy is configured but not implemented.** `orphan_policy: TERMINATE` exists in config, but the kernel never acts on it. The testbed driver cascades it.

## Layout

```
testbed/
├── kernel.py      TestbedKernel: wires all subsystems + scheduling loop + Sys syscall API
├── scenarios.py   32 scenarios: setup() spawns agents/hooks, verify() returns checks
├── runner.py      CLI runner + scorecard (writes last_report.json)
├── run_server.py  plugs the testbed into the FastAPI server for the React dashboard
└── agents/        scheduling, ipc, sync, resources, reliability, memory, security, lifecycle
```

### Writing a new scenario

```python
@scenario("S33", "Sync", "My edge case")
class _:
    async def setup(k):
        await k.spawn(MyAgent(), name="Mine", priority=5, restart="ONCE",
                      limits=ResourceLimits(token_limit=500), caps=["net.http"])
        k.when("operator action", lambda: <predicate>, lambda: k.cancel("Mine"))

    async def verify(k):
        return [Check("it did the thing", await state(k, "Mine") == "TERMINATED")]
```

Agents implement `async def step(ctx)` and use `s = ctx.data["sys"]` for everything:
`s.llm`, `s.tool`, `s.sandbox`, `s.send`/`s.recv`, `s.acquire`/`s.release`, `s.sem_acquire`,
`s.page_add`/`s.page_read`, `s.checkpoint`, `s.spawn`, `s.sleep()`, `s.wait_ipc()`, `s.record`.

## Same agents on Agent-OS's native runtime

```powershell
python testbed/native.py              # side-by-side scorecard
python -m pytest tests/test_testbed.py  # every scenario on both runtimes
```

`native.py` runs the same 60 agents and checks under the public `agent_os.Kernel().run()` loop
from `sdk/kernel.py`, with spawn order reversed. The testbed driver loop is **not** used.
The agents' syscalls use the kernel's own subsystems (`kernel.sync`, `.resources`, `.contexts`,
`.checkpoints`, `.capabilities`, `.ipc`). The adapter only injects `sys`, records the trace and
turns the kernel's journal (`kernel.observe(...)`) into the evidence the checks read.

| | Driver | Native `Kernel.run()` before | Native `Kernel.run()` now |
|---|---|---|---|
| Scenarios | 31/32 | 7/32 | **31/32** (stable over 10 runs) |
| Time | 4.9 s | 56.5 s (hit limits) | **3.4 s** |
| Processes never terminated | 0 | 29 | **0** |
| Deadlocks resolved | 2 | 0 | **2** |

S03 failed on both runtimes until the `WeightedFairScheduler` fix (finding 1). Both runtimes now score 32/32.

What `Kernel.run()` now does every quantum:
1. Wakes sleepers, IPC waiters that got mail or hit `ipc_wait_timeout` (with `ctx.data["ipc_timed_out"]`), and BLOCKED processes that were handed their lock or semaphore.
2. Applies priority inheritance to lock owners and restores the priority once the lock is released.
3. Rebuilds the wait-for graph from live lock state. On a cycle, it fails the lowest-priority process through the Supervisor.
4. Lets the configured scheduler (`priority` with aging, or `weighted_fair`; switch with `kernel.use_scheduler`) pick **one** READY process.
5. Runs a quota pre-check, then the step under a per-process `step_timeout`. Exceptions are classified (`failure_type` / `restartable` attributes are honoured) and sent to the Supervisor: restart policy, `agent.on_restart(checkpoint_state)`, and `EXPONENTIAL_BACKOFF` delays that are actually applied.
6. On exit, failure or cancel, reclaims locks and semaphores and hands them to the next waiter, frees memory contexts, and applies the orphan policy to children.
7. Exposes operator controls `kernel.pause/resume/cancel(pid)`, `max_seconds`, and stall detection.

Also fixed along the way: the checkpoint used for resume was picked by `max(timestamp)`, which ties on
Windows (~15 ms clock), so a stale checkpoint was sometimes restored. Both runtimes now use the
process's recorded `checkpoint_id`.
