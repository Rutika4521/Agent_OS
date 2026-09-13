class CapabilityDenied(Exception):
    def __init__(self, process_id: int, capability: str):
        super().__init__(f"Capability '{capability}' denied for process {process_id}")
        self.process_id = process_id
        self.capability = capability

class CapabilityManager:
    def __init__(self, default_capabilities: list[str] = None):
        self._default_capabilities = set(default_capabilities) if default_capabilities else set()
        self._process_capabilities: dict[int, set[str]] = {}

    def grant(self, process_id: int, capability: str) -> None:
        if process_id not in self._process_capabilities:
            self._process_capabilities[process_id] = set(self._default_capabilities)
        self._process_capabilities[process_id].add(capability)

    def revoke(self, process_id: int, capability: str) -> None:
        if process_id in self._process_capabilities and capability in self._process_capabilities[process_id]:
            self._process_capabilities[process_id].remove(capability)

    def check(self, process_id: int, capability: str) -> bool:
        caps = self._process_capabilities.get(process_id, self._default_capabilities)
        return capability in caps

    def get_capabilities(self, process_id: int) -> set[str]:
        return self._process_capabilities.get(process_id, set(self._default_capabilities)).copy()

    def initialize_process(self, process_id: int, capabilities: list[str]) -> None:
        self._process_capabilities[process_id] = set(capabilities)

    def remove_process(self, process_id: int) -> None:
        self._process_capabilities.pop(process_id, None)
