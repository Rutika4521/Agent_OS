# Orbital Research Lab: the full Agent-OS showcase

A multi-agent system of about 110 agents in ten departments. It runs on the **native `agent_os.Kernel().run()`** loop, with no custom scheduler, no driver loop and no wrapper around the kernel. The suite has 62 scenarios in 9 missions, and they set out to trigger every capability and edge case Agent-OS has. Each scenario checks its outcome against evidence the kernel itself produced.

```powershell
python showcase_full/run.py                 # live log + scorecard (~10 s)
python showcase_full/run.py --quiet         # scorecard only
python showcase_full/run.py --mission M1    # one mission
python showcase_full/run.py --only S12,S13  # chosen scenarios
python showcase_full/run.py --forward       # spawn in declaration order (default: reversed)
python -m pytest tests/test_showcase_full.py
```

### On the dashboard (▶ Run Demo)

```powershell
python showcase_full/run_server.py          # Terminal 1 (API :8000); `python run.py server` is the same
cd frontend; npm run dev                    # Terminal 2 → http://localhost:3000 → ▶ Run Demo
```

▶ Run Demo runs all 9 missions inside the server, paced at 20 ms per step (about 20 s in total).
The **🛰 Scorecard** tab fills in mission by mission, with every check's evidence one click away.
The Processes, Scheduler, IPC, Resources, Deadlock and Events tabs show the live kernels.
All mission kernels share one event log and get separate PID ranges (M1 = 1…, M2 = 1001…, …), so the
tables build up to all 112 processes. Pause, resume and cancel in the UI reach whichever kernel owns
the PID. The JSON scorecard is at `GET /demo/report`.

On Windows, set `$env:PYTHONUTF8=1` if the console can't print the log's emoji. The run writes its results to `showcase_full/last_report.json`.

**Result: 62 / 62 pass.** The first version of the showcase found 4 Agent-OS bugs, listed below. All four are fixed, and their scenarios now pass. The same 62/62 holds in the terminal, in pytest and from ▶ Run Demo.

## How it works

```
showcase_full/
├── run.py              CLI runner and scorecard
├── run_server.py       dashboard server (▶ Run Demo runs this lab)
├── live.py             live mode: shared event log, PID ranges, DashboardView
└── lab/
    ├── os_api.py       LabOS: the syscalls agents use, on the kernel's own subsystems
    ├── harness.py      missions, scenarios, operator hooks, evidence queries
    ├── missions.py     9 missions × 62 scenarios
    └── agents/         command · comms · vault · budget · reliability · archive ·
                        security · operations · platform
```

* **Missions:** a mission is one boot of `agent_os.Kernel` with its own `Settings`. All of a mission's scenarios spawn their agents into that one kernel, so the agents compete for the scheduler, locks, memory and mailboxes concurrently. M1 alone runs 87 agents.
* **Agents:** agents subclass `LabAgent` and implement `act(s)`. The kernel calls `step()`, and `s` is a syscall handle. Its calls go straight to `kernel.sync`, `.resources`, `.contexts`, `.checkpoints`, `.capabilities`, `.ipc` and `.metrics`. LabOS adds only what the kernel leaves to the platform: a mock LLM (normal, outage and stalled providers), a tool registry with capability requirements, the subprocess sandbox, and three bounded mailboxes (REJECT, DROP and BLOCK).
* **Evidence:** checks read three sources: `kernel.journal`, which records every kernel decision; `kernel.events`, the audit trail; and facts the agents record about themselves.
* **Operator actions:** pause, resume, cancel, capability revocation and REST calls are one-shot hooks. They fire concurrently while `Kernel.run()` is running.

## Missions

| Mission | Kernel configuration | Purpose |
|---|---|---|
| M1 Main shift | priority + aging, 8-page memory, IPC timeout 1 s | every department at once (52 scenarios) |
| M2 Fair-share hour | `default_scheduler = weighted_fair` | fair-share scheduling |
| M3 Lockdown | sandbox disabled, `default_capabilities = [telemetry.read]` | config-driven security |
| M4 Hiring freeze | `max_processes = 6` | global process limit |
| M5 Control room | real FastAPI router via `httpx.ASGITransport` | REST operations on the live kernel |
| M6 Radio silence | `ipc_wait_timeout = None`, `stall_timeout = 0.5` | stall detection |
| M7 Overtime | `run(max_seconds=1)` | wall-clock budget |
| M8 Step budget | `run(max_steps=25)` | step ceiling |
| M9 SDK onboarding | `@agent_os.register` + `spawn_registered()` | SDK and AutoWrapper |

## Scenarios

