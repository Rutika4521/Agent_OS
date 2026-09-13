from agent_os.config.settings import Settings, get_settings
from agent_os.security.capability import CapabilityManager

class SecurityPolicy:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._tool_capability_map: dict[str, str] = {}
        
    def register_tool_capability(self, tool_name: str, required_capability: str) -> None:
        self._tool_capability_map[tool_name] = required_capability

    def check_tool_access(self, process_id: int, tool_name: str, capability_manager: CapabilityManager) -> bool:
        required_cap = self._tool_capability_map.get(tool_name)
        if not required_cap:
            return True
        return capability_manager.check(process_id, required_cap)

    def get_required_capability(self, tool_name: str) -> str | None:
        return self._tool_capability_map.get(tool_name)
