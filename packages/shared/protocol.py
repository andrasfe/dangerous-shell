"""Protocol definitions for nlsh remote communication."""

from enum import Enum
from dataclasses import dataclass
from typing import Any
import base64


class MessageType(str, Enum):
    """Types of messages in the nlsh protocol."""
    COMMAND = "command"      # Execute a shell command
    UPLOAD = "upload"        # Upload a file to remote
    DOWNLOAD = "download"    # Download a file from remote
    RESPONSE = "response"    # Response to any request
    ERROR = "error"          # Error response
    PING = "ping"            # Keepalive ping
    PONG = "pong"            # Keepalive pong
    # Cache-related messages
    CACHE_LOOKUP = "cache_lookup"          # Look up command by key
    CACHE_STORE_EXEC = "cache_store_exec"  # Store command and execute
    CACHE_HIT = "cache_hit"                # Lookup found the key
    CACHE_MISS = "cache_miss"              # Lookup did not find key
    # Script execution messages
    SCRIPT = "script"                      # Execute a multi-line script
    SCRIPT_OUTPUT = "script_output"        # Streaming output chunk
    SCRIPT_COMPLETE = "script_complete"    # Script execution completed
    SCRIPT_CANCEL = "script_cancel"        # Cancel a running script
    SCRIPT_CANCELLED = "script_cancelled"  # Confirmation of cancellation
    # Server-push message types (server-initiated, full duplex)
    PUSH_TASK_STATUS = "push_task_status"       # Background task status update
    PUSH_JOB_COMPLETE = "push_job_complete"     # Async job completion notification
    PUSH_PROMPT = "push_prompt"                 # Server-initiated prompt/question
    PUSH_NOTIFICATION = "push_notification"     # General notification
    PUSH_HEARTBEAT = "push_heartbeat"           # Server health/status broadcast
    PUSH_SCRIPT_PROGRESS = "push_script_progress"  # Progress update for long scripts
    PUSH_RESOURCE_ALERT = "push_resource_alert"    # Resource warnings (disk full, etc.)


