"""Tests for Security (§53-§54)."""
import pytest
from agent_os.security.capability import CapabilityManager, CapabilityDenied


def test_grant_and_check():
    cm = CapabilityManager()
    cm.initialize_process(1, ["read"])
    assert cm.check(1, "read") is True
    assert cm.check(1, "write") is False


def test_grant_capability():
    cm = CapabilityManager()
    cm.initialize_process(1, [])
    cm.grant(1, "write")
    assert cm.check(1, "write") is True
    assert "write" in cm.get_capabilities(1)


def test_revoke_capability():
    cm = CapabilityManager()
    cm.initialize_process(1, ["read", "write"])
    cm.revoke(1, "write")
    assert cm.check(1, "write") is False
    assert cm.check(1, "read") is True


def test_missing_capability():
    cm = CapabilityManager()
    cm.initialize_process(1, [])
    assert cm.check(1, "execute") is False


def test_remove_process():
    cm = CapabilityManager()
    cm.initialize_process(1, ["read"])
    cm.remove_process(1)
    assert cm.get_capabilities(1) == set()