| ID | Area | What is forced to happen | Verified |
|---|---|---|---|
| S01 | Scheduling | Prio-10 FlightDirector among 87 agents | first step of the mission |
| S02 | Scheduling | Prio-1 janitor vs three prio-7 crunchers | aging schedules it while the crunchers are still runnable |
| S03 | Scheduling | Agent returns `YIELD` every step | stays runnable, finishes |
| S04 | Scheduling | Tenants weighted 1:2:4 | ≈1:2:4 CPU share (**known bug**) |
| S05 | IPC | Dispatcher → 3 Analysts → Aggregator | WAITING(IPC) parks; correlation IDs match |
| S06 | IPC | 8 messages into a capacity-3 REJECT mailbox | 3 delivered, 5 `IPC_DROPPED`, oldest kept |
| S07 | IPC | Same into a DROP mailbox | all accepted, only the newest 3 survive |
| S08 | IPC | 3rd send into a full BLOCK mailbox | sender blocks inside its step; step timeout ends it, loop never freezes |
| S09 | IPC | Two senders × 5 messages | per-sender FIFO, sequence numbers 0..4 |
| S10 | IPC | Waiting for a reply from a crashed peer | IPC deadline wakes it with `ipc_timed_out` |
| S11 | IPC | Mail to a dead process and to PID 9999 | refused (**known bug**) |
| S12 | Deadlock | AB/BA lock order | 2-cycle found; lowest priority restarted; both finish |
| S13 | Deadlock | Dining philosophers | 3-cycle; victim Philosopher-0; all eat |
| S14 | Deadlock | Crossed 1-slot **semaphores** | cycle through semaphores detected and resolved |
| S15 | Deadlock | Victim has restart `NEVER` | terminated, its lock reclaimed, survivor finishes |
| S16 | Sync | Priority inversion | owner boosted 2→9 by the kernel, released early, restored |
| S17 | Sync | 4 jobs, 2-slot semaphore | peak 2 holders, the rest BLOCKED, all finish |
| S18 | Sync | Queue forced 1,2,3 with priorities 3,6,8 | lock passed to waiters in queue order (FIFO), not by priority |
| S19 | Sync | Agent exits holding a lock | leak detected; lock handed to the waiter |
| S20 | Sync | Re-entrant acquire | `LockError` → failure; lock freed |
| S21 | Sync | Cancel a BLOCKED waiter | removed from the queue; hand-off skips it |
| S22–S26 | Quotas | tokens, LLM calls, steps, tool calls, wall time | each killed with `RESOURCE_LIMIT`, never restarted |
| S27–S30 | Supervisor | NEVER, ONCE, N_TIMES recovery, crash loop | restart counts match each policy; the crash loop stops after 3 restarts |
| S31 | Supervisor | EXPONENTIAL_BACKOFF | 0.15 → 0.3 → 0.6 s, and the agent really sleeps each delay |
| S32 | Supervisor | Step hangs 10 s | 0.4 s step timeout (`TOOL_TIMEOUT`); restart succeeds |
| S33 | Supervisor | LLM outage | `LLM_FAILURE`; retry succeeds |
| S34 | Supervisor | LLM provider stalls | `LLM_TIMEOUT`; retry succeeds |
| S35 | Supervisor | Agent *returns* `FAILED` | handled like a crash; restart succeeds |
| S36 | Memory | Power loss at batch 6 of 10 | resumes from the checkpoint; each batch runs exactly once |
| S37 | Memory | 12 pages into an 8-page budget + 2 pinned | LRU swap-outs; page fault restores content; pinned pages stay |
| S38 | Memory | Three page updates | versions 2,3,4; latest content readable |
| S39 | Memory | Pin more than the budget | kernel survives; every context freed at exit |
| S40 | Security | Missing capability, granted capability, live revocation | denied / allowed / cut off right after revocation |
| S41 | Security | Sandbox run, runaway subprocess, no `sys.exec` | stdout captured; killed at 0.5 s; denied |
| S42 | Security | Default capabilities | inherited when none given; replaced by explicit caps |
| S43 | Security | Sandbox disabled in config | `SANDBOX_FAILURE` |
| S44 | Lifecycle | Pause / resume | zero steps while paused; finishes |
| S45 | Lifecycle | Pause while **asleep** | expired sleep timer doesn't wake a paused agent |
| S46 | Lifecycle | Cancel a runaway holding a lock | CANCELLED → TERMINATED; lock reclaimed; waiter finishes |
| S47 | Lifecycle | Cancel while WAITING for mail | terminated cleanly |
| S48 | Lifecycle | 4 children, limit 3, parent crashes | 4th refused; children cascade-terminated |
| S49 | Lifecycle | Director → Manager → Intern | orphan cascade reaches grandchildren |
| S50 | Lifecycle | `orphan_policy=KEEP` | child outlives its parent and finishes |
| S51 | Lifecycle | `max_processes=6`; spawn a non-agent | 6th process refused; `TypeError` |
| S52 | Runtime | Two agents wait on each other forever | stall detected; both terminated |
| S53 | Runtime | `run(max_seconds=1)` | survivors terminated at the budget |
| S54 | Runtime | `run(max_steps=25)` | exactly 25 steps; survivor left READY |
| S55 | SDK | `@register` with steps, `init_args`, sync method, crashing `run()` | AutoWrapper → FAILED → restart → success |
| S56 | Platform | REST: `POST /processes`, `POST /ipc/send`, `GET /health` `/processes` `/events` | REST-spawned agent runs to completion; REST message wakes a waiter |
| S57 | Platform | REST cancel of a lock holder | lock reclaimed (**known bug**) |
| S58 | Platform | REST pause | process paused (**known bug**) |
| S59 | Platform | MetricsCollector | steps/failures/restarts/deadlocks equal the journal; LLM/tool/IPC metered |
| S60 | Platform | Audit trail | full lifecycle event sequence; every subsystem emitted events; everything TERMINATED |
| S61 | Platform | SQLite persistence | processes + deadlock events round-trip through `Repository` |
| S62 | Platform | Illegal transitions | READY→COMPLETED/FAILED/BLOCKED/WAITING rejected; TERMINATED is final |

