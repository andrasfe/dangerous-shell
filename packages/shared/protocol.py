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
