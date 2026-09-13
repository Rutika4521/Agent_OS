"""
Agent-OS Resources — Quota definitions

Defines resource limits and usage tracking dataclasses (§25).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ResourceLimits:
    """
    Resource limits for an agent process (§25).

    These are populated from configuration defaults and may be
    overridden per-process at creation time.
    """
    token_limit: int = 5000
    llm_call_limit: int = 50
    tool_call_limit: int = 20
    step_limit: int = 100
    wall_time_limit: float = 300.0
    child_process_limit: int = 10

    @classmethod
    def from_config(cls, config_resources) -> ResourceLimits:
        """Create ResourceLimits from a config ResourceDefaults object."""
        return cls(
            token_limit=config_resources.token_limit,
            llm_call_limit=config_resources.llm_call_limit,
            tool_call_limit=config_resources.tool_call_limit,
            step_limit=config_resources.step_limit,
            wall_time_limit=config_resources.wall_time_limit,
            child_process_limit=config_resources.child_process_limit,
        )
