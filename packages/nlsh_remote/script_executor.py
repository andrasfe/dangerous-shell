"""Script execution with streaming output for nlsh-remote server."""

import asyncio
import os
import signal
import tempfile
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Coroutine


class ScriptState(str, Enum):
    """Script execution states."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass
class RunningScript:
    """Tracks a running script's state."""
    script_id: str
    process: asyncio.subprocess.Process
    temp_file: Path
    start_time: float
    state: ScriptState = ScriptState.RUNNING
    stdout_buffer: list[str] = field(default_factory=list)
    stderr_buffer: list[str] = field(default_factory=list)
    stdout_bytes: int = 0
    stderr_bytes: int = 0
    sequence: int = 0

    def next_sequence(self) -> int:
        """Get next sequence number for output ordering."""
        seq = self.sequence
        self.sequence += 1
        return seq


# Type for async output callback
OutputCallback = Callable[[str, str, str, int], Coroutine[Any, Any, None]]


class RemoteScriptExecutor:
    """Manages script execution with streaming output for the remote server.

    Uses asyncio.subprocess.Process with separate tasks for reading
    stdout/stderr, enabling true streaming over WebSocket.
    """

    def __init__(self, shell: str = "/bin/bash"):
        """Initialize the script executor.

        Args:
            shell: Path to shell interpreter
        """
        self.shell = shell
        self.running_scripts: dict[str, RunningScript] = {}
        self._temp_dir = Path(tempfile.gettempdir()) / "nlsh_scripts"
        self._temp_dir.mkdir(exist_ok=True)

    async def execute_script(
        self,
        script_id: str,
        script: str,
        on_output: OutputCallback,
        cwd: str | None = None,
        timeout: int = 3600,
        interpreter: str | None = None,
        env: dict[str, str] | None = None,
    ) -> tuple[int, float, int, int, str | None]:
        """Execute a script with streaming output.

        Args:
            script_id: Unique identifier for the script
            script: Script content
            on_output: Async callback for each output chunk
                      (script_id, stream, data, sequence)
            cwd: Working directory
            timeout: Maximum execution time in seconds
            interpreter: Script interpreter (defaults to self.shell)
            env: Additional environment variables

        Returns:
            Tuple of (returncode, duration, stdout_bytes, stderr_bytes, error_message)
        """
        # Create temporary script file
        temp_file = self._temp_dir / f"{script_id}.sh"
        temp_file.write_text(script)
        temp_file.chmod(0o700)

        # Use provided interpreter or default
        shell = interpreter or self.shell

        try:
            # Prepare environment
            process_env = os.environ.copy()
            if env:
                process_env.update(env)

            # Determine working directory
            work_dir = cwd if cwd and os.path.isdir(cwd) else os.getcwd()

            # Start process
            start_time = time.time()
            process = await asyncio.create_subprocess_exec(
                shell,
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
            )
            self.running_scripts[script_id] = running

            # Create streaming tasks
            async def stream_output(
                stream: asyncio.StreamReader,
                stream_name: str,
            ):
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    data = line.decode('utf-8', errors='replace')
                    seq = running.next_sequence()

                    if stream_name == "stdout":
                        running.stdout_buffer.append(data)
                        running.stdout_bytes += len(line)
                    else:
                        running.stderr_buffer.append(data)
                        running.stderr_bytes += len(line)

                    # Call the async output callback
                    await on_output(script_id, stream_name, data, seq)

            # Run both stream readers concurrently with timeout
            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        stream_output(process.stdout, "stdout"),
                        stream_output(process.stderr, "stderr"),
                    ),
                    timeout=timeout,
                )
                await process.wait()
                returncode = process.returncode
                error_message = None
                running.state = ScriptState.COMPLETED

            except asyncio.TimeoutError:
                # Kill process group on timeout
                await self._kill_process(process)
                returncode = -9
                error_message = f"Script timed out after {timeout}s"
                running.state = ScriptState.FAILED

            duration = time.time() - start_time
            return (
                returncode,
                duration,
                running.stdout_bytes,
                running.stderr_bytes,
                error_message,
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
            script_id: Script to cancel
            sig: Signal to send (default SIGTERM)

        Returns:
            Tuple of (was_running, partial_stdout, partial_stderr)
        """
        running = self.running_scripts.get(script_id)
        if not running or running.state != ScriptState.RUNNING:
            return False, "", ""

        running.state = ScriptState.CANCELLED

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
        return running is not None and running.state == ScriptState.RUNNING

    def cleanup(self):
        """Clean up any remaining temp files."""
        for f in self._temp_dir.glob("*.sh"):
            try:
                f.unlink()
            except OSError:
                pass


# Global executor instance
_script_executor: RemoteScriptExecutor | None = None


def get_script_executor(shell: str = "/bin/bash") -> RemoteScriptExecutor:
    """Get or create the global script executor.

    Args:
        shell: Shell interpreter path

    Returns:
        The global RemoteScriptExecutor instance
    """
    global _script_executor
    if _script_executor is None:
        _script_executor = RemoteScriptExecutor(shell)
    return _script_executor
