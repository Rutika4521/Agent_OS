from typing import List, Optional
from agent_os.kernel.agent_process import AgentProcess
from agent_os.config.settings import get_settings
from agent_os.scheduler.base import Scheduler
from agent_os.scheduler.priority import PriorityScheduler
from agent_os.scheduler.weighted_fair import WeightedFairScheduler

class SchedulerManager(Scheduler):
    def __init__(self):
        self.priority_scheduler = PriorityScheduler()
        self.weighted_fair_scheduler = WeightedFairScheduler()
        
        settings = get_settings()
        self.scheduler_type = settings.system.default_scheduler

    def add(self, process: AgentProcess) -> None:
        self.priority_scheduler.add(process)
        self.weighted_fair_scheduler.add(process)

    def remove(self, process_id: int) -> None:
        self.priority_scheduler.remove(process_id)
        self.weighted_fair_scheduler.remove(process_id)

    def select_next(self, processes: List[AgentProcess]) -> Optional[AgentProcess]:
        if self.scheduler_type == 'weighted_fair':
            return self.weighted_fair_scheduler.select_next(processes)
        return self.priority_scheduler.select_next(processes)
        
    def switch_scheduler_type(self, new_type: str) -> None:
        if new_type not in ['priority', 'weighted_fair']:
            raise ValueError(f"Unknown scheduler type: {new_type}")
        self.scheduler_type = new_type
