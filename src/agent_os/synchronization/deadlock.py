"""Agent-OS Synchronization — Deadlock Detection."""

class DeadlockDetector:
    def __init__(self):
        self._graph: dict[int, set[int]] = {}
    
    def add_dependency(self, waiter_pid: int, holder_pid: int) -> None:
        if waiter_pid not in self._graph:
            self._graph[waiter_pid] = set()
        self._graph[waiter_pid].add(holder_pid)
        if holder_pid not in self._graph:
            self._graph[holder_pid] = set()
            
    def remove_dependency(self, waiter_pid: int, holder_pid: int) -> None:
        if waiter_pid in self._graph and holder_pid in self._graph[waiter_pid]:
            self._graph[waiter_pid].remove(holder_pid)
            
    def remove_process(self, pid: int) -> None:
        if pid in self._graph:
            del self._graph[pid]
        for v in self._graph.values():
            v.discard(pid)
            
    def detect_cycle(self) -> list[int] | None:
        visited = set()
        rec_stack = set()
        
        def dfs(node: int, path: list[int]) -> list[int] | None:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)
            
            for neighbor in self._graph.get(node, set()):
                if neighbor not in visited:
                    res = dfs(neighbor, path)
                    if res:
                        return res
                elif neighbor in rec_stack:
                    # Cycle detected
                    idx = path.index(neighbor)
                    return path[idx:]
                    
            rec_stack.remove(node)
            path.pop()
            return None
            
        for node in self._graph:
            if node not in visited:
                cycle = dfs(node, [])
                if cycle:
                    return cycle
        return None
        
    def select_victim(self, cycle: list[int], process_priorities: dict[int, int]) -> int:
        if not cycle:
            raise ValueError("Cycle is empty")
        
        victim = cycle[0]
        min_prio = process_priorities.get(victim, 0)
        
        for pid in cycle[1:]:
            prio = process_priorities.get(pid, 0)
            if prio < min_prio:
                min_prio = prio
                victim = pid
            elif prio == min_prio:
                if pid > victim:
                    victim = pid
                    
        return victim
        
    def clear(self) -> None:
        self._graph.clear()
