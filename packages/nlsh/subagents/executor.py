"""ScriptExecutor subagent - executes scripts with streaming output."""

import asyncio
import os
import re
import signal
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from subagents.base import BaseSubagent
from script_types import (
    GeneratedScript,
    ExecutionResult,
    ExecutionStatus,
)


@dataclass
class RunningScript:
    """Tracks a running script's state."""
    script_id: str
    process: asyncio.subprocess.Process
    temp_file: Path
    start_time: float
    status: ExecutionStatus = ExecutionStatus.RUNNING
    stdout_buffer: list[str] = field(default_factory=list)
    stderr_buffer: list[str] = field(default_factory=list)
    stdout_bytes: int = 0
    stderr_bytes: int = 0
    sequence: int = 0
    steps_completed: int = 0
    total_steps: int = 0

    def next_sequence(self) -> int:
        """Get next sequence number for output ordering."""
        seq = self.sequence
        self.sequence += 1
        return seq


# Callback type for streaming output
OutputCallback = Callable[[str, str], None]  # (stream_name, data)


class ScriptExecutor(BaseSubagent[ExecutionResult]):
    """Executes shell scripts with streaming output.

    Features:
    - Streaming stdout/stderr in real-time
    - Progress tracking via step markers
    - Cancellation via SIGTERM/SIGKILL
    - Timeout enforcement
    - Temp file cleanup
    """

    def __init__(self, shell: str = "/bin/bash"):
        """Initialize the script executor.

        Args:
            shell: Path to shell interpreter
        """
        super().__init__("ScriptExecutor")
        self.shell = shell
        self.running_scripts: dict[str, RunningScript] = {}
        self._temp_dir = Path(tempfile.gettempdir()) / "nlsh_scripts"
        self._temp_dir.mkdir(exist_ok=True)

    async def process(
        self,
        script: GeneratedScript,
        cwd: str | None = None,
        timeout: int = 3600,
        on_output: OutputCallback | None = None,
        env: dict[str, str] | None = None,
    ) -> ExecutionResult:
        """Execute a script with streaming output.

        Args:
            script: The GeneratedScript to execute
            cwd: Working directory
            timeout: Maximum execution time in seconds
            on_output: Callback for streaming output
            env: Additional environment variables

        Returns:
            ExecutionResult with full execution details
        """
        script_id = str(uuid.uuid4())
        return await self.execute_script(
            script_id=script_id,
            script_content=script.script,
            cwd=cwd,
            timeout=timeout,
            on_output=on_output,
            env=env,
            total_steps=len(script.steps),
        )

    async def execute_script(
        self,
        script_id: str,
        script_content: str,
        cwd: str | None = None,
        timeout: int = 3600,
        on_output: OutputCallback | None = None,
        env: dict[str, str] | None = None,
        total_steps: int = 0,
    ) -> ExecutionResult:
        """Execute a script by content.

        Args:
            script_id: Unique identifier for tracking
            script_content: The script content to execute
            cwd: Working directory
            timeout: Maximum execution time
            on_output: Callback for streaming output
            env: Additional environment variables
            total_steps: Total number of steps for progress tracking

        Returns:
            ExecutionResult with execution details
        """
        # Create temporary script file
        temp_file = self._temp_dir / f"{script_id}.sh"
        temp_file.write_text(script_content)
        temp_file.chmod(0o700)

        # Prepare environment
        process_env = os.environ.copy()
        if env:
            process_env.update(env)

        # Determine working directory
        work_dir = cwd if cwd and os.path.isdir(cwd) else os.getcwd()

        start_time = time.time()
        stdout_buffer: list[str] = []
        stderr_buffer: list[str] = []
        steps_completed = 0
        error_message: str | None = None

        try:
            # Start process
            process = await asyncio.create_subprocess_exec(
                self.shell,
                str(temp_file),
                cwd=work_dir,
                env=process_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,  # For process group signaling
            )

            # Track the running script
            running = RunningScript(
                script_id=script_id,
                process=process,
                temp_file=temp_file,
                start_time=start_time,
                total_steps=total_steps,
            )
            self.running_scripts[script_id] = running

            # Stream output
            async def stream_output(
                stream: asyncio.StreamReader,
                stream_name: str,
                buffer: list[str],
            ):
                nonlocal steps_completed
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    data = line.decode('utf-8', errors='replace')
                    buffer.append(data)

                    # Track step progress from log markers
                    step_match = re.search(r'\[Step\s+(\d+)/(\d+)\]', data)
                    if step_match:
                        steps_completed = int(step_match.group(1))
                        running.steps_completed = steps_completed

                    # Call output callback
                    if on_output:
                        on_output(stream_name, data)

            # Run both stream readers concurrently with timeout
            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        stream_output(process.stdout, "stdout", stdout_buffer),
                        stream_output(process.stderr, "stderr", stderr_buffer),
                    ),
                    timeout=timeout,
                )
                await process.wait()
                returncode = process.returncode
                running.status = ExecutionStatus.COMPLETED

            except asyncio.TimeoutError:
                # Kill process group on timeout
                await self._kill_process(process)
                returncode = -9
                error_message = f"Script timed out after {timeout}s"
                running.status = ExecutionStatus.FAILED

            duration = time.time() - start_time

            return ExecutionResult(
                script_id=script_id,
                returncode=returncode,
                success=(returncode == 0 and error_message is None),
                duration_seconds=duration,
                stdout="".join(stdout_buffer),
                stderr="".join(stderr_buffer),
                steps_completed=steps_completed,
                total_steps=total_steps,
                error_message=error_message,
            )

        finally:
            # Cleanup
            self.running_scripts.pop(script_id, None)
            try:
                temp_file.unlink()
            except OSError:
                pass

    async def cancel_script(
        self,
        script_id: str,
        sig: int = signal.SIGTERM,
    ) -> tuple[bool, str, str]:
        """Cancel a running script.

        Args:
            script_id: ID of script to cancel
            sig: Signal to send (default SIGTERM)

        Returns:
            Tuple of (was_running, partial_stdout, partial_stderr)
        """
        running = self.running_scripts.get(script_id)
        if not running or running.status != ExecutionStatus.RUNNING:
            return False, "", ""

        running.status = ExecutionStatus.CANCELLED

        await self._kill_process(running.process, sig)

        return (
            True,
            "".join(running.stdout_buffer),
            "".join(running.stderr_buffer),
        )

    async def _kill_process(
        self,
        process: asyncio.subprocess.Process,
        sig: int = signal.SIGTERM,
    ):
        """Kill a process and its process group.

        Args:
            process: The process to kill
            sig: Signal to send
        """
        try:
            # Send signal to process group
            os.killpg(os.getpgid(process.pid), sig)
        except (ProcessLookupError, OSError):
            pass

        # Wait briefly for graceful shutdown
        try:
            await asyncio.wait_for(process.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            # Force kill if SIGTERM didn't work
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass

    def is_running(self, script_id: str) -> bool:
        """Check if a script is currently running."""
        running = self.running_scripts.get(script_id)
        return running is not None and running.status == ExecutionStatus.RUNNING

    def get_progress(self, script_id: str) -> tuple[int, int] | None:
        """Get current progress for a running script.

        Returns:
            Tuple of (steps_completed, total_steps) or None if not found
        """
        running = self.running_scripts.get(script_id)
        if running:
            return running.steps_completed, running.total_steps
        return None

    def cleanup(self):
        """Clean up any remaining temp files."""
        for f in self._temp_dir.glob("*.sh"):
            try:
                f.unlink()
            except OSError:
                pass
