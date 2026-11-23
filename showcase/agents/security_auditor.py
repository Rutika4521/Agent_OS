"""
Security Auditor Agent (Priority 8)

Heavy token consumer — demonstrates hard resource quota enforcement.
Waits for the Commander's IPC task, then performs a 4-step audit cycle.
On the final step it sends a Vulnerability Report to the BugFixer via IPC.

OS Features demonstrated:
  - Resource quota tracking (token burn visible in Resource Meters)
  - IPC receive (waits for Commander assignment)
  - IPC send (forwards vulnerability report to Fixer)
  - Multi-step execution (CONTINUE × 3, COMPLETED × 1)
"""
from __future__ import annotations
from agent_os import AgentContext, AgentStepResult, StepStatus

AUDIT_STEPS = [
    ("Dependency Scan",         480, "Scanning 142 npm packages for known CVEs"),
    ("Code Pattern Analysis",   620, "Running SAST on /api/login endpoint"),
    ("Authentication Audit",    510, "Reviewing JWT validation and session handling"),
    ("Vulnerability Report",    390, "Compiling findings into structured report"),
]


class SecurityAuditorAgent:
    """4-step security audit. Burns tokens. Sends CVE report to Fixer."""

    def __init__(self, ipc_manager, pid_map: dict):
        self._ipc     = ipc_manager
        self._pid_map = pid_map
        self._phase   = 0
        self._task_received = False
        self._findings: list[str] = []

    async def step(self, ctx: AgentContext) -> AgentStepResult:
        # Phase 0: Receive IPC assignment from Commander
        if self._phase == 0:
            msg = await self._ipc.receive(ctx.process_id)
            if msg is None:
                print(f"  [Auditor] Waiting for Commander task via IPC…")
                return AgentStepResult(status=StepStatus.WAIT, output="waiting for assignment")
            print(f"  [Auditor] Received assignment: {str(msg.payload)[:60]}…")
            self._phase = 1

        idx = self._phase - 1
        if idx >= len(AUDIT_STEPS):
            return AgentStepResult(status=StepStatus.COMPLETED, output=self._findings)

        name, tokens, description = AUDIT_STEPS[idx]

        # Burn tokens — visible in Resource Meters tab
        proc = ctx.data.get("process")
        if proc:
            proc.resource_usage.total_tokens  += tokens
            proc.resource_usage.input_tokens  += tokens // 3
            proc.resource_usage.output_tokens += tokens * 2 // 3
            proc.resource_usage.llm_calls     += 1
            proc.resource_usage.steps         += 1

        finding = f"[{name}] {description} — {tokens} tokens"
        self._findings.append(finding)
        print(f"  [Auditor] Step {self._phase}/{len(AUDIT_STEPS)} — {name} ({tokens} tokens)")
        self._phase += 1

        # On last step: forward report to BugFixer
        if self._phase > len(AUDIT_STEPS):
            report = {
                "severity": "CRITICAL",
                "cve": "CVE-2024-9999",
                "vector": "SQL Injection in /api/login via 'username' parameter",
                "steps_to_reproduce": "POST /api/login with username=admin'--",
                "findings": self._findings,
            }
            fixer_pid = self._pid_map.get("fixer")
            if fixer_pid:
                await self._ipc.send(ctx.process_id, fixer_pid, report)
                print(f"  [Auditor] CVE report sent → Fixer (PID {fixer_pid})")
            return AgentStepResult(status=StepStatus.COMPLETED, output=report)

        return AgentStepResult(status=StepStatus.CONTINUE, output=finding)
