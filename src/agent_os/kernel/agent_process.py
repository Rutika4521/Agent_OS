"""
Agent-OS Kernel — AgentProcess

Defines the AgentProcess dataclass that wraps every agent
with OS-managed metadata (§15).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from agent_os.kernel.state_machine import ProcessState, WaitReason
from agent_os.resources.quota import ResourceLimits
from agent_os.resources.usage import ResourceUsage


@dataclass
class AgentProcess:
    """
    A managed agent process (§15).

    Every agent becomes an AgentProcess when registered with Agent-OS.
    The application defines agent behavior; Agent-OS manages the process.
    """

    # Identity
    process_id: int
    agent: Any  # Agent protocol instance
    name: str = ""

    # Lifecycle
    state: ProcessState = ProcessState.CREATED
    waiting_for: WaitReason | None = None

    # Scheduling
    priority: int = 5
    weight: int = 1
    _original_priority: int | None = field(default=None, repr=False)

    # Resources
    resource_limits: ResourceLimits = field(default_factory=ResourceLimits)
    resource_usage: ResourceUsage = field(default_factory=ResourceUsage)

    # Context
    context_id: str | None = None

    # Security
    capabilities: list[str] = field(default_factory=list)

    # Hierarchy
    parent_process_id: int | None = None

    # Reliability
    restart_count: int = 0
    failure_count: int = 0
    checkpoint_id: str | None = None
    restart_policy: str = "N_TIMES"

    # Timestamps
    creation_time: float = field(default_factory=time.time)
    start_time: float | None = None
    completion_time: float | None = None
    last_scheduled_time: float | None = None
    ready_since: float | None = None

    # Scheduling metadata
    deficit: float = 0.0  # For weighted fair scheduling

    @property
    def original_priority(self) -> int:
        """Get the original base priority (before any inheritance)."""
        return self._original_priority if self._original_priority is not None else self.priority

    def set_inherited_priority(self, new_priority: int) -> None:
        """Temporarily boost priority for priority inheritance (§23)."""
        if self._original_priority is None:
            self._original_priority = self.priority
        self.priority = max(self.priority, new_priority)

    def restore_priority(self) -> None:
        """Restore original priority after priority inheritance."""
        if self._original_priority is not None:
            self.priority = self._original_priority
            self._original_priority = None