## Agent-OS bugs found by the showcase, now fixed

| Scenario | Bug | Fix |
|---|---|---|
| S04 | `WeightedFairScheduler` gave each runnable process its weight on every pick but took back only 1 from the winner. The deficits diverged and the heaviest tenant took the CPU: 0/10/60 instead of ≈10/20/40. | The winner now pays back the *total* runnable weight (smooth weighted round-robin). Weights 1:2:4 get exactly 10/20/40 of 70 picks, interleaved. `src/agent_os/scheduler/weighted_fair.py` |
| S11 | `IPCManager.send()` reported mail to a dead process, or to a PID that never existed, as `DELIVERED` and queued it forever. | An optional receiver check (`set_receiver_check`), which the kernel wires to every mailbox it owns. Such mail is refused with `IPC_DROPPED`, and a terminated process's unread mail is discarded (`discard_mailbox`). `ipc_manager.py`, `sdk/kernel.py` |
| S57 | `POST /processes/{pid}/cancel` called `ProcessManager.cancel()` directly. The process was left CANCELLED with its locks, and agents waiting on those locks stalled. | The routes now go through the kernel (`use_kernel`): locks are reclaimed and handed on, the process reaches TERMINATED, and the orphan policy applies. The server (`agent_os.api.app`) now boots a real `sdk.Kernel`. `routes.py`, `app.py` |
| S58 | `POST /processes/{pid}/pause` only acted on a RUNNING process. Between steps a process is READY, so the API answered `paused` and nothing happened. | The routes call `kernel.pause/resume`. `ProcessManager.pause()` also handles READY, and the API answers 409 if the process can't be paused. `routes.py`, `process_manager.py` |

[tests/test_bugfixes.py](../tests/test_bugfixes.py) holds the regression tests. A scenario can still be marked
`known_bug="..."` to document a new defect: it then reports KNOWN, and pytest runs it as `xfail(strict=True)`.

Still visible in the evidence, though no scenario fails on them:
* **Token overshoot (S22):** the token quota is checked after the tokens are charged, so an agent can exceed its budget by up to one call.
* **Pinned-page over-commit (S39):** when every page is pinned, `ContextManager` loads more pages than the memory budget allows instead of refusing.

## Adding a scenario

```python
@scenario("S63", "M1", "Sync", "My edge case")
class _:
    async def setup(c):
        await c.spawn(MyAgent(), name="Mine", priority=5, restart="ONCE",
                      limits=ResourceLimits(token_limit=500), caps=["net.http"])
        c.when("operator action", lambda: c.board.get("ready"),
               lambda: c.k.cancel(c.os.pid("Mine")))

    async def verify(c):
        return [Check("it did the thing", await c.state("Mine") == "TERMINATED",
                      str(c.journal("cancel", "Mine")))]
```

```python
class MyAgent(LabAgent):
    async def act(self, s):
        if not await s.acquire("db"):
            return s.BLOCK                  # kernel wakes you when the lock is handed over
        await s.llm("plan", 20, 40)         # metered, quota-checked
        await s.release("db")
        return s.done()
```

Syscalls:
* **LLM, tools and sandbox:** `s.llm`, `s.tool`, `s.sandbox`
* **IPC:** `s.send(to, …, box=main|reject|drop|block)`, `s.recv`
* **Locks and semaphores:** `s.acquire`/`release`/`holds`, `s.sem_acquire`/`sem_release`
* **Memory:** `s.page_add`/`page_read`/`page_update`/`page_loaded`
* **Checkpoints and child processes:** `s.checkpoint`, `s.spawn`
* **Step results:** `s.sleep()`, `s.wait_ipc()`, `s.CONTINUE`, `s.YIELD`, `s.BLOCK`, `s.done()`, `s.failed()`
* **Recording and process state:** `s.record`, `s.ipc_timed_out`, `s.restarts`, `s.priority`
