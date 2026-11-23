"""Tests for Supervisor — failure handling, restart policies, event emission."""
import pytest
from agent_os.supervisor.supervisor import Supervisor
from agent_os.supervisor.restart import RestartManager, RestartPolicy
from agent_os.supervisor.failure import FailureType
from agent_os.kernel.state_machine import ProcessState
from agent_os.metrics.events import EventType
from tests.conftest import DummyAgent


@pytest.fixture
def restart_manager(settings):
    return RestartManager(settings.supervisor)


@pytest.fixture
def supervisor(process_manager, restart_manager, event_manager):
    return Supervisor(process_manager, restart_manager, event_manager)


@pytest.mark.asyncio
async def test_handle_failure_n_times_policy_restarts(process_manager, supervisor, event_manager):
    proc = await process_manager.spawn(DummyAgent(), name="worker", restart_policy="N_TIMES")
    await process_manager.set_state(proc.process_id, ProcessState.RUNNING)
    await process_manager.set_state(proc.process_id, ProcessState.FAILED)
    await supervisor.handle_failure(proc.process_id, FailureType.AGENT_EXCEPTION, "crash")
    updated = await process_manager.get(proc.process_id)
    assert updated.state == ProcessState.READY
    assert updated.restart_count == 1


@pytest.mark.asyncio
async def test_handle_failure_never_policy_terminates(process_manager, supervisor):
    proc = await process_manager.spawn(DummyAgent(), name="worker", restart_policy="NEVER")
    await process_manager.set_state(proc.process_id, ProcessState.RUNNING)
    await process_manager.set_state(proc.process_id, ProcessState.FAILED)
    await supervisor.handle_failure(proc.process_id, FailureType.AGENT_EXCEPTION, "crash")
    updated = await process_manager.get(proc.process_id)
    assert updated.state == ProcessState.TERMINATED


@pytest.mark.asyncio
async def test_handle_failure_emits_restart_events(process_manager, supervisor, event_manager):
    proc = await process_manager.spawn(DummyAgent(), restart_policy="N_TIMES")
    await process_manager.set_state(proc.process_id, ProcessState.RUNNING)
    await process_manager.set_state(proc.process_id, ProcessState.FAILED)
    await supervisor.handle_failure(proc.process_id, FailureType.AGENT_EXCEPTION, "err")
    types = [e.event_type for e in await event_manager.get_history()]
    assert EventType.RESTART_STARTED in types
    assert EventType.RESTART_COMPLETED in types


@pytest.mark.asyncio
async def test_get_failures_returns_records(process_manager, supervisor):
    proc = await process_manager.spawn(DummyAgent(), restart_policy="NEVER")
    await process_manager.set_state(proc.process_id, ProcessState.RUNNING)
    await process_manager.set_state(proc.process_id, ProcessState.FAILED)
    await supervisor.handle_failure(proc.process_id, FailureType.AGENT_EXCEPTION, "oops")
    records = await supervisor.get_failures(proc.process_id)
    assert len(records) == 1
    assert records[0].error_message == "oops"


@pytest.mark.asyncio
async def test_get_failures_all_returns_all(process_manager, supervisor):
    p1 = await process_manager.spawn(DummyAgent(), restart_policy="NEVER")
    p2 = await process_manager.spawn(DummyAgent(), restart_policy="NEVER")
    for pid in [p1.process_id, p2.process_id]:
        await process_manager.set_state(pid, ProcessState.RUNNING)
        await process_manager.set_state(pid, ProcessState.FAILED)
        await supervisor.handle_failure(pid, FailureType.AGENT_EXCEPTION, "err")
    all_records = await supervisor.get_failures()
    assert len(all_records) == 2


@pytest.mark.asyncio
async def test_handle_failure_nonexistent_pid_silent(supervisor):
    # Should not raise
    await supervisor.handle_failure(9999, FailureType.AGENT_EXCEPTION, "ghost")


# ── RestartManager ────────────────────────────────────────────────────────────

def test_restart_manager_never_policy(settings):
    rm = RestartManager(settings.supervisor)
    assert rm.can_restart(1, RestartPolicy.NEVER, restart_count=0) is False


def test_restart_manager_once_policy_first_time(settings):
    rm = RestartManager(settings.supervisor)
    assert rm.can_restart(1, RestartPolicy.ONCE, restart_count=0) is True


def test_restart_manager_once_policy_second_time(settings):
    rm = RestartManager(settings.supervisor)
    assert rm.can_restart(1, RestartPolicy.ONCE, restart_count=1) is False


def test_restart_manager_n_times_within_limit(settings):
    rm = RestartManager(settings.supervisor)
    # restart_count=0, no failures recorded → can restart
    assert rm.can_restart(1, RestartPolicy.N_TIMES, restart_count=0) is True


def test_restart_manager_n_times_at_limit(settings):
    rm = RestartManager(settings.supervisor)
    max_r = settings.supervisor.max_restarts
    assert rm.can_restart(1, RestartPolicy.N_TIMES, restart_count=max_r) is False


def test_restart_manager_record_failure_and_storm(settings):
    rm = RestartManager(settings.supervisor)
    # Record more failures than max_restarts to trigger storm
    for _ in range(settings.supervisor.max_restarts + 1):
        rm.record_failure(1)
    assert rm.is_failure_storm(1) is True


def test_restart_manager_clear_history(settings):
    rm = RestartManager(settings.supervisor)
    rm.record_failure(1)
    rm.clear_history(1)
    assert rm.is_failure_storm(1) is False


def test_get_backoff_delay_increases(settings):
    rm = RestartManager(settings.supervisor)
    d0 = rm.get_backoff_delay(0)
    d1 = rm.get_backoff_delay(1)
    assert d1 > d0
