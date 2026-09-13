"""
Agent-OS Resources — Usage tracking

Tracks resource consumption per agent process (§25).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ResourceUsage:
    """
    Current resource usage for an agent process (§25).

    Updated by the ResourceManager after each operation.
    """
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    llm_calls: int = 0
    tool_calls: int = 0
    steps: int = 0
    execution_time: float = 0.0
    child_processes: int = 0

    def reset(self) -> None:
        """Reset all usage counters to zero."""
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0
        self.llm_calls = 0
        self.tool_calls = 0
        self.steps = 0
        self.execution_time = 0.0
        self.child_processes = 0
