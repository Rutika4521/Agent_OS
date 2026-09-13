import asyncio
import time
from typing import Dict, Any, Optional
from agent_os.llm.base import LLMProvider, LLMRequest, LLMResponse

class MockLLMProvider:
    def __init__(
        self,
        default_response: str = "Mock response",
        default_latency: float = 0.1,
        default_input_tokens: int = 10,
        default_output_tokens: int = 20,
        pattern_responses: Optional[Dict[str, str]] = None,
        failure_mode: bool = False,
        timeout_mode: bool = False,
        timeout_duration: float = 10.0,
    ):
        self.default_response = default_response
        self.default_latency = default_latency
        self.default_input_tokens = default_input_tokens
        self.default_output_tokens = default_output_tokens
        self.pattern_responses = pattern_responses or {}
        self.failure_mode = failure_mode
        self.timeout_mode = timeout_mode
        self.timeout_duration = timeout_duration
        self.call_count = 0

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.call_count += 1
        
        if self.failure_mode:
            raise RuntimeError("Mock LLM Provider failure mode active.")
            
        if self.timeout_mode:
            await asyncio.sleep(self.timeout_duration)
            raise TimeoutError("Mock LLM Provider timeout mode active.")
            
        start_time = time.monotonic()
        await asyncio.sleep(self.default_latency)
        
        response_content = self.default_response
        for pattern, response in self.pattern_responses.items():
            if pattern in request.prompt:
                response_content = response
                break
                
        latency = time.monotonic() - start_time
        
        return LLMResponse(
            content=response_content,
            input_tokens=self.default_input_tokens,
            output_tokens=self.default_output_tokens,
            latency=latency,
            metadata={"mock_call_count": self.call_count}
        )
