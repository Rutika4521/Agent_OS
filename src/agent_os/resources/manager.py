"""
Agent-OS Resources — Manager

Centralizes resource accounting and quota enforcement (§26-§29).
No agent may bypass the resource manager.
"""

from __future__ import annotations

from enum import Enum

from agent_os.config.settings import Settings, get_settings
from agent_os.kernel.agent_process import AgentProcess


class ResourceExceededPolicy(str, Enum):
    """Policy when a resource limit is exceeded (§27)."""
    BLOCK = "BLOCK"
    FAIL = "FAIL"
    TERMINATE = "TERMINATE"


class ResourceLimitExceeded(Exception):
    """Raised when a resource quota is exceeded."""

    def __init__(self, resource_type: str, process_id: int):
        self.resource_type = resource_type
        self.process_id = process_id
        super().__init__(
            f"Resource limit exceeded: {resource_type} for process {process_id}"
        )


class ResourceManager:
    """
    Central resource accounting and enforcement (§26).

    Methods:
        can_execute, consume_tokens, consume_llm_call,
        consume_tool_call, consume_step, check_wall_time,
        release_resources
    """

    def __init__(self, settings: Settings | None = None):
        self._settings = settings or get_settings()
        policy_str = self._settings.process_defaults.resource_exceeded_policy
        try:
            self._policy = ResourceExceededPolicy(policy_str)
        except ValueError:
            self._policy = ResourceExceededPolicy.FAIL

    def can_execute(self, process: AgentProcess) -> bool:
        """Check if the process has remaining quota for at least one more step."""
        limits = process.resource_limits
        usage = process.resource_usage

        if usage.steps >= limits.step_limit:
            return False
        if usage.tool_calls >= limits.tool_call_limit:
            return False
        if usage.llm_calls >= limits.llm_call_limit:
            return False
        if usage.total_tokens >= limits.token_limit:
            return False
        if self.check_wall_time(process):
            return False

        return True

    def consume_tokens(self, process: AgentProcess, input_tokens: int, output_tokens: int) -> None:
        """Update token usage and check quota (§27)."""
        usage = process.resource_usage
        usage.input_tokens += input_tokens
        usage.output_tokens += output_tokens
        usage.total_tokens += input_tokens + output_tokens

        if usage.total_tokens > process.resource_limits.token_limit:
            raise ResourceLimitExceeded("token_limit", process.process_id)

    def consume_llm_call(self, process: AgentProcess) -> None:
        """Increment LLM call count and check limit."""
        usage = process.resource_usage
        usage.llm_calls += 1

        if usage.llm_calls > process.resource_limits.llm_call_limit:
            raise ResourceLimitExceeded("llm_call_limit", process.process_id)

    def consume_tool_call(self, process: AgentProcess) -> None:
        """Increment tool call count and check limit."""
        usage = process.resource_usage
        usage.tool_calls += 1

        if usage.tool_calls > process.resource_limits.tool_call_limit:
            raise ResourceLimitExceeded("tool_call_limit", process.process_id)

    def consume_step(self, process: AgentProcess) -> None:
        """Increment step count and check limit (§28)."""
        usage = process.resource_usage
        usage.steps += 1

        if usage.steps > process.resource_limits.step_limit:
            raise ResourceLimitExceeded("step_limit", process.process_id)

    def check_wall_time(self, process: AgentProcess) -> bool:
        """Return True if wall time limit is exceeded (§29)."""
        return process.resource_usage.execution_time >= process.resource_limits.wall_time_limit

    def release_resources(self, process: AgentProcess) -> None:
        """Reset usage counters (for restart)."""
        process.resource_usage.reset()
