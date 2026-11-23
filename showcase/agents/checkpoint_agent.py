"""
Checkpoint Agent (Priority 6)

Saves a checkpoint of its state after step 1.
On step 2 it fails (simulated crash).
The Supervisor restarts it (N_TIMES policy).
On post-restart step 1, it looks up the checkpoint and restores its previous state.

OS Features demonstrated:
  - CheckpointManager.create(pid, process_state, agent_state={...})
  - CheckpointManager.list_for_process(pid)
  - CHECKPOINT_CREATED event emitted automatically
  - Checkpoint data persists across supervisor restarts
  - Integration of memory + supervisor subsystems
"""
from __future__ import annotations
from agent_os import AgentContext, AgentStepResult, StepStatus


class CheckpointAgent:
    """
    Demonstrates the full checkpoint / restore lifecycle:
      Step 1 (run 0): do work → save checkpoint
      Step 2 (run 0): crash
      Step 1 (run 1): restore from checkpoint → verify state matches
      Step 2 (run 1): complete successfully
    """

    def __init__(self, checkpoint_manager):
        self._ckpt_mgr       = checkpoint_manager
        self._step           = 0
        self._checkpoint_id  = None   # filled after first checkpoint

    async def step(self, ctx: AgentContext) -> AgentStepResult:
        self._step += 1
        proc = ctx.data.get("process")
        pid  = ctx.process_id
        restart_count = proc.restart_count if proc else 0

        # ── First run ──────────────────────────────────────────────────────
        if restart_count == 0:
            if self._step == 1:
                # Do some work
                work_result = {"records_processed": 1_247, "checksum": "a3f7b1"}
                print(f"  [Checkpoint] Step 1 — processed {work_result['records_processed']} records")

                # Save checkpoint so we can restore if we crash
                from agent_os.kernel.state_machine import ProcessState
                ckpt = await self._ckpt_mgr.create(
                    process_id=pid,
                    process_state=ProcessState.RUNNING,
                    agent_state=work_result,
                    resource_usage={
                        "steps": proc.resource_usage.steps if proc else 0,
                        "total_tokens": proc.resource_usage.total_tokens if proc else 0,
                    },
                )
                self._checkpoint_id = ckpt.checkpoint_id
                print(f"  [Checkpoint] ✓ Checkpoint saved: {ckpt.checkpoint_id[:8]}…")
                return AgentStepResult(status=StepStatus.CONTINUE, output=work_result)

            elif self._step == 2:
                print(f"  [Checkpoint] Step 2 — CRASH 💥 (simulated power failure mid-run)")
                return AgentStepResult(
                    status=StepStatus.FAILED,
                    error="SimulatedPowerFailure: process killed unexpectedly",
                )

        # ── Post-restart run ───────────────────────────────────────────────
        else:
            if self._step == 1:
                # Look for a saved checkpoint
                checkpoints = await self._ckpt_mgr.list_for_process(pid)
                if checkpoints:
                    latest = max(checkpoints, key=lambda c: c.timestamp)
                    restored = latest.agent_state
                    print(f"  [Checkpoint] Post-restart — restored from checkpoint "
                          f"{latest.checkpoint_id[:8]}…")
                    print(f"  [Checkpoint] Restored state: {restored}")
                else:
                    print(f"  [Checkpoint] Post-restart — no checkpoint found, starting fresh")
                return AgentStepResult(status=StepStatus.CONTINUE, output="state restored")

            elif self._step == 2:
                print(f"  [Checkpoint] Step 2 (post-restart) — completing successfully ✓")
                return AgentStepResult(
                    status=StepStatus.COMPLETED,
                    output="Batch job completed after checkpoint recovery",
                )

        return AgentStepResult(status=StepStatus.COMPLETED, output="done")
