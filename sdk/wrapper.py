"""
Agent-OS SDK — Auto-Wrapper

Converts any existing agent class into a step()-based agent
that Agent-OS can manage, without modifying the original class.

Supports agents that expose:
    - async run(...)       → most common
    - async execute(...)   → alternative
    - async __call__(...) → callable agents

Usage:
    wrapper = AutoWrapper(MyAgent(), method="run", steps=[
        {"args": ["task 1"]},
        {"args": ["task 2"]},
    ])
    proc = await pm.spawn(wrapper, name="MyAgent", priority=5)
"""
from __future__ import annotations

import inspect
from typing import Any

from agent_os.kernel.state_machine import AgentStepResult, StepStatus
from sdk.agent import AgentContext


class AutoWrapper:
    """
    Wraps any existing agent object into the step() protocol.

    The wrapper calls the agent's method once per step, cycling
    through the provided steps list.

    Args:
        agent:      Your existing agent instance.
        method:     The method name to call each step (default: "run").
                    Falls back through: run → execute → __call__
        steps:      List of dicts with 'args' and/or 'kwargs' for each step.
                    If None, one step is run with no arguments.
        on_result:  Optional callable(result, step_index) → StepStatus
                    to decide what status to return. Default: COMPLETED on last step, CONTINUE otherwise.

    Example:
        wrapper = AutoWrapper(
            agent=PlannerAgent(),
            method="run",
            steps=[
                {"args": ["create outline"]},
                {"args": ["expand outline into full draft"]},
            ]
        )
    """

    def __init__(
        self,
        agent: Any,
        method: str | None = None,
        steps: list[dict] | None = None,
        on_result=None,
    ):
        self._agent = agent
        self._method_name = method or self._detect_method(agent)
        self._steps = steps or [{}]
        self._on_result = on_result
        self._current_step = 0
        self._last_output = None

        if not hasattr(agent, self._method_name):
            raise AttributeError(
                f"Agent {type(agent).__name__!r} has no method {self._method_name!r}. "
                f"Available methods: {[m for m in dir(agent) if not m.startswith('_')]}"
            )

    @staticmethod
    def _detect_method(agent: Any) -> str:
        """Auto-detect the callable method on the agent."""
        for name in ("run", "execute", "arun", "ainvoke", "invoke"):
            if hasattr(agent, name) and callable(getattr(agent, name)):
                return name
        if callable(agent):
            return "__call__"
        raise AttributeError(
            f"Cannot auto-detect callable method on {type(agent).__name__!r}. "
            "Pass method='your_method_name' explicitly."
        )

    async def step(self, ctx: AgentContext) -> AgentStepResult:
        """Called by Agent-OS once per scheduling tick."""
        if self._current_step >= len(self._steps):
            return AgentStepResult(status=StepStatus.COMPLETED, output=self._last_output)

        step_spec = self._steps[self._current_step]
        args   = step_spec.get("args", [])
        kwargs = step_spec.get("kwargs", {})

        method = getattr(self._agent, self._method_name)
        try:
            if inspect.iscoroutinefunction(method):
                result = await method(*args, **kwargs)
            else:
                result = method(*args, **kwargs)
        except Exception as e:
            return AgentStepResult(
                status=StepStatus.FAILED,
                output=None,
                error=str(e),
            )

        self._last_output = result
        self._current_step += 1

        # Custom status logic
        if self._on_result:
            status = self._on_result(result, self._current_step - 1)
        elif self._current_step >= len(self._steps):
            status = StepStatus.COMPLETED
        else:
            status = StepStatus.CONTINUE

        return AgentStepResult(status=status, output=result)

    @property
    def inner(self) -> Any:
        """Access the original agent object."""
        return self._agent

    @property
    def step_index(self) -> int:
        """Current step index (0-based)."""
        return self._current_step
