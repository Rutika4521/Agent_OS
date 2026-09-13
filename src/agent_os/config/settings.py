"""
Agent-OS Configuration Settings

Loads configuration from config.yaml and provides typed access
to all configuration sections. Values here are defaults that can
be overridden by the YAML file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ResourceDefaults:
    """Default resource limits for new processes."""
    token_limit: int = 5000
    llm_call_limit: int = 50
    tool_call_limit: int = 20
    step_limit: int = 100
    wall_time_limit: float = 300.0
    child_process_limit: int = 10


@dataclass
class ProcessDefaults:
    """Default process configuration."""
    priority: int = 5
    weight: int = 1
    resources: ResourceDefaults = field(default_factory=ResourceDefaults)
    restart_policy: str = "N_TIMES"
    resource_exceeded_policy: str = "FAIL"
    orphan_policy: str = "TERMINATE"


@dataclass
class AgingConfig:
    """Aging configuration for starvation prevention."""
    enabled: bool = True
    interval_seconds: float = 5.0
    max_bonus: int = 10


@dataclass
class SchedulerConfig:
    """Scheduler configuration."""
    aging: AgingConfig = field(default_factory=AgingConfig)
    time_slice_steps: int = 1


@dataclass
class IPCConfig:
    """IPC configuration."""
    queue_capacity: int = 100
    overflow_policy: str = "BLOCK"


@dataclass
class MemoryConfig:
    """Memory/context management configuration."""
    max_loaded_pages: int = 100
    eviction_policy: str = "LRU"
    page_size: int = 4096


@dataclass
class SupervisorConfig:
    """Supervisor configuration."""
    max_restarts: int = 3
    failure_window_seconds: float = 60.0
    backoff_initial: float = 1.0
    backoff_multiplier: float = 2.0
    backoff_max: float = 60.0


@dataclass
class SecurityConfig:
    """Security configuration."""
    default_capabilities: list[str] = field(default_factory=list)


@dataclass
class SandboxConfig:
    """Sandbox configuration."""
    enabled: bool = True
    timeout_seconds: float = 30.0


@dataclass
class LLMConfig:
    """LLM provider configuration."""
    default_provider: str = "mock"


@dataclass
class PersistenceConfig:
    """Persistence configuration."""
    database_url: str = "sqlite+aiosqlite:///agent_os.db"


@dataclass
class APIConfig:
    """API configuration."""
    host: str = "0.0.0.0"
    port: int = 8000


@dataclass
class SystemConfig:
    """Top-level system configuration."""
    max_processes: int = 100
    default_scheduler: str = "priority"


@dataclass
class Settings:
    """
    Root configuration object for Agent-OS.

    Loaded from config.yaml. All values are configurable defaults.
    """
    system: SystemConfig = field(default_factory=SystemConfig)
    process_defaults: ProcessDefaults = field(default_factory=ProcessDefaults)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    ipc: IPCConfig = field(default_factory=IPCConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    supervisor: SupervisorConfig = field(default_factory=SupervisorConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    sandbox: SandboxConfig = field(default_factory=SandboxConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    persistence: PersistenceConfig = field(default_factory=PersistenceConfig)
    api: APIConfig = field(default_factory=APIConfig)


def _merge_dataclass(dc_instance: Any, data: dict) -> Any:
    """Recursively merge a dict into a dataclass instance."""
    if not isinstance(data, dict):
        return dc_instance
    for key, value in data.items():
        if hasattr(dc_instance, key):
            current = getattr(dc_instance, key)
            if hasattr(current, '__dataclass_fields__') and isinstance(value, dict):
                _merge_dataclass(current, value)
            else:
                setattr(dc_instance, key, value)
    return dc_instance


def load_settings(config_path: str | Path | None = None) -> Settings:
    """
    Load settings from a YAML configuration file.

    Args:
        config_path: Path to config.yaml. If None, searches for
                     config.yaml in the current directory and project root.

    Returns:
        Fully initialized Settings object.
    """
    settings = Settings()

    if config_path is None:
        # Search for config.yaml
        candidates = [
            Path.cwd() / "config.yaml",
            Path(__file__).resolve().parent.parent.parent.parent / "config.yaml",
        ]
        for candidate in candidates:
            if candidate.exists():
                config_path = candidate
                break
    else:
        config_path = Path(config_path)

    if config_path and Path(config_path).exists():
        with open(config_path, "r") as f:
            data = yaml.safe_load(f) or {}
        _merge_dataclass(settings, data)

    return settings


# Module-level singleton (lazy)
_settings: Settings | None = None


def get_settings(config_path: str | Path | None = None) -> Settings:
    """Get or create the global settings singleton."""
    global _settings
    if _settings is None:
        _settings = load_settings(config_path)
    return _settings


def reset_settings() -> None:
    """Reset the global settings singleton. Useful for testing."""
    global _settings
    _settings = None
