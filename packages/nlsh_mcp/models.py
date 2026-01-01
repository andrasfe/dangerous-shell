"""Pydantic models for nlsh-mcp tool input/output schemas."""

from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class ExecuteCommandInput(BaseModel):
    """Input for remote command execution."""
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        extra='forbid'
    )

    command: str = Field(
        ...,
        description="The shell command to execute on the remote server",
        min_length=1,
        max_length=10000,
        examples=["ls -la", "pwd", "cat /etc/hostname"]
    )
    cwd: Optional[str] = Field(
        default=None,
        description="Working directory for command execution. If not specified, uses current remote working directory.",
        examples=["/home/user", "~/project", "/tmp"]
    )
    timeout: int = Field(
        default=300,
        ge=1,
        le=3600,
        description="Command timeout in seconds (1-3600, default: 300)"
    )


class ExecuteCommandOutput(BaseModel):
    """Output from remote command execution."""
    success: bool = Field(description="Whether the command succeeded (exit code 0)")
    stdout: str = Field(description="Standard output from the command")
    stderr: str = Field(description="Standard error from the command")
    returncode: int = Field(description="Exit code of the command")
    cwd: str = Field(description="Working directory where command was executed")


class UploadFileInput(BaseModel):
    """Input for file upload."""
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        extra='forbid'
    )

    local_path: str = Field(
        ...,
        description="Path to the local file to upload",
        min_length=1,
        examples=["./script.sh", "/tmp/data.csv", "~/config.json"]
    )
    remote_path: str = Field(
        ...,
        description="Destination path on the remote server",
        min_length=1,
        examples=["/home/user/script.sh", "~/config.json"]
    )
    mode: str = Field(
        default="0644",
        pattern=r"^[0-7]{3,4}$",
        description="Unix file permissions in octal (e.g., '0644', '0755')"
    )


class UploadFileOutput(BaseModel):
    """Output from file upload."""
    success: bool = Field(description="Whether the upload succeeded")
    message: str = Field(description="Status message")
    bytes_written: int = Field(description="Number of bytes written")
    remote_path: str = Field(description="Final path on remote server")


class DownloadFileInput(BaseModel):
    """Input for file download."""
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        extra='forbid'
    )

    remote_path: str = Field(
        ...,
        description="Path to the file on the remote server",
        min_length=1,
        examples=["/etc/hosts", "~/data.csv", "/var/log/app.log"]
    )
    local_path: Optional[str] = Field(
        default=None,
        description="Optional local path to save the file. If not specified, returns content in response."
    )


class DownloadFileOutput(BaseModel):
    """Output from file download."""
    success: bool = Field(description="Whether the download succeeded")
    size: int = Field(description="Size of downloaded file in bytes")
    message: str = Field(description="Status message")
    content: Optional[str] = Field(
        default=None,
        description="Base64-encoded file content (if local_path not specified)"
    )
    local_path: Optional[str] = Field(
        default=None,
        description="Path where file was saved (if local_path was specified)"
    )


class SetCwdInput(BaseModel):
    """Input for setting remote working directory."""
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        extra='forbid'
    )

    path: str = Field(
        ...,
        description="Path to set as the remote working directory",
        min_length=1,
        examples=["/home/user/project", "~", "/tmp"]
    )


class CwdOutput(BaseModel):
    """Output for working directory operations."""
    cwd: str = Field(description="Current remote working directory")
    success: bool = Field(description="Whether the operation succeeded")
    message: Optional[str] = Field(default=None, description="Optional status message")


class ConnectionStatus(BaseModel):
    """Remote connection status."""
    connected: bool = Field(description="Whether currently connected to remote server")
    host: str = Field(description="Remote server host (usually localhost via SSH tunnel)")
    port: int = Field(description="Remote server port")
    cwd: Optional[str] = Field(description="Current remote working directory")
    uptime_seconds: Optional[float] = Field(description="Connection uptime in seconds")


class PingOutput(BaseModel):
    """Output from ping/health check."""
    alive: bool = Field(description="Whether the remote server responded")
    message: str = Field(description="Status message")
    latency_ms: Optional[float] = Field(default=None, description="Round-trip latency in milliseconds")
