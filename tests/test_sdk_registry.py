"""
Tests for sdk/registry.py — @register decorator
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]   # tests/ → project root
sys.path.insert(0, str(_ROOT / "src"))         # for `agent_os` package
sys.path.insert(0, str(_ROOT))                 # for `sdk` package

import pytest
from sdk.registry import (
    register,
    get_registry,
    clear_registry,
    registered_count,
    AgentRegistration,
)


# ── Fixture: always clear the global registry between tests ───────────────────

@pytest.fixture(autouse=True)
def clean_registry():
    clear_registry()
    yield
    clear_registry()


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestRegisterDecorator:
    def test_register_adds_to_registry(self):
        @register(priority=7, name="Alpha")
        class AlphaAgent:
            async def run(self): ...

        assert registered_count() == 1

    def test_class_unchanged(self):
        @register()
        class BetaAgent:
            async def run(self): return "beta"

        instance = BetaAgent()
        # Class still works normally
        assert callable(instance.run)

    def test_name_defaults_to_class_name(self):
        @register()
        class GammaAgent:
            async def run(self): ...

        regs = get_registry()
        assert regs[0].name == "GammaAgent"

    def test_explicit_name_stored(self):
        @register(name="Custom Name")
        class DeltaAgent:
            async def run(self): ...

        assert get_registry()[0].name == "Custom Name"

    def test_priority_stored(self):
        @register(priority=9)
        class EpsilonAgent:
            async def run(self): ...

        assert get_registry()[0].priority == 9

    def test_default_priority_is_five(self):
        @register()
        class ZetaAgent:
            async def run(self): ...

        assert get_registry()[0].priority == 5

    def test_weight_stored(self):
        @register(weight=3)
        class EtaAgent:
            async def run(self): ...

        assert get_registry()[0].weight == 3

    def test_restart_policy_stored(self):
        @register(restart_policy="ONCE")
        class ThetaAgent:
            async def run(self): ...

        assert get_registry()[0].restart_policy == "ONCE"

    def test_default_restart_policy_is_n_times(self):
        @register()
        class IotaAgent:
            async def run(self): ...

        assert get_registry()[0].restart_policy == "N_TIMES"

    def test_steps_stored(self):
        steps = [{"args": ["a"]}, {"args": ["b"]}]

        @register(steps=steps)
        class KappaAgent:
            async def run(self, x): ...

        assert get_registry()[0].steps == steps

    def test_steps_none_by_default(self):
        @register()
        class LambdaAgent:
            async def run(self): ...

        assert get_registry()[0].steps is None

    def test_method_stored(self):
        @register(method="execute")
        class MuAgent:
            async def execute(self): ...

        assert get_registry()[0].method == "execute"

    def test_init_args_and_kwargs_stored(self):
        @register(init_args=[1, 2], init_kwargs={"x": 3})
        class NuAgent:
            def __init__(self, a, b, x=0):
                pass
            async def run(self): ...

        reg = get_registry()[0]
        assert reg.init_args == [1, 2]
        assert reg.init_kwargs == {"x": 3}

    def test_class_gets_registration_attribute(self):
        @register(priority=4)
        class XiAgent:
            async def run(self): ...

        assert hasattr(XiAgent, "_agent_os_registration")
        assert isinstance(XiAgent._agent_os_registration, AgentRegistration)
        assert XiAgent._agent_os_registration.priority == 4


class TestMultipleRegistrations:
    def test_multiple_agents_all_registered(self):
        @register(name="First")
        class FirstAgent:
            async def run(self): ...

        @register(name="Second")
        class SecondAgent:
            async def run(self): ...

        @register(name="Third")
        class ThirdAgent:
            async def run(self): ...

        assert registered_count() == 3
        names = [r.name for r in get_registry()]
        assert names == ["First", "Second", "Third"]

    def test_order_preserved(self):
        names = ["Omega", "Sigma", "Tau"]
        for n in names:
            @register(name=n)
            class DynamicAgent:
                async def run(self): ...

        stored = [r.name for r in get_registry()]
        assert stored == names


class TestClearRegistry:
    def test_clear_empties_registry(self):
        @register()
        class TempAgent:
            async def run(self): ...

        assert registered_count() == 1
        clear_registry()
        assert registered_count() == 0

    def test_clear_is_idempotent(self):
        clear_registry()
        clear_registry()
        assert registered_count() == 0


class TestGetRegistry:
    def test_returns_copy_not_reference(self):
        @register()
        class CopyAgent:
            async def run(self): ...

        registry_copy = get_registry()
        registry_copy.clear()
        # Original should still have 1 entry
        assert registered_count() == 1
