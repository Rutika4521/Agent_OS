"""
Agent-OS Kernel — State Machine

Defines process states, wait reasons, step statuses, step results,
and the state machine that enforces valid transitions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ProcessState(str, Enum):
    """All possible states of an AgentProcess (§12)."""
    CREATED = "CREATED"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RESTARTING = "RESTARTING"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"
    TERMINATED = "TERMINATED"


class WaitReason(str, Enum):
    """Reasons a process may enter the WAITING state (§13)."""
    LLM = "LLM"
    TOOL = "TOOL"
    IPC = "IPC"
    RESOURCE = "RESOURCE"
    LOCK = "LOCK"
    SLEEP = "SLEEP"


class StepStatus(str, Enum):
    """Possible outcomes of a single agent step (§11)."""
    CONTINUE = "CONTINUE"
    YIELD = "YIELD"
    WAIT = "WAIT"
    BLOCK = "BLOCK"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


# ---------------------------------------------------------------------------
# Step Result
# ---------------------------------------------------------------------------

@dataclass
class AgentStepResult:
    """Result returned by an agent's step() method (§11)."""
    status: StepStatus
    output: Any | None = None
    wait_reason: WaitReason | None = None
    messages: list = field(default_factory=list)
    resource_usage: Any | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class InvalidStateTransition(Exception):
    """Raised when an invalid state transition is attempted."""

    def __init__(self, current: ProcessState, target: ProcessState):
        self.current = current
        self.target = target
        super().__init__(
            f"Invalid state transition: {current.value} -> {target.value}"
        )


# ---------------------------------------------------------------------------
# State Machine
# ---------------------------------------------------------------------------

# Valid transitions per §14
_VALID_TRANSITIONS: dict[ProcessState, set[ProcessState]] = {
    ProcessState.CREATED: {
        ProcessState.READY,
    },
    ProcessState.READY: {
        ProcessState.RUNNING,
    },
    ProcessState.RUNNING: {
        ProcessState.READY,
        ProcessState.WAITING,
        ProcessState.BLOCKED,
        ProcessState.COMPLETED,
        ProcessState.FAILED,
        ProcessState.CANCELLING,
    },
    ProcessState.WAITING: {
        ProcessState.READY,
        ProcessState.CANCELLING,
        ProcessState.TERMINATED,
    },
    ProcessState.BLOCKED: {
        ProcessState.READY,
        ProcessState.CANCELLING,
        ProcessState.TERMINATED,
    },
    ProcessState.FAILED: {
        ProcessState.RESTARTING,
        ProcessState.TERMINATED,
    },
    ProcessState.RESTARTING: {
        ProcessState.READY,
        ProcessState.FAILED,
    },
    ProcessState.CANCELLING: {
        ProcessState.CANCELLED,
    },
    ProcessState.COMPLETED: {
        ProcessState.TERMINATED,
    },
    ProcessState.CANCELLED: {
        ProcessState.TERMINATED,
    },
    ProcessState.TERMINATED: set(),  # terminal state
}


class StateMachine:
    """
    Enforces valid process state transitions.

    The state machine is authoritative: no transition may occur
    unless it is listed in the valid transition table (§14).
    Invalid transitions raise InvalidStateTransition.
    """

    @staticmethod
    def valid_transitions() -> dict[ProcessState, set[ProcessState]]:
        """Return a copy of the valid transitions table."""
        return {k: set(v) for k, v in _VALID_TRANSITIONS.items()}

    @staticmethod
    def can_transition(current: ProcessState, target: ProcessState) -> bool:
        """Check whether a transition is valid without raising."""
        allowed = _VALID_TRANSITIONS.get(current, set())
        return target in allowed

    @staticmethod
    def transition(current: ProcessState, target: ProcessState) -> ProcessState:
        """
        Validate and execute a state transition.

        Args:
            current: The current process state.
            target: The desired next state.

        Returns:
            The new state (target) if the transition is valid.

        Raises:
            InvalidStateTransition: If the transition is not allowed.
        """
        if not StateMachine.can_transition(current, target):
            raise InvalidStateTransition(current, target)
        return target

    @staticmethod
    def is_terminal(state: ProcessState) -> bool:
        """Check whether a state is terminal (no outgoing transitions)."""
        return len(_VALID_TRANSITIONS.get(state, set())) == 0

    @staticmethod
    def is_runnable(state: ProcessState) -> bool:
        """Check whether a process in this state is eligible for scheduling."""
        return state == ProcessState.READY

    @staticmethod
    def is_active(state: ProcessState) -> bool:
        """Check whether a process is in an active (non-terminal) state."""
        return state not in {
            ProcessState.COMPLETED,
            ProcessState.CANCELLED,
            ProcessState.TERMINATED,
        }
