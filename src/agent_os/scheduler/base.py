from typing import Protocol, List, Optional
from agent_os.kernel.agent_process import AgentProcess

class Scheduler(Protocol):
    def add(self, process: AgentProcess) -> None:
        ...

    def remove(self, process_id: int) -> None:
        ...

    def select_next(self, processes: List[AgentProcess]) -> Optional[AgentProcess]:
        ...
