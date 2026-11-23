"""
Agent-OS SDK Example — Full End-to-End Demo

Demonstrates how to use the Agent-OS SDK decorator API to register,
spawn, and run multiple agents with zero manual OS wiring.

Run from the project root:
    python examples/sdk_example/main.py

Requires:
    pip install pyyaml fastapi
    (All other dependencies are built-in or in the project itself.)
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# ── Path bootstrap ────────────────────────────────────────────────────────────
# src/  → contains the `agent_os` package
# ROOT  → contains the `sdk` package (sdk/ is a sub-package of ROOT, not standalone)
_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "src"))  # for `import agent_os`
sys.path.insert(0, str(_ROOT))          # for `import sdk` (sdk/ lives at project root)
# ─────────────────────────────────────────────────────────────────────────────

import agent_os  # noqa: E402  (after sys.path setup)


# ── Agent Definitions ─────────────────────────────────────────────────────────

@agent_os.register(
    priority=9,
    name="Researcher",
    steps=[
        {"args": ["quantum computing"]},
        {"args": ["large language models"]},
        {"args": ["agent operating systems"]},
    ],
)
class ResearchAgent:
    """
    A research agent that processes topics one step at a time.
    Each step receives a topic and produces a research summary.
    """

    def __init__(self):
        self.results: list[str] = []

    async def run(self, topic: str) -> str:
        # Simulate research work (in real use: call an LLM or tool)
        summary = f"[Research] Gathered findings on '{topic}'"
        self.results.append(summary)
        print(f"  ResearchAgent step: {summary}")
        return summary


@agent_os.register(
    priority=7,
    name="Analyst",
    steps=[
        {"args": ["step-1 analysis"]},
        {"args": ["step-2 synthesis"]},
    ],
)
class AnalystAgent:
    """
    An analyst agent that analyses data in two phases.
    Demonstrates multi-step agents alongside other agents.
    """

    async def run(self, phase: str) -> str:
        output = f"[Analyst] Completed {phase}"
        print(f"  AnalystAgent step: {output}")
        return output


@agent_os.register(
    priority=5,
    name="Writer",
    # No explicit steps → one step, no arguments
)
class WriterAgent:
    """
    A writer agent that produces a final report in a single step.
    Demonstrates single-step agents (no 'steps' needed).
    """

    async def run(self) -> str:
        output = "[Writer] Final report compiled and ready."
        print(f"  WriterAgent step: {output}")
        return output


@agent_os.register(
    priority=3,
    name="Monitor",
    # Callable-style agent — uses __call__ instead of run()
)
class MonitorAgent:
    """
    A monitor agent implemented as a callable.
    Demonstrates that AutoWrapper auto-detects __call__ as the method.
    """

    async def __call__(self) -> str:
        output = "[Monitor] All systems nominal."
        print(f"  MonitorAgent step: {output}")
        return output


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    print("=" * 60)
    print("  Agent-OS SDK Demo")
    print("=" * 60)

    # 1. Create and boot the kernel (wires up ALL OS subsystems)
    kernel = agent_os.Kernel()
    await kernel.boot()
    print(f"\n[Kernel] Booted. Registered agents: {agent_os.registered_count()}")

    # 2. Spawn all @agent_os.register()-decorated agents
    processes = await kernel.spawn_registered()
    print(f"[Kernel] Spawned {len(processes)} processes:")
    for proc in processes:
        print(f"  PID={proc.process_id}  name={proc.name!r}  priority={proc.priority}")

    print("\n[Kernel] Running agents...\n")

    # 3. Drive all agents to completion
    await kernel.run()

    print("\n" + "=" * 60)
    print("[Kernel] All agents completed.")

    # 4. Show final process states
    all_procs = await kernel.pm.list()
    print(f"\nFinal process states ({len(all_procs)} total):")
    for proc in all_procs:
        print(f"  PID={proc.process_id}  name={proc.name!r}  state={proc.state.value}")

    # 5. Show event log summary
    history = await kernel.events.get_history()
    print(f"\nEvent log: {len(history)} events recorded.")

    # 6. Advanced: send an IPC message between two processes (if ≥2 existed)
    if len(processes) >= 2:
        sender   = processes[0].process_id
        receiver = processes[1].process_id
        await kernel.ipc.send(sender, receiver, {"msg": "hello from IPC demo"})
        msg = await kernel.ipc.receive(receiver)
        print(f"\nIPC demo: {sender} → {receiver}: {msg.payload if msg else '(no message)'}")

    await kernel.shutdown()
    print("\n[Kernel] Shutdown complete.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
