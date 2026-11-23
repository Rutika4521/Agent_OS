"""Tests for DeadlockDetector."""
import pytest
from agent_os.synchronization.deadlock import DeadlockDetector


def test_no_cycle_in_empty_graph():
    d = DeadlockDetector()
    assert d.detect_cycle() is None


def test_no_cycle_simple_chain():
    d = DeadlockDetector()
    d.add_dependency(1, 2)
    d.add_dependency(2, 3)
    assert d.detect_cycle() is None


def test_cycle_detected_two_nodes():
    d = DeadlockDetector()
    d.add_dependency(1, 2)
    d.add_dependency(2, 1)
    cycle = d.detect_cycle()
    assert cycle is not None
    assert len(cycle) >= 2
    assert 1 in cycle
    assert 2 in cycle


def test_cycle_detected_three_nodes():
    d = DeadlockDetector()
    d.add_dependency(1, 2)
    d.add_dependency(2, 3)
    d.add_dependency(3, 1)
    cycle = d.detect_cycle()
    assert cycle is not None
    assert len(cycle) == 3


def test_remove_dependency_breaks_cycle():
    d = DeadlockDetector()
    d.add_dependency(1, 2)
    d.add_dependency(2, 1)
    d.remove_dependency(2, 1)
    assert d.detect_cycle() is None


def test_remove_process_clears_all_edges():
    d = DeadlockDetector()
    d.add_dependency(1, 2)
    d.add_dependency(2, 1)
    d.remove_process(2)
    assert d.detect_cycle() is None


def test_select_victim_lowest_priority():
    d = DeadlockDetector()
    cycle = [1, 2, 3]
    priorities = {1: 9, 2: 3, 3: 6}
    victim = d.select_victim(cycle, priorities)
    assert victim == 2  # lowest priority


def test_select_victim_tie_break_highest_pid():
    d = DeadlockDetector()
    cycle = [1, 3, 5]
    priorities = {1: 5, 3: 5, 5: 5}  # all same priority
    victim = d.select_victim(cycle, priorities)
    assert victim == 5  # highest PID breaks tie


def test_select_victim_empty_raises():
    d = DeadlockDetector()
    with pytest.raises(ValueError):
        d.select_victim([], {})


def test_clear_removes_all_state():
    d = DeadlockDetector()
    d.add_dependency(1, 2)
    d.add_dependency(2, 1)
    d.clear()
    assert d.detect_cycle() is None


def test_add_dependency_creates_holder_node():
    d = DeadlockDetector()
    d.add_dependency(1, 2)
    # holder (2) should be in graph even though it has no outgoing edges
    assert 2 in d._graph


def test_multiple_cycles_detected():
    d = DeadlockDetector()
    # Two independent cycles: 1→2→1 and 3→4→3
    d.add_dependency(1, 2)
    d.add_dependency(2, 1)
    d.add_dependency(3, 4)
    d.add_dependency(4, 3)
    cycle = d.detect_cycle()
    assert cycle is not None  # At least one cycle found
