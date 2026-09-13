from dataclasses import dataclass, field
from typing import Protocol, Dict, Any

@dataclass
class LLMRequest:
    prompt: str
    max_tokens: int = 1000
    temperature: float = 0.7
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class LLMResponse:
    content: str
    input_tokens: int
    output_tokens: int
    latency: float
    metadata: Dict[str, Any] = field(default_factory=dict)

class LLMProvider(Protocol):
    async def generate(self, request: LLMRequest) -> LLMResponse:
        ...
