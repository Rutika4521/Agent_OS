from typing import Dict, Optional
from agent_os.llm.base import LLMProvider
from agent_os.llm.mock import MockLLMProvider
from agent_os.config.settings import get_settings

class LLMManager:
    def __init__(self):
        self._providers: Dict[str, LLMProvider] = {}
        # Auto-register MockLLMProvider on init
        self.register_provider("mock", MockLLMProvider())

    def register_provider(self, name: str, provider: LLMProvider) -> None:
        self._providers[name] = provider

    def get_provider(self, name: Optional[str] = None) -> LLMProvider:
        if name is None:
            settings = get_settings()
            name = getattr(settings, 'default_llm_provider', 'mock')
            
        if name not in self._providers:
            raise ValueError(f"Provider {name} not registered.")
        return self._providers[name]
