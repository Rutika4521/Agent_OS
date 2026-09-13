"""Agent-OS Supervisor — Failure types and records."""
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

class FailureType(str, Enum):
    AGENT_EXCEPTION = "AGENT_EXCEPTION"
    LLM_TIMEOUT = "LLM_TIMEOUT"
    LLM_FAILURE = "LLM_FAILURE"
    TOOL_FAILURE = "TOOL_FAILURE"
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"
    IPC_FAILURE = "IPC_FAILURE"
    CONTEXT_FAILURE = "CONTEXT_FAILURE"
    SANDBOX_FAILURE = "SANDBOX_FAILURE"
    CANCELLATION = "CANCELLATION"
    UNKNOWN = "UNKNOWN"

@dataclass
class FailureRecord:
    failure_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    process_id: int = 0
    failure_type: FailureType = FailureType.UNKNOWN
    error_message: str = ""
    timestamp: float = field(default_factory=time.time)
    context: dict[str, Any] = field(default_factory=dict)
