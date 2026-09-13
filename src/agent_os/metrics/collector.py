"""Agent-OS Metrics — Collector for global and per-process metrics."""
from __future__ import annotations
from dataclasses import dataclass, field

@dataclass
class ProcessMetrics:
    """Per-process metrics tracking."""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    llm_calls: int = 0
    llm_latency: float = 0.0
    tool_calls: int = 0
    tool_latency: float = 0.0
    steps: int = 0
    waiting_time: float = 0.0
    execution_time: float = 0.0
    turnaround_time: float = 0.0
    restart_count: int = 0
    failure_count: int = 0
    context_swaps: int = 0

class MetricsCollector:
    def __init__(self):
        # Global metrics
        self.process_count: int = 0
        self.running_process_count: int = 0
        self.ready_queue_length: int = 0
        self.total_steps: int = 0
        self.total_tokens: int = 0
        self.total_llm_calls: int = 0
        self.total_tool_calls: int = 0
        self.context_swaps: int = 0
        self.ipc_messages: int = 0
        self.failures: int = 0
        self.restarts: int = 0
        self.deadlocks: int = 0
        self._per_process: dict[int, ProcessMetrics] = {}
    
    def initialize_process(self, process_id: int) -> None:
        if process_id not in self._per_process:
            self._per_process[process_id] = ProcessMetrics()
    
    def record_step(self, process_id: int) -> None:
        self.total_steps += 1
        self._ensure(process_id).steps += 1
    
    def record_tokens(self, process_id: int, input_tokens: int, output_tokens: int) -> None:
        total = input_tokens + output_tokens
        self.total_tokens += total
        pm = self._ensure(process_id)
        pm.input_tokens += input_tokens
        pm.output_tokens += output_tokens
        pm.total_tokens += total
    
    def record_llm_call(self, process_id: int, latency: float) -> None:
        self.total_llm_calls += 1
        pm = self._ensure(process_id)
        pm.llm_calls += 1
        pm.llm_latency += latency
    
    def record_tool_call(self, process_id: int, latency: float) -> None:
        self.total_tool_calls += 1
        pm = self._ensure(process_id)
        pm.tool_calls += 1
        pm.tool_latency += latency
    
    def record_context_swap(self, process_id: int) -> None:
        self.context_swaps += 1
        self._ensure(process_id).context_swaps += 1
    
    def record_ipc_message(self) -> None:
        self.ipc_messages += 1
    
    def record_failure(self, process_id: int) -> None:
        self.failures += 1
        self._ensure(process_id).failure_count += 1
    
    def record_restart(self, process_id: int) -> None:
        self.restarts += 1
        self._ensure(process_id).restart_count += 1
    
    def record_deadlock(self) -> None:
        self.deadlocks += 1
    
    def update_process_count(self, count: int) -> None:
        self.process_count = count
    
    def update_running_count(self, count: int) -> None:
        self.running_process_count = count
    
    def update_ready_queue_length(self, length: int) -> None:
        self.ready_queue_length = length
    
    def get_global_metrics(self) -> dict:
        return {
            "process_count": self.process_count,
            "running_process_count": self.running_process_count,
            "ready_queue_length": self.ready_queue_length,
            "total_steps": self.total_steps,
            "total_tokens": self.total_tokens,
            "total_llm_calls": self.total_llm_calls,
            "total_tool_calls": self.total_tool_calls,
            "context_swaps": self.context_swaps,
            "ipc_messages": self.ipc_messages,
            "failures": self.failures,
            "restarts": self.restarts,
            "deadlocks": self.deadlocks,
        }
    
    def get_process_metrics(self, process_id: int) -> dict:
        pm = self._per_process.get(process_id)
        if pm is None:
            return {}
        return {
            "input_tokens": pm.input_tokens,
            "output_tokens": pm.output_tokens,
            "total_tokens": pm.total_tokens,
            "llm_calls": pm.llm_calls,
            "llm_latency": pm.llm_latency,
            "tool_calls": pm.tool_calls,
            "tool_latency": pm.tool_latency,
            "steps": pm.steps,
            "waiting_time": pm.waiting_time,
            "execution_time": pm.execution_time,
            "turnaround_time": pm.turnaround_time,
            "restart_count": pm.restart_count,
            "failure_count": pm.failure_count,
            "context_swaps": pm.context_swaps,
        }
    
    def get_all_metrics(self) -> dict:
        return {
            "global": self.get_global_metrics(),
            "per_process": {
                pid: self.get_process_metrics(pid)
                for pid in self._per_process
            },
        }
    
    def _ensure(self, process_id: int) -> ProcessMetrics:
        if process_id not in self._per_process:
            self._per_process[process_id] = ProcessMetrics()
        return self._per_process[process_id]
