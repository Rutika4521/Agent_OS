"""Agent-OS Supervisor — Restart policies."""
from enum import Enum
from agent_os.config.settings import SupervisorConfig

class RestartPolicy(str, Enum):
    NEVER = "NEVER"
    ONCE = "ONCE"
    N_TIMES = "N_TIMES"
    EXPONENTIAL_BACKOFF = "EXPONENTIAL_BACKOFF"

class RestartManager:
    def __init__(self, config: SupervisorConfig):
        self._config = config
        self._failure_history: dict[int, list[float]] = {}  # pid -> [timestamps]
    
    def can_restart(self, process_id: int, policy: RestartPolicy, restart_count: int) -> bool:
        if policy == RestartPolicy.NEVER:
            return False
        if policy == RestartPolicy.ONCE:
            return restart_count < 1
        if policy in (RestartPolicy.N_TIMES, RestartPolicy.EXPONENTIAL_BACKOFF):
            if restart_count >= self._config.max_restarts:
                return False
            if self.is_failure_storm(process_id):
                return False
            return True
        return False
    
    def get_backoff_delay(self, restart_count: int) -> float:
        delay = self._config.backoff_initial * (self._config.backoff_multiplier ** restart_count)
        return min(delay, self._config.backoff_max)
    
    def is_failure_storm(self, process_id: int) -> bool:
        import time
        history = self._failure_history.get(process_id, [])
        now = time.time()
        window = self._config.failure_window_seconds
        recent = [t for t in history if now - t <= window]
        return len(recent) > self._config.max_restarts
    
    def record_failure(self, process_id: int) -> None:
        import time
        if process_id not in self._failure_history:
            self._failure_history[process_id] = []
        self._failure_history[process_id].append(time.time())
    
    def clear_history(self, process_id: int) -> None:
        self._failure_history.pop(process_id, None)
