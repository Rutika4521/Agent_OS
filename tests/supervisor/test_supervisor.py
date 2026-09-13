"""Tests for Supervisor (§45-§49)."""
import pytest
from agent_os.kernel.process_manager import ProcessManager
from agent_os.kernel.process_table import ProcessTable
from agent_os.kernel.state_machine import ProcessState, StepStatus, AgentStepResult
from agent_os.metrics.events import EventManager
from agent_os.config.settings import Settings
from agent_os.supervisor.supervisor import Supervisor
from agent_os.supervisor.failure import FailureType
from agent_os.supervisor.restart import RestartManager, RestartPolicy
from sdk.agent import AgentContext


class FailingAgent:
    async def step(self, ctx):
        raise RuntimeError("fail")


@pytest.fixture
def supervisor_components():
    settings = Settings()
    em = EventManager()
    pt = ProcessTable()
    pm = ProcessManager(pt, em, settings)
    rm = RestartManager(settings.supervisor)
    sv = Supervisor(pm, rm, em)
    return pm, sv, rm, settings


@pytest.mark.asyncio
async def test_handle_failure_with_restart(supervisor_components):
    pm, sv, rm, _ = supervisor_components
    p = await pm.spawn(FailingAgent(), restart_policy="N_TIMES")
    # Simulate failure: set to FAILED
    await pm.set_state(p.process_id, ProcessState.RUNNING)
    await pm.set_state(p.process_id, ProcessState.FAILED)
    assert p.state == ProcessState.FAILED

    await sv.handle_failure(p.process_id, FailureType.AGENT_EXCEPTION, "test error")
    # Should be restarted -> READY
    assert p.state == ProcessState.READY
    assert p.restart_count == 1


@pytest.mark.asyncio
async def test_handle_failure_never_policy(supervisor_components):
    pm, sv, rm, _ = supervisor_components
    p = await pm.spawn(FailingAgent(), restart_policy="NEVER")
    await pm.set_state(p.process_id, ProcessState.RUNNING)
    await pm.set_state(p.process_id, ProcessState.FAILED)

    await sv.handle_failure(p.process_id, FailureType.AGENT_EXCEPTION, "test error")
    assert p.state == ProcessState.TERMINATED


@pytest.mark.asyncio
async def test_restart_limit_exceeded(supervisor_components):
    pm, sv, rm, settings = supervisor_components
    settings.supervisor.max_restarts = 1
    rm_limited = RestartManager(settings.supervisor)
    sv_limited = Supervisor(pm, rm_limited, EventManager())

    p = await pm.spawn(FailingAgent(), restart_policy="N_TIMES")

    # First failure -> restart
    await pm.set_state(p.process_id, ProcessState.RUNNING)
    await pm.set_state(p.process_id, ProcessState.FAILED)
    await sv_limited.handle_failure(p.process_id, FailureType.AGENT_EXCEPTION, "err1")
    assert p.state == ProcessState.READY
    assert p.restart_count == 1

    # Second failure -> should terminate (limit=1 reached)
    await pm.set_state(p.process_id, ProcessState.RUNNING)
    await pm.set_state(p.process_id, ProcessState.FAILED)
    await sv_limited.handle_failure(p.process_id, FailureType.AGENT_EXCEPTION, "err2")
    assert p.state == ProcessState.TERMINATED


@pytest.mark.asyncio
async def test_restart_manager_basics():
    settings = Settings()
    rm = RestartManager(settings.supervisor)
    assert rm.can_restart(1, RestartPolicy.NEVER, restart_count=0) is False
    assert rm.can_restart(1, RestartPolicy.ONCE, restart_count=0) is True
    assert rm.can_restart(1, RestartPolicy.ONCE, restart_count=1) is False
    assert rm.can_restart(1, RestartPolicy.N_TIMES, restart_count=0) is True


@pytest.mark.asyncio
async def test_backoff_delay():
    settings = Settings()
    rm = RestartManager(settings.supervisor)
    d0 = rm.get_backoff_delay(0)
    d1 = rm.get_backoff_delay(1)
    d2 = rm.get_backoff_delay(2)
    assert d0 == settings.supervisor.backoff_initial
    assert d1 == settings.supervisor.backoff_initial * settings.supervisor.backoff_multiplier
    assert d2 <= settings.supervisor.backoff_max
