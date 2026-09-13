"""Tests for StateMachine (§14)."""
import pytest
from agent_os.kernel.state_machine import (
    ProcessState, StateMachine, InvalidStateTransition,
    StepStatus, WaitReason, AgentStepResult,
)


# --- Valid transitions ---

def test_created_to_ready():
    assert StateMachine.transition(ProcessState.CREATED, ProcessState.READY) == ProcessState.READY

def test_ready_to_running():
    assert StateMachine.transition(ProcessState.READY, ProcessState.RUNNING) == ProcessState.RUNNING

def test_running_to_ready():
    assert StateMachine.transition(ProcessState.RUNNING, ProcessState.READY) == ProcessState.READY

def test_running_to_waiting():
    assert StateMachine.transition(ProcessState.RUNNING, ProcessState.WAITING) == ProcessState.WAITING

def test_running_to_blocked():
    assert StateMachine.transition(ProcessState.RUNNING, ProcessState.BLOCKED) == ProcessState.BLOCKED

def test_running_to_completed():
    assert StateMachine.transition(ProcessState.RUNNING, ProcessState.COMPLETED) == ProcessState.COMPLETED

def test_running_to_failed():
    assert StateMachine.transition(ProcessState.RUNNING, ProcessState.FAILED) == ProcessState.FAILED

def test_running_to_cancelling():
    assert StateMachine.transition(ProcessState.RUNNING, ProcessState.CANCELLING) == ProcessState.CANCELLING

def test_waiting_to_ready():
    assert StateMachine.transition(ProcessState.WAITING, ProcessState.READY) == ProcessState.READY

def test_waiting_to_cancelling():
    assert StateMachine.transition(ProcessState.WAITING, ProcessState.CANCELLING) == ProcessState.CANCELLING

def test_waiting_to_terminated():
    assert StateMachine.transition(ProcessState.WAITING, ProcessState.TERMINATED) == ProcessState.TERMINATED

def test_blocked_to_ready():
    assert StateMachine.transition(ProcessState.BLOCKED, ProcessState.READY) == ProcessState.READY

def test_blocked_to_cancelling():
    assert StateMachine.transition(ProcessState.BLOCKED, ProcessState.CANCELLING) == ProcessState.CANCELLING

def test_blocked_to_terminated():
    assert StateMachine.transition(ProcessState.BLOCKED, ProcessState.TERMINATED) == ProcessState.TERMINATED

def test_failed_to_restarting():
    assert StateMachine.transition(ProcessState.FAILED, ProcessState.RESTARTING) == ProcessState.RESTARTING

def test_failed_to_terminated():
    assert StateMachine.transition(ProcessState.FAILED, ProcessState.TERMINATED) == ProcessState.TERMINATED

def test_restarting_to_ready():
    assert StateMachine.transition(ProcessState.RESTARTING, ProcessState.READY) == ProcessState.READY

def test_restarting_to_failed():
    assert StateMachine.transition(ProcessState.RESTARTING, ProcessState.FAILED) == ProcessState.FAILED

def test_cancelling_to_cancelled():
    assert StateMachine.transition(ProcessState.CANCELLING, ProcessState.CANCELLED) == ProcessState.CANCELLED

def test_completed_to_terminated():
    assert StateMachine.transition(ProcessState.COMPLETED, ProcessState.TERMINATED) == ProcessState.TERMINATED

def test_cancelled_to_terminated():
    assert StateMachine.transition(ProcessState.CANCELLED, ProcessState.TERMINATED) == ProcessState.TERMINATED


# --- Invalid transitions ---

def test_invalid_created_to_running():
    with pytest.raises(InvalidStateTransition):
        StateMachine.transition(ProcessState.CREATED, ProcessState.RUNNING)

def test_invalid_ready_to_completed():
    with pytest.raises(InvalidStateTransition):
        StateMachine.transition(ProcessState.READY, ProcessState.COMPLETED)

def test_invalid_terminated_to_ready():
    with pytest.raises(InvalidStateTransition):
        StateMachine.transition(ProcessState.TERMINATED, ProcessState.READY)

def test_invalid_completed_to_ready():
    with pytest.raises(InvalidStateTransition):
        StateMachine.transition(ProcessState.COMPLETED, ProcessState.READY)


# --- Helpers ---

def test_can_transition():
    assert StateMachine.can_transition(ProcessState.CREATED, ProcessState.READY) is True
    assert StateMachine.can_transition(ProcessState.READY, ProcessState.CREATED) is False

def test_is_terminal():
    assert StateMachine.is_terminal(ProcessState.TERMINATED) is True
    assert StateMachine.is_terminal(ProcessState.RUNNING) is False

def test_is_runnable():
    assert StateMachine.is_runnable(ProcessState.READY) is True
    assert StateMachine.is_runnable(ProcessState.RUNNING) is False

def test_is_active():
    assert StateMachine.is_active(ProcessState.RUNNING) is True
    assert StateMachine.is_active(ProcessState.READY) is True
    assert StateMachine.is_active(ProcessState.TERMINATED) is False
    assert StateMachine.is_active(ProcessState.COMPLETED) is False
    assert StateMachine.is_active(ProcessState.CANCELLED) is False