@dataclass
class CommandRequest:
    """Request to execute a shell command."""
    command: str
    cwd: str | None = None
    timeout: int = 300  # 5 minutes default

    def to_payload(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "cwd": self.cwd,
            "timeout": self.timeout
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "CommandRequest":
        return cls(
            command=payload["command"],
            cwd=payload.get("cwd"),
            timeout=payload.get("timeout", 300)
        )


@dataclass
class CommandResponse:
    """Response from command execution."""
    stdout: str
    stderr: str
    returncode: int
    success: bool

    def to_payload(self) -> dict[str, Any]:
        return {
            "stdout": self.stdout,
            "stderr": self.stderr,
            "returncode": self.returncode,
            "success": self.success
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "CommandResponse":
        return cls(
            stdout=payload["stdout"],
            stderr=payload["stderr"],
            returncode=payload["returncode"],
            success=payload["success"]
        )


@dataclass
class UploadRequest:
    """Request to upload a file."""
    remote_path: str
    data: bytes
    mode: str = "0644"

    def to_payload(self) -> dict[str, Any]:
        return {
            "remote_path": self.remote_path,
            "data": base64.b64encode(self.data).decode('utf-8'),
            "mode": self.mode
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "UploadRequest":
        return cls(
            remote_path=payload["remote_path"],
            data=base64.b64decode(payload["data"]),
            mode=payload.get("mode", "0644")
        )


@dataclass
class UploadResponse:
    """Response from file upload."""
    success: bool
    message: str
    bytes_written: int = 0

    def to_payload(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            "bytes_written": self.bytes_written
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "UploadResponse":
        return cls(
            success=payload["success"],
            message=payload["message"],
            bytes_written=payload.get("bytes_written", 0)
        )


@dataclass
class DownloadRequest:
    """Request to download a file."""
    remote_path: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "remote_path": self.remote_path
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "DownloadRequest":
        return cls(remote_path=payload["remote_path"])


@dataclass
class DownloadResponse:
    """Response from file download."""
    success: bool
    data: bytes | None
    size: int
    message: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "data": base64.b64encode(self.data).decode('utf-8') if self.data else None,
            "size": self.size,
            "message": self.message
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "DownloadResponse":
        data = None
        if payload.get("data"):
            data = base64.b64decode(payload["data"])
        return cls(
            success=payload["success"],
            data=data,
            size=payload["size"],
            message=payload.get("message", "")
        )


@dataclass
class ErrorResponse:
    """Error response."""
    error: str
    code: str = "UNKNOWN_ERROR"

    def to_payload(self) -> dict[str, Any]:
        return {
            "error": self.error,
            "code": self.code
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ErrorResponse":
        return cls(
            error=payload["error"],
            code=payload.get("code", "UNKNOWN_ERROR")
        )


# ============================================================================
# Cache Protocol Messages
# ============================================================================

@dataclass
class CacheLookupRequest:
    """Request to look up a cached command by key."""
    key: str  # UUID

    def to_payload(self) -> dict[str, Any]:
        return {"key": self.key}

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "CacheLookupRequest":
        return cls(key=payload["key"])


@dataclass
class CacheLookupResponse:
    """Response to cache lookup - either hit with command or miss."""
    hit: bool
    key: str
    command: str | None = None  # Only set if hit=True

    def to_payload(self) -> dict[str, Any]:
        return {
            "hit": self.hit,
            "key": self.key,
            "command": self.command
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "CacheLookupResponse":
        return cls(
            hit=payload["hit"],
            key=payload["key"],
            command=payload.get("command")
        )


@dataclass
class CacheStoreExecRequest:
    """Request to store a command and execute it."""
    key: str  # UUID
    command: str
    cwd: str | None = None
    timeout: int = 300

    def to_payload(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "command": self.command,
            "cwd": self.cwd,
            "timeout": self.timeout
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "CacheStoreExecRequest":
        return cls(
            key=payload["key"],
            command=payload["command"],
            cwd=payload.get("cwd"),
            timeout=payload.get("timeout", 300)
        )


# ============================================================================
# Script Execution Protocol Messages
# ============================================================================

@dataclass
class ScriptRequest:
    """Request to execute a shell script."""
    script_id: str                    # UUID for tracking/cancellation
    script: str                       # Multi-line script content
    interpreter: str = "/bin/bash"    # Script interpreter
    cwd: str | None = None
    timeout: int = 3600               # 1 hour default for scripts
    env: dict[str, str] | None = None  # Additional environment variables

    def to_payload(self) -> dict[str, Any]:
        return {
            "script_id": self.script_id,
            "script": self.script,
            "interpreter": self.interpreter,
            "cwd": self.cwd,
            "timeout": self.timeout,
            "env": self.env or {}
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ScriptRequest":
        return cls(
            script_id=payload["script_id"],
            script=payload["script"],
            interpreter=payload.get("interpreter", "/bin/bash"),
            cwd=payload.get("cwd"),
            timeout=payload.get("timeout", 3600),
            env=payload.get("env")
        )


@dataclass
class ScriptOutputChunk:
    """A chunk of streaming output from script execution."""
    script_id: str
    stream: str       # "stdout" or "stderr"
    data: str         # Output chunk (text)
    sequence: int     # Monotonic sequence number for ordering

    def to_payload(self) -> dict[str, Any]:
        return {
            "script_id": self.script_id,
            "stream": self.stream,
            "data": self.data,
            "sequence": self.sequence
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ScriptOutputChunk":
        return cls(
            script_id=payload["script_id"],
            stream=payload["stream"],
            data=payload["data"],
            sequence=payload["sequence"]
        )


@dataclass
class ScriptCompleteResponse:
    """Final response when script execution completes."""
    script_id: str
    returncode: int
    success: bool
    duration_seconds: float
    total_stdout_bytes: int
    total_stderr_bytes: int
    error_message: str | None = None  # Set if execution error (not script error)

    def to_payload(self) -> dict[str, Any]:
        return {
            "script_id": self.script_id,
            "returncode": self.returncode,
            "success": self.success,
            "duration_seconds": self.duration_seconds,
            "total_stdout_bytes": self.total_stdout_bytes,
            "total_stderr_bytes": self.total_stderr_bytes,
            "error_message": self.error_message
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ScriptCompleteResponse":
        return cls(
            script_id=payload["script_id"],
            returncode=payload["returncode"],
            success=payload["success"],
            duration_seconds=payload["duration_seconds"],
            total_stdout_bytes=payload["total_stdout_bytes"],
            total_stderr_bytes=payload["total_stderr_bytes"],
            error_message=payload.get("error_message")
        )


@dataclass
class ScriptCancelRequest:
    """Request to cancel a running script."""
    script_id: str
    signal: int = 15  # SIGTERM by default

    def to_payload(self) -> dict[str, Any]:
        return {
            "script_id": self.script_id,
            "signal": self.signal
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ScriptCancelRequest":
        return cls(
            script_id=payload["script_id"],
            signal=payload.get("signal", 15)
        )


@dataclass
class ScriptCancelledResponse:
    """Confirmation that script was cancelled."""
    script_id: str
    was_running: bool
    partial_stdout: str
    partial_stderr: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "script_id": self.script_id,
            "was_running": self.was_running,
            "partial_stdout": self.partial_stdout,
            "partial_stderr": self.partial_stderr
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ScriptCancelledResponse":
        return cls(
            script_id=payload["script_id"],
            was_running=payload["was_running"],
            partial_stdout=payload["partial_stdout"],
            partial_stderr=payload["partial_stderr"]
        )


# ============================================================================
# Server-Push Protocol Messages (Full Duplex)
# ============================================================================

@dataclass
class PushTaskStatus:
    """Status update for a background task."""
    task_id: str
    status: str           # "running", "completed", "failed", "cancelled"
    progress: float       # 0.0 to 1.0
    message: str | None   # Human-readable status message

    def to_payload(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "progress": self.progress,
            "message": self.message
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "PushTaskStatus":
        return cls(
            task_id=payload["task_id"],
            status=payload["status"],
            progress=payload.get("progress", 0.0),
            message=payload.get("message")
        )


@dataclass
class PushJobComplete:
    """Notification that an async job has finished."""
    job_id: str
    success: bool
    result_summary: str
    duration_seconds: float

    def to_payload(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "success": self.success,
            "result_summary": self.result_summary,
            "duration_seconds": self.duration_seconds
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "PushJobComplete":
        return cls(
            job_id=payload["job_id"],
            success=payload["success"],
            result_summary=payload.get("result_summary", ""),
            duration_seconds=payload.get("duration_seconds", 0.0)
        )


@dataclass
class PushPrompt:
    """Server-initiated prompt requiring user response."""
    prompt_id: str
    question: str
    options: list[str] | None   # e.g., ["yes", "no", "cancel"]
    timeout_seconds: int | None  # Optional timeout
    context: dict[str, Any] | None  # Additional context for display

    def to_payload(self) -> dict[str, Any]:
        return {
            "prompt_id": self.prompt_id,
            "question": self.question,
            "options": self.options,
            "timeout_seconds": self.timeout_seconds,
            "context": self.context
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "PushPrompt":
        return cls(
            prompt_id=payload["prompt_id"],
            question=payload["question"],
            options=payload.get("options"),
            timeout_seconds=payload.get("timeout_seconds"),
            context=payload.get("context")
        )


@dataclass
class PushNotification:
    """General notification from server."""
    notification_id: str
    level: str            # "info", "warning", "error"
    title: str
    message: str
    dismissable: bool = True

    def to_payload(self) -> dict[str, Any]:
        return {
            "notification_id": self.notification_id,
            "level": self.level,
            "title": self.title,
            "message": self.message,
            "dismissable": self.dismissable
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "PushNotification":
        return cls(
            notification_id=payload["notification_id"],
            level=payload.get("level", "info"),
            title=payload.get("title", ""),
            message=payload.get("message", ""),
            dismissable=payload.get("dismissable", True)
        )


@dataclass
class PushHeartbeat:
    """Server health/status broadcast."""
    server_time: float          # Unix timestamp
    uptime_seconds: float
    connected_clients: int
    load_average: float | None  # System load

    def to_payload(self) -> dict[str, Any]:
        return {
            "server_time": self.server_time,
            "uptime_seconds": self.uptime_seconds,
            "connected_clients": self.connected_clients,
            "load_average": self.load_average
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "PushHeartbeat":
        return cls(
            server_time=payload["server_time"],
            uptime_seconds=payload.get("uptime_seconds", 0.0),
            connected_clients=payload.get("connected_clients", 0),
            load_average=payload.get("load_average")
        )


@dataclass
class PushScriptProgress:
    """Progress update for long-running scripts."""
    script_id: str
    step: int             # Current step number
    total_steps: int      # Total steps
    step_name: str        # Current step description
    elapsed_seconds: float

    def to_payload(self) -> dict[str, Any]:
        return {
            "script_id": self.script_id,
            "step": self.step,
            "total_steps": self.total_steps,
            "step_name": self.step_name,
            "elapsed_seconds": self.elapsed_seconds
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "PushScriptProgress":
        return cls(
            script_id=payload["script_id"],
            step=payload.get("step", 0),
            total_steps=payload.get("total_steps", 0),
            step_name=payload.get("step_name", ""),
            elapsed_seconds=payload.get("elapsed_seconds", 0.0)
        )


@dataclass
class PushResourceAlert:
    """Resource warning (disk full, memory low, etc.)."""
    alert_id: str
    resource_type: str    # "disk", "memory", "cpu", "network"
    severity: str         # "warning", "critical"
    current_value: float  # Current usage (e.g., 0.95 for 95%)
    threshold: float      # Threshold that triggered alert
    message: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "resource_type": self.resource_type,
            "severity": self.severity,
            "current_value": self.current_value,
            "threshold": self.threshold,
            "message": self.message
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "PushResourceAlert":
        return cls(
            alert_id=payload["alert_id"],
            resource_type=payload.get("resource_type", "unknown"),
            severity=payload.get("severity", "warning"),
            current_value=payload.get("current_value", 0.0),
            threshold=payload.get("threshold", 0.0),
            message=payload.get("message", "")
        )
