"""Tests for PriorityScheduler and AgingPolicy."""
import pytest
import time
from agent_os.scheduler.priority import PriorityScheduler
from agent_os.scheduler.aging import AgingPolicy
from agent_os.scheduler.weighted_fair import WeightedFairScheduler
from agent_os.kernel.state_machine import ProcessState, AgentStepResult, StepStatus
from agent_os.kernel.agent_process import AgentProcess
from agent_os.resources.quota import ResourceLimits
from agent_os.resources.usage import ResourceUsage
from agent_os.config.settings import Settings


def _make_proc(pid, priority, state=ProcessState.READY, ready_since=None):
    class A:
        async def step(self, ctx): return AgentStepResult(status=StepStatus.COMPLETED)
    p = AgentProcess(
        process_id=pid,
        agent=A(),
        name=f"p{pid}",
        state=state,
        priority=priority,
        resource_limits=ResourceLimits(),
        resource_usage=ResourceUsage(),
    )
    p.ready_since = ready_since or time.time()
    return p


# ── PriorityScheduler ─────────────────────────────────────────────────────────

def test_select_next_highest_priority():
    sched = PriorityScheduler()
    procs = [_make_proc(1, 3), _make_proc(2, 7), _make_proc(3, 5)]
    selected = sched.select_next(procs)
    assert selected.process_id == 2  # priority 7


def test_select_next_tie_break_lowest_pid():
    sched = PriorityScheduler()
    procs = [_make_proc(3, 5), _make_proc(1, 5), _make_proc(2, 5)]
    selected = sched.select_next(procs)
    assert selected.process_id == 1  # lowest PID wins tie


def test_select_next_empty_returns_none():
    sched = PriorityScheduler()
    assert sched.select_next([]) is None


def test_select_next_ignores_non_ready():
    sched = PriorityScheduler()
    p1 = _make_proc(1, 10, state=ProcessState.WAITING)
    p2 = _make_proc(2, 1, state=ProcessState.READY)
    selected = sched.select_next([p1, p2])
    assert selected.process_id == 2  # only ready one


def test_select_next_all_waiting_returns_none():
    sched = PriorityScheduler()
    procs = [_make_proc(1, 5, ProcessState.WAITING), _make_proc(2, 5, ProcessState.WAITING)]
    assert sched.select_next(procs) is None


def test_add_remove_are_noops():
    sched = PriorityScheduler()
    p = _make_proc(1, 5)
    sched.add(p)    # should not raise
    sched.remove(1)  # should not raise


# ── AgingPolicy ───────────────────────────────────────────────────────────────

def test_aging_bonus_zero_when_disabled():
    settings = Settings()
    settings.scheduler.aging.enabled = False
    policy = AgingPolicy(settings=settings)
    assert policy.calculate_bonus(9999) == 0


def test_aging_bonus_increases_with_wait_time():
    settings = Settings()
    settings.scheduler.aging.enabled = True
    settings.scheduler.aging.interval_seconds = 10
    settings.scheduler.aging.max_bonus = 5
    policy = AgingPolicy(settings=settings)
    assert policy.calculate_bonus(10) == 1
    assert policy.calculate_bonus(20) == 2
    assert policy.calculate_bonus(50) == 5


def test_aging_bonus_capped_at_max():
    settings = Settings()
    settings.scheduler.aging.enabled = True
    settings.scheduler.aging.interval_seconds = 10
    settings.scheduler.aging.max_bonus = 3
    policy = AgingPolicy(settings=settings)
    assert policy.calculate_bonus(1000) == 3


def test_aging_bonus_zero_for_zero_wait():
    settings = Settings()
    settings.scheduler.aging.enabled = True
    policy = AgingPolicy(settings=settings)
    assert policy.calculate_bonus(0) == 0


# ── WeightedFairScheduler ─────────────────────────────────────────────────────

def test_weighted_fair_selects_ready_process():
    sched = WeightedFairScheduler()
    procs = [_make_proc(1, 5), _make_proc(2, 3)]
    for p in procs:
        sched.add(p)
    selected = sched.select_next(procs)
    assert selected is not None
    assert selected.state == ProcessState.READY


def test_weighted_fair_empty_returns_none():
    sched = WeightedFairScheduler()
    assert sched.select_next([]) is None


def test_weighted_fair_remove_noop():
    sched = WeightedFairScheduler()
    sched.remove(999)  # should not raise
