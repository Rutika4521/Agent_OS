"""Testbed agents. Every agent talks to the kernel only through ctx.data["sys"]."""
from agent_os.kernel.state_machine import AgentStepResult, StepStatus

CONTINUE = AgentStepResult(StepStatus.CONTINUE)
BLOCK = AgentStepResult(StepStatus.BLOCK)


def done(output=None) -> AgentStepResult:
    return AgentStepResult(StepStatus.COMPLETED, output=output)
