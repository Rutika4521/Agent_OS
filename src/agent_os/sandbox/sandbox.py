import asyncio
import os
import time
from dataclasses import dataclass
from typing import Optional

from agent_os.config.settings import Settings, get_settings

class SandboxError(Exception):
    pass

class SandboxTimeout(SandboxError):
    pass

class SandboxDisabled(SandboxError):
    pass

@dataclass
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    execution_time: float

class SubprocessSandbox:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.timeout = getattr(self.settings.sandbox, "timeout_seconds", 30.0) if hasattr(self.settings, "sandbox") else 30.0
        self.enabled = getattr(self.settings.sandbox, "enabled", True) if hasattr(self.settings, "sandbox") else True

    async def execute(self, command: str | list[str], *, env: dict[str, str] | None = None, cwd: str | None = None, timeout: float | None = None, restricted_env: bool = True) -> SandboxResult:
        if not self.enabled:
            raise SandboxDisabled("Sandbox execution is disabled")
        
        effective_timeout = timeout if timeout is not None else self.timeout
        
        exec_env = {}
        if restricted_env:
            exec_env["PATH"] = os.environ.get("PATH", "")
        else:
            exec_env.update(os.environ)
            
        if env:
            exec_env.update(env)

        start_time = time.time()
        
        try:
            if isinstance(command, str):
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=exec_env,
                    cwd=cwd
                )
            else:
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=exec_env,
                    cwd=cwd
                )

            stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=effective_timeout)
            exit_code = process.returncode
            timed_out = False

        except asyncio.TimeoutError:
            try:
                process.kill()
            except OSError:
                pass
            timed_out = True
            exit_code = -1
            stdout_bytes, stderr_bytes = b"", b""
            raise SandboxTimeout(f"Command timed out after {effective_timeout} seconds")
        except Exception as e:
            raise SandboxError(f"Execution failed: {e}")

        execution_time = time.time() - start_time
        
        return SandboxResult(
            exit_code=exit_code if exit_code is not None else -1,
            stdout=stdout_bytes.decode(errors='replace') if stdout_bytes else "",
            stderr=stderr_bytes.decode(errors='replace') if stderr_bytes else "",
            timed_out=timed_out,
            execution_time=execution_time
        )
