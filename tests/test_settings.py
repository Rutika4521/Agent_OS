"""Tests for Settings loading and structure."""
import pytest
from agent_os.config.settings import Settings, get_settings, reset_settings


def test_settings_loads_defaults():
    s = Settings()
    assert s.system.max_processes > 0
    assert s.scheduler is not None
    assert s.ipc is not None
    assert s.supervisor is not None


def test_settings_system_has_required_fields():
    s = Settings()
    assert hasattr(s.system, "max_processes")
    assert hasattr(s.system, "default_scheduler")


def test_settings_scheduler_aging_config():
    s = Settings()
    assert hasattr(s.scheduler.aging, "enabled")
    assert hasattr(s.scheduler.aging, "interval_seconds")
    assert hasattr(s.scheduler.aging, "max_bonus")


def test_settings_ipc_config():
    s = Settings()
    assert hasattr(s.ipc, "queue_capacity")
    assert hasattr(s.ipc, "overflow_policy")


def test_settings_supervisor_config():
    s = Settings()
    assert hasattr(s.supervisor, "max_restarts")
    assert hasattr(s.supervisor, "backoff_initial")


def test_get_settings_returns_singleton():
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2


def test_reset_settings_creates_new_singleton():
    s1 = get_settings()
    reset_settings()
    s2 = get_settings()
    assert s1 is not s2


def test_process_defaults_exist():
    s = Settings()
    assert s.process_defaults is not None
    assert hasattr(s.process_defaults, "priority")
    assert hasattr(s.process_defaults, "weight")
    assert hasattr(s.process_defaults, "restart_policy")


def test_resource_defaults_have_positive_limits():
    s = Settings()
    r = s.process_defaults.resources
    assert r.token_limit > 0
    assert r.step_limit > 0


def test_settings_default_scheduler_is_valid():
    s = Settings()
    assert s.system.default_scheduler in ("priority", "weighted_fair")


def test_settings_security_config():
    s = Settings()
    assert hasattr(s.security, "default_capabilities")
    assert isinstance(s.security.default_capabilities, list)


def test_settings_memory_config():
    s = Settings()
    assert hasattr(s.memory, "max_loaded_pages")
    assert s.memory.max_loaded_pages > 0
