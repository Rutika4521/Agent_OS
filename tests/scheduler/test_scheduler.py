"""Tests for Scheduler (§20-§24)."""
import pytest
import time
from agent_os.scheduler.priority import PriorityScheduler
from agent_os.scheduler.weighted_fair import WeightedFairScheduler
from agent_os.scheduler.aging import AgingPolicy
from agent_os.kernel.agent_process import AgentProcess
from agent_os.kernel.state_machine import ProcessState
from agent_os.config.settings import Settings
from unittest.mock import AsyncMock


def make_ready_process(pid, priority=5, weight=1, ready_since=None):
    p = AgentProcess(
        process_id=pid, agent=AsyncMock(), name=f"p-{pid}",
        state=ProcessState.READY, priority=priority, weight=weight,
        ready_since=ready_since or time.time(),
    )
    return p


def test_priority_selects_highest():
    settings = Settings()
    sched = PriorityScheduler(settings=settings)
    p1 = make_ready_process(1, priority=2)
    p2 = make_ready_process(2, priority=9)
    selected = sched.select_next([p1, p2])
    assert selected.process_id == 2


def test_priority_tiebreak_by_pid():
    settings = Settings()
    sched = PriorityScheduler(settings=settings)
    p1 = make_ready_process(1, priority=5)
    p2 = make_ready_process(2, priority=5)
    selected = sched.select_next([p1, p2])
    assert selected.process_id == 1  # lower PID wins tie


def test_priority_empty_list():
    settings = Settings()
    sched = PriorityScheduler(settings=settings)
    assert sched.select_next([]) is None


def test_aging_bonus():
    settings = Settings()
    policy = AgingPolicy(settings=settings)
    # 25 seconds / 5 second interval = 5 bonus
    assert policy.calculate_bonus(25.0) == 5


def test_aging_capped():
    settings = Settings()
    policy = AgingPolicy(settings=settings)
    # 1000 seconds / 5 = 200, capped at 10
    assert policy.calculate_bonus(1000.0) == 10


def test_starvation_prevention():
    settings = Settings()
    sched = PriorityScheduler(settings=settings)
    p_high = make_ready_process(1, priority=9, ready_since=time.time())
    p_low = make_ready_process(2, priority=2, ready_since=time.time() - 200)
    # Low priority: 2 + min(200/5, 10) = 2 + 10 = 12
    # High priority: 9 + 0 = 9
    selected = sched.select_next([p_high, p_low])
    assert selected.process_id == 2  # low priority wins with aging


def test_weighted_fair_proportional():
    sched = WeightedFairScheduler()
    p1 = make_ready_process(1, weight=1)
    p2 = make_ready_process(2, weight=2)

    counts = {1: 0, 2: 0}
    for _ in range(30):
        selected = sched.select_next([p1, p2])
        counts[selected.process_id] += 1

    # Weight-2 should get ~2x selections
    assert counts[2] >= counts[1] * 1.5  # roughly 2:1


def test_weighted_fair_tiebreak():
    sched = WeightedFairScheduler()
    p1 = make_ready_process(1, weight=1)
    p2 = make_ready_process(2, weight=1)
    # First selection: both get deficit 1, PID 1 wins tiebreak
    selected = sched.select_next([p1, p2])
    assert selected.process_id == 1
