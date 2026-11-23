"""
Agent-OS SDK — Decorator Registry

Provides the @agent_os.register() decorator so any class can be
plugged into Agent-OS without writing a manual wrapper.

Usage:
    import agent_os

    @agent_os.register(priority=7, name="Planner")
    class PlannerAgent:
        async def run(self, task: str) -> str:
            return f"Plan for: {task}"

    # Boot and run
    kernel = agent_os.Kernel()
    await kernel.boot()
    await kernel.spawn_registered()
    await kernel.run()
"""
from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Type

from sdk.wrapper import AutoWrapper


@dataclass
class AgentRegistration:
    """Metadata stored when @agent_os.register() is called."""
    cls: Type
    name: str
    priority: int
    weight: int
    restart_policy: str
    method: str | None
    steps: list[dict] | None
    init_args: list
    init_kwargs: dict


# Module-level registry — populated by @agent_os.register()
_registry: list[AgentRegistration] = []


def register(
    *,
    name: str = "",
    priority: int = 5,
    weight: int = 1,
    restart_policy: str = "N_TIMES",
    method: str | None = None,
    steps: list[dict] | None = None,
    init_args: list | None = None,
    init_kwargs: dict | None = None,
):
    """
    Decorator: register a class as an Agent-OS managed agent.

    Args:
        name:           Human-readable process name (default: class name).
        priority:       Scheduling priority 1-10 (higher = runs first).
        weight:         Weight for weighted-fair scheduling.
        restart_policy: "N_TIMES" | "ONCE" | "NEVER" | "EXPONENTIAL_BACKOFF"
        method:         Which method to call each step (auto-detected if omitted).
        steps:          List of {args, kwargs} dicts — one entry per step.
                        If omitted, one step with no arguments is run.
        init_args:      Positional args to pass to the class constructor.
        init_kwargs:    Keyword args to pass to the class constructor.

    Example:
        @agent_os.register(priority=9, name="Writer", steps=[
            {"args": ["write intro"]},
            {"args": ["write body"]},
            {"args": ["write conclusion"]},
        ])
        class WriterAgent:
            async def run(self, section: str) -> str:
                return f"Content for {section}"
    """
    def decorator(cls: Type) -> Type:
        reg = AgentRegistration(
            cls=cls,
            name=name or cls.__name__,
            priority=priority,
            weight=weight,
            restart_policy=restart_policy,
            method=method,
            steps=steps,
            init_args=init_args or [],
            init_kwargs=init_kwargs or {},
        )
        _registry.append(reg)
        # Attach metadata to the class for introspection
        cls._agent_os_registration = reg
        return cls

    return decorator


def get_registry() -> list[AgentRegistration]:
    """Return all registered agents."""
    return list(_registry)


def clear_registry() -> None:
    """Clear all registered agents. Useful for testing."""
    _registry.clear()


def registered_count() -> int:
    """How many agents have been registered."""
    return len(_registry)
