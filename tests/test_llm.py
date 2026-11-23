"""Tests for MockLLMProvider and LLMManager."""
import pytest
from agent_os.llm.mock import MockLLMProvider
from agent_os.llm.base import LLMRequest, LLMResponse
from agent_os.llm.manager import LLMManager


@pytest.mark.asyncio
async def test_mock_llm_returns_response():
    llm = MockLLMProvider()
    req = LLMRequest(prompt="hello")
    resp = await llm.generate(req)
    assert isinstance(resp, LLMResponse)
    assert resp.content is not None


@pytest.mark.asyncio
async def test_mock_llm_default_response():
    llm = MockLLMProvider(default_response="test output")
    req = LLMRequest(prompt="anything")
    resp = await llm.generate(req)
    assert resp.content == "test output"


@pytest.mark.asyncio
async def test_mock_llm_pattern_response():
    llm = MockLLMProvider(pattern_responses={"outline": "I will outline..."})
    req = LLMRequest(prompt="please outline the topic")
    resp = await llm.generate(req)
    assert resp.content == "I will outline..."


@pytest.mark.asyncio
async def test_mock_llm_tracks_call_count():
    llm = MockLLMProvider(default_latency=0.0)
    for _ in range(3):
        await llm.generate(LLMRequest(prompt="x"))
    assert llm.call_count == 3


@pytest.mark.asyncio
async def test_mock_llm_returns_token_counts():
    llm = MockLLMProvider()
    resp = await llm.generate(LLMRequest(prompt="test"))
    assert resp.input_tokens >= 0
    assert resp.output_tokens >= 0


@pytest.mark.asyncio
async def test_mock_llm_failure_mode():
    llm = MockLLMProvider(failure_mode=True)
    with pytest.raises(RuntimeError):
        await llm.generate(LLMRequest(prompt="fail"))


# ── LLMManager ────────────────────────────────────────────────────────────────

def test_llm_manager_has_mock_by_default():
    mgr = LLMManager()
    provider = mgr.get_provider("mock")
    assert provider is not None


def test_llm_manager_register_and_get():
    mgr = LLMManager()
    custom = MockLLMProvider(default_response="custom")
    mgr.register_provider("custom", custom)
    assert mgr.get_provider("custom") is custom


def test_llm_manager_get_nonexistent_raises():
    mgr = LLMManager()
    with pytest.raises(ValueError):
        mgr.get_provider("nonexistent")
