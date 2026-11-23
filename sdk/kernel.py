"""
Agent-OS SDK — Kernel

High-level bootstrap helper that wires together all OS subsystems
and runs registered agents to completion.

Usage:
    import agent_os

    @agent_os.register(priority=7, name="MyAgent")
    class MyAgent:
        async def run(self) -> str:
            return "done"

    async def main():
        kernel = agent_os.Kernel()
        await kernel.boot()
        await kernel.spawn_registered()
        await kernel.run()

    asyncio.run(main())
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from agent_os.config.settings import Settings
from agent_os.kernel.agent_process import AgentProcess
from agent_os.kernel.process_manager import ProcessManager
from agent_os.kernel.process_table import ProcessTable
from agent_os.kernel.state_machine import ProcessState, StepStatus
from agent_os.ipc.ipc_manager import IPCManager
from agent_os.memory.context_manager import ContextManager
from agent_os.memory.checkpoint import CheckpointManager
from agent_os.metrics.events import EventManager
from agent_os.metrics.collector import MetricsCollector
from agent_os.resources.manager import ResourceManager
from agent_os.supervisor.supervisor import Supervisor
from agent_os.supervisor.restart import RestartManager

from sdk.agent import AgentContext
from sdk.registry import get_registry, AgentRegistration
from sdk.wrapper import AutoWrapper

logger = logging.getLogger(__name__)


class KernelNotBootedError(RuntimeError):
    """Raised when kernel methods are called before boot()."""
    pass


class Kernel:
    """
    High-level helper that bootstraps all Agent-OS subsystems.

    This is the recommended entry-point for applications using the SDK.
    It initialises all subsystems (ProcessManager, IPC, Supervisor, etc.)
    and exposes a simple interface to spawn and run agents.

    Lifecycle:
        kernel = Kernel()
        await kernel.boot()          # initialise subsystems
        await kernel.spawn_registered()  # spawn @register-decorated agents
        await kernel.run()           # drive all processes to completion
        await kernel.shutdown()      # clean up

    Advanced usage:
        proc = await kernel.spawn(MyAgent(), name="Worker", priority=8)
    """

    def __init__(self, settings: Settings | None = None):
        self._settings = settings or Settings()
        self._booted = False

        # Subsystems (set by boot())
        self._event_manager: EventManager | None = None
        self._process_table: ProcessTable | None = None
        self._process_manager: ProcessManager | None = None
        self._resource_manager: ResourceManager | None = None
        self._ipc_manager: IPCManager | None = None
        self._context_manager: ContextManager | None = None
        self._checkpoint_manager: CheckpointManager | None = None
        self._restart_manager: RestartManager | None = None
        self._supervisor: Supervisor | None = None
        self._metrics_collector: MetricsCollector | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def boot(self) -> None:
        """Initialise all OS subsystems. Must be called before spawn/run."""
        if self._booted:
            return

        self._event_manager = EventManager()
        self._process_table = ProcessTable()
        self._process_manager = ProcessManager(
            self._process_table, self._event_manager, self._settings
        )
        self._resource_manager = ResourceManager(self._settings)
        self._ipc_manager = IPCManager(self._settings, self._event_manager)
        self._context_manager = ContextManager(self._settings, self._event_manager)
        self._checkpoint_manager = CheckpointManager(self._event_manager)
        self._restart_manager = RestartManager(self._settings.supervisor)
        self._supervisor = Supervisor(
            self._process_manager,
            self._restart_manager,
            self._event_manager,
            self._checkpoint_manager,
        )
        self._metrics_collector = MetricsCollector()

        self._booted = True
        logger.info("[Kernel] Booted successfully.")

    async def shutdown(self) -> None:
        """Gracefully shut down the kernel."""
        if not self._booted:
            return
        logger.info("[Kernel] Shutting down.")
        self._booted = False

    # ------------------------------------------------------------------
    # Process Spawning
    # ------------------------------------------------------------------

    async def spawn(
        self,
        agent: Any,
        *,
        name: str = "",
        priority: int | None = None,
        weight: int | None = None,
        restart_policy: str | None = None,
    ) -> AgentProcess:
        """
        Spawn a single agent as a managed process.

        The agent must implement the step(ctx) -> AgentStepResult protocol
        OR be wrapped with AutoWrapper first.

        Args:
            agent:          Agent instance (must have step() method).
            name:           Human-readable process name.
            priority:       Scheduling priority 1–10.
            weight:         Weight for weighted-fair scheduling.
            restart_policy: "N_TIMES" | "ONCE" | "NEVER" | "EXPONENTIAL_BACKOFF"

        Returns:
            The spawned AgentProcess in READY state.
        """
        self._require_booted()
        return await self._process_manager.spawn(
            agent,
            name=name,
            priority=priority,
            weight=weight,
            restart_policy=restart_policy,
        )

    async def spawn_registered(self) -> list[AgentProcess]:
        """
        Spawn all agents decorated with @agent_os.register().

        Reads the global registry, instantiates each class, wraps it in
        AutoWrapper, and spawns it as a managed process.

        Returns:
            List of created AgentProcess objects in READY state.
        """
        self._require_booted()
        processes: list[AgentProcess] = []
        for reg in get_registry():
            proc = await self._spawn_from_registration(reg)
            processes.append(proc)
        return processes

    async def _spawn_from_registration(self, reg: AgentRegistration) -> AgentProcess:
        """Instantiate, wrap and spawn a single registered agent."""
        # Instantiate the class
        instance = reg.cls(*reg.init_args, **reg.init_kwargs)

        # Wrap in AutoWrapper (handles run/execute/__call__ auto-detection)
        wrapper = AutoWrapper(
            agent=instance,
            method=reg.method,
            steps=reg.steps,
        )

        return await self._process_manager.spawn(
            wrapper,
            name=reg.name,
            priority=reg.priority,
            weight=reg.weight,
            restart_policy=reg.restart_policy,
        )

    # ------------------------------------------------------------------
    # Run Loop
    # ------------------------------------------------------------------

    async def run(self, *, max_steps: int = 10_000, tick_interval: float = 0.0) -> None:
        """
        Drive all READY/RUNNING processes to completion.

        Repeatedly picks READY processes and calls their step() until all
        processes have reached a terminal state (COMPLETED, FAILED, CANCELLED,
        or TERMINATED).

        Args:
            max_steps:      Safety ceiling — stop after this many total steps
                            across all processes (prevents infinite loops).
            tick_interval:  Optional sleep between ticks (seconds). 0 = as fast
                            as possible.
        """
        self._require_booted()
        steps_taken = 0

        while steps_taken < max_steps:
            ready = await self._process_manager.list(state=ProcessState.READY)
            if not ready:
                # Check if anything is still active
                active = []
                for s in (ProcessState.RUNNING, ProcessState.WAITING, ProcessState.BLOCKED):
                    active.extend(await self._process_manager.list(state=s))
                if not active:
                    break  # All done

            # Run one step per ready process per tick
            for proc in ready:
                await self._tick_process(proc)
                steps_taken += 1

            if tick_interval > 0:
                await asyncio.sleep(tick_interval)

        logger.info("[Kernel] Run loop complete. Steps taken: %d", steps_taken)

    async def _tick_process(self, proc: AgentProcess) -> None:
        """Execute one step of a process."""
        pm = self._process_manager
        pid = proc.process_id

        # READY → RUNNING
        try:
            await pm.set_state(pid, ProcessState.RUNNING)
        except Exception:
            return

        ctx = AgentContext(process_id=pid)
        try:
            result = await proc.agent.step(ctx)
        except Exception as exc:
            logger.warning("[Kernel] Agent %d raised exception: %s", pid, exc)
            await pm.set_state(pid, ProcessState.FAILED)
            return

        # Interpret result
        if result.status == StepStatus.COMPLETED:
            await pm.set_state(pid, ProcessState.COMPLETED)
            await pm.terminate(pid)
        elif result.status == StepStatus.FAILED:
            await pm.set_state(pid, ProcessState.FAILED)
        elif result.status in (StepStatus.WAIT, StepStatus.YIELD):
            from agent_os.kernel.state_machine import WaitReason
            await pm.set_state(pid, ProcessState.WAITING, wait_reason=WaitReason.SLEEP)
            # Auto-resume for the demo scheduler
            await pm.set_state(pid, ProcessState.READY)
        else:
            # CONTINUE → back to READY
            await pm.set_state(pid, ProcessState.READY)

    # ------------------------------------------------------------------
    # Subsystem Properties (for advanced use)
    # ------------------------------------------------------------------

    @property
    def pm(self) -> ProcessManager:
        """The ProcessManager subsystem."""
        self._require_booted()
        return self._process_manager

    @property
    def ipc(self) -> IPCManager:
        """The IPCManager subsystem."""
        self._require_booted()
        return self._ipc_manager

    @property
    def events(self) -> EventManager:
        """The EventManager subsystem."""
        self._require_booted()
        return self._event_manager

    @property
    def supervisor(self) -> Supervisor:
        """The Supervisor subsystem."""
        self._require_booted()
        return self._supervisor

    @property
    def metrics(self) -> MetricsCollector:
        """The MetricsCollector subsystem."""
        self._require_booted()
        return self._metrics_collector

    @property
    def settings(self) -> Settings:
        """The Settings object used by this kernel."""
        return self._settings

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_booted(self) -> None:
        if not self._booted:
            raise KernelNotBootedError(
                "Kernel is not booted. Call await kernel.boot() first."
            )
