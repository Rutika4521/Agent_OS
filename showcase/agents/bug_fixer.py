"""
Bug Fixer Agent (Priority 7)

Waits for the Vulnerability Report from SecurityAuditor via IPC.
Then generates a code patch in 2 steps.

OS Features demonstrated:
  - IPC receive (WAITING state shown in dashboard)
  - Decoupled communication (Fixer never references Auditor directly)
  - Multi-step execution after IPC wakeup
"""
from __future__ import annotations
from agent_os import AgentContext, AgentStepResult, StepStatus


class BugFixerAgent:
    """
    2-step patch writer.
    Step 0: Waits for CVE report via IPC (shows WAITING in UI).
    Step 1: Draft the patch.
    Step 2: Finalize and document.
    """

    def __init__(self, ipc_manager, pid_map: dict):
        self._ipc     = ipc_manager
        self._pid_map = pid_map
        self._phase   = 0
        self._report  = None

    async def step(self, ctx: AgentContext) -> AgentStepResult:
        # Wait for IPC from Auditor
        if self._phase == 0:
            msg = await self._ipc.receive(ctx.process_id)
            if msg is None:
                print(f"  [BugFixer] Waiting for vulnerability report via IPC…")
                return AgentStepResult(status=StepStatus.WAIT, output="waiting for CVE report")

            self._report = msg.payload
            cve = self._report.get("cve", "unknown") if isinstance(self._report, dict) else "unknown"
            print(f"  [BugFixer] Received CVE report: {cve}")
            self._phase = 1

        if self._phase == 1:
            # Draft patch
            tokens = 540
            proc = ctx.data.get("process")
            if proc:
                proc.resource_usage.total_tokens  += tokens
                proc.resource_usage.input_tokens  += 180
                proc.resource_usage.output_tokens += 360
                proc.resource_usage.llm_calls     += 1
                proc.resource_usage.steps         += 1

            patch_draft = (
                "--- a/api/login.py\n"
                "+++ b/api/login.py\n"
                "- query = f\"SELECT * FROM users WHERE username='{username}'\"\n"
                "+ query = \"SELECT * FROM users WHERE username=?\"\n"
                "+ cursor.execute(query, (username,))\n"
            )
            print(f"  [BugFixer] Step 1/2 — Patch drafted ({tokens} tokens)")
            self._phase = 2
            return AgentStepResult(status=StepStatus.CONTINUE, output=patch_draft)

        elif self._phase == 2:
            # Finalize
            tokens = 220
            proc = ctx.data.get("process")
            if proc:
                proc.resource_usage.total_tokens  += tokens
                proc.resource_usage.input_tokens  += 80
                proc.resource_usage.output_tokens += 140
                proc.resource_usage.llm_calls     += 1
                proc.resource_usage.steps         += 1

            final = "PATCH APPLIED. Unit tests scheduled. PR created: fix/CVE-2024-9999"
            print(f"  [BugFixer] Step 2/2 — Patch finalized ({tokens} tokens)")
            self._phase = 3
            return AgentStepResult(status=StepStatus.COMPLETED, output=final)

        return AgentStepResult(status=StepStatus.COMPLETED, output="done")
