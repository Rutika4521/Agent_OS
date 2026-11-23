"""Tests for ProcessState, StepStatus, StateMachine, AgentStepResult."""
import pytest
from agent_os.kernel.state_machine import (
    ProcessState,
    StepStatus,
    WaitReason,
    AgentStepResult,
    StateMachine,
    InvalidStateTransition,
)


# ── ProcessState ──────────────────────────────────────────────────────────────

def test_all_states_exist():
    states = [
        "CREATED", "READY", "RUNNING", "WAITING", "BLOCKED",
        "COMPLETED", "FAILED", "RESTARTING", "CANCELLING", "CANCELLED", "TERMINATED",
    ]
    for s in states:
        assert ProcessState(s) is not None


def test_state_is_string_enum():
    assert ProcessState.READY == "READY"
    assert ProcessState.RUNNING == "RUNNING"


# ── StepStatus ────────────────────────────────────────────────────────────────

def test_all_step_statuses_exist():
    for s in ["CONTINUE", "YIELD", "WAIT", "BLOCK", "COMPLETED", "FAILED"]:
        assert StepStatus(s) is not None


# ── AgentStepResult ───────────────────────────────────────────────────────────

def test_agent_step_result_defaults():
    r = AgentStepResult(status=StepStatus.COMPLETED)
    assert r.output is None
    assert r.wait_reason is None
    assert r.messages == []
    assert r.error is None


def test_agent_step_result_with_output():
    r = AgentStepResult(status=StepStatus.CONTINUE, output="hello")
    assert r.output == "hello"


# ── StateMachine.can_transition ───────────────────────────────────────────────

@pytest.mark.parametrize("frm,to,expected", [
    (ProcessState.CREATED,    ProcessState.READY,      True),
    (ProcessState.READY,      ProcessState.RUNNING,    True),
    (ProcessState.RUNNING,    ProcessState.READY,      True),
    (ProcessState.RUNNING,    ProcessState.COMPLETED,  True),
    (ProcessState.RUNNING,    ProcessState.FAILED,     True),
    (ProcessState.RUNNING,    ProcessState.WAITING,    True),
    (ProcessState.RUNNING,    ProcessState.BLOCKED,    True),
    (ProcessState.RUNNING,    ProcessState.CANCELLING, True),
    (ProcessState.WAITING,    ProcessState.READY,      True),
    (ProcessState.FAILED,     ProcessState.RESTARTING, True),
    (ProcessState.RESTARTING, ProcessState.READY,      True),
    (ProcessState.COMPLETED,  ProcessState.TERMINATED, True),
    # Invalid transitions
    (ProcessState.READY,      ProcessState.COMPLETED,  False),
    (ProcessState.READY,      ProcessState.FAILED,     False),
    (ProcessState.CREATED,    ProcessState.RUNNING,    False),
    (ProcessState.TERMINATED, ProcessState.READY,      False),
    (ProcessState.COMPLETED,  ProcessState.READY,      False),
])
def test_can_transition(frm, to, expected):
    assert StateMachine.can_transition(frm, to) == expected


# ── StateMachine.transition ───────────────────────────────────────────────────

def test_transition_valid_returns_target():
    result = StateMachine.transition(ProcessState.CREATED, ProcessState.READY)
    assert result == ProcessState.READY


def test_transition_invalid_raises():
    with pytest.raises(InvalidStateTransition):
        StateMachine.transition(ProcessState.READY, ProcessState.COMPLETED)


def test_invalid_state_transition_message():
    exc = InvalidStateTransition(ProcessState.READY, ProcessState.COMPLETED)
    assert "READY" in str(exc)
    assert "COMPLETED" in str(exc)


# ── StateMachine helpers ──────────────────────────────────────────────────────

def test_is_terminal():
    assert StateMachine.is_terminal(ProcessState.TERMINATED) is True
    assert StateMachine.is_terminal(ProcessState.READY) is False
    assert StateMachine.is_terminal(ProcessState.COMPLETED) is False  # has TERMINATED transition


def test_is_runnable():
    assert StateMachine.is_runnable(ProcessState.READY) is True
    assert StateMachine.is_runnable(ProcessState.RUNNING) is False
    assert StateMachine.is_runnable(ProcessState.WAITING) is False


def test_is_active():
    assert StateMachine.is_active(ProcessState.READY) is True
    assert StateMachine.is_active(ProcessState.RUNNING) is True
    assert StateMachine.is_active(ProcessState.COMPLETED) is False
    assert StateMachine.is_active(ProcessState.TERMINATED) is False
    assert StateMachine.is_active(ProcessState.CANCELLED) is False


def test_valid_transitions_returns_copy():
    t1 = StateMachine.valid_transitions()
    t2 = StateMachine.valid_transitions()
    assert t1 is not t2
