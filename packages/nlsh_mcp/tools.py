"""MCP tool implementations for nlsh-remote operations.

This module defines the tool functions that are registered with FastMCP.
Each tool wraps RemoteConnectionManager methods with proper error handling
and output formatting.
"""

import base64
import time
from typing import Annotated, Optional

from .client import RemoteConnectionManager
from .models import (
    ExecuteCommandOutput,
    UploadFileOutput,
    DownloadFileOutput,
    CwdOutput,
    ConnectionStatus,
    PingOutput,
)
from .exceptions import (
    NotConnectedError,
    ConnectionFailedError,
    RemoteExecutionError,
    FileTransferError,
)


async def nlsh_remote_execute(
    command: Annotated[str, "The shell command to execute on the remote server"],
    cwd: Annotated[Optional[str], "Working directory (optional, uses current if not specified)"] = None,
    timeout: Annotated[int, "Command timeout in seconds (default 300)"] = 300
) -> ExecuteCommandOutput:
    """Execute a shell command on the remote server.

    The command runs in the specified working directory (or current remote cwd).
    Returns stdout, stderr, and exit code.

    Args:
        command: Shell command to execute
        cwd: Optional working directory
        timeout: Command timeout in seconds

    Returns:
        ExecuteCommandOutput with stdout, stderr, returncode, success, cwd

    Examples:
        - nlsh_remote_execute("ls -la") - list files
        - nlsh_remote_execute("pwd") - print working directory
        - nlsh_remote_execute("cat /etc/hostname") - read file
    """
    manager = RemoteConnectionManager.get_instance()

    try:
        await manager.ensure_connected()
        effective_cwd = cwd or manager.current_cwd or "~"

        result = await manager.execute_command(
            command=command,
            cwd=cwd,
            timeout=timeout
        )

        return ExecuteCommandOutput(
            success=result.success,
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
            cwd=effective_cwd
        )

    except ConnectionFailedError as e:
        return ExecuteCommandOutput(
            success=False,
            stdout="",
            stderr=f"Connection failed: {e}. Ensure SSH tunnel is active and nlsh_remote server is running.",
            returncode=-1,
            cwd=cwd or "~"
        )
    except RemoteExecutionError as e:
        return ExecuteCommandOutput(
            success=False,
            stdout="",
            stderr=str(e),
            returncode=e.returncode,
            cwd=cwd or "~"
        )
    except Exception as e:
        return ExecuteCommandOutput(
            success=False,
            stdout="",
            stderr=f"Unexpected error: {e}",
            returncode=-1,
            cwd=cwd or "~"
        )


async def nlsh_remote_upload(
    local_path: Annotated[str, "Path to the local file to upload"],
    remote_path: Annotated[str, "Destination path on the remote server"],
    mode: Annotated[str, "Unix file permissions (e.g., '0644')"] = "0644"
) -> UploadFileOutput:
    """Upload a file from the local machine to the remote server.

    The file is transferred via the secure WebSocket connection.
    Parent directories are created automatically if they don't exist.

    Args:
        local_path: Path to local file
        remote_path: Destination path on remote server
        mode: Unix permissions in octal (default: 0644)

    Returns:
        UploadFileOutput with success status, message, bytes_written

    Examples:
        - nlsh_remote_upload("./script.sh", "/home/user/script.sh", "0755")
        - nlsh_remote_upload("config.json", "~/config.json")
    """
    manager = RemoteConnectionManager.get_instance()

    try:
        await manager.ensure_connected()

        result = await manager.upload_file(
            local_path=local_path,
            remote_path=remote_path,
            mode=mode
        )

        return UploadFileOutput(
            success=result.success,
            message=result.message,
            bytes_written=result.bytes_written,
            remote_path=remote_path
        )

    except FileNotFoundError as e:
        return UploadFileOutput(
            success=False,
            message=str(e),
            bytes_written=0,
            remote_path=remote_path
        )
    except FileTransferError as e:
        return UploadFileOutput(
            success=False,
            message=str(e),
            bytes_written=0,
            remote_path=remote_path
        )
    except ConnectionFailedError as e:
        return UploadFileOutput(
            success=False,
            message=f"Connection failed: {e}",
            bytes_written=0,
            remote_path=remote_path
        )
    except Exception as e:
        return UploadFileOutput(
            success=False,
            message=f"Unexpected error: {e}",
            bytes_written=0,
            remote_path=remote_path
        )


async def nlsh_remote_download(
    remote_path: Annotated[str, "Path to the file on the remote server"],
    local_path: Annotated[Optional[str], "Optional local path to save the file"] = None
) -> DownloadFileOutput:
    """Download a file from the remote server.

    If local_path is specified, saves the file there.
    Otherwise, returns the file content base64-encoded in the response.

    Args:
        remote_path: Path to file on remote server
        local_path: Optional local path to save file

    Returns:
        DownloadFileOutput with success, size, content (if no local_path)

    Examples:
        - nlsh_remote_download("/etc/hosts") - returns content
        - nlsh_remote_download("~/data.csv", "./data.csv") - saves locally
    """
    manager = RemoteConnectionManager.get_instance()

    try:
        await manager.ensure_connected()

        data, result = await manager.download_file(
            remote_path=remote_path,
            local_path=local_path
        )

        return DownloadFileOutput(
            success=result.success,
            size=result.size,
            message=result.message or "Download successful",
            content=base64.b64encode(data).decode('utf-8') if data and not local_path else None,
            local_path=local_path if local_path and result.success else None
        )

    except FileTransferError as e:
        return DownloadFileOutput(
            success=False,
            size=0,
            message=str(e),
            content=None,
            local_path=None
        )
    except ConnectionFailedError as e:
        return DownloadFileOutput(
            success=False,
            size=0,
            message=f"Connection failed: {e}",
            content=None,
            local_path=None
        )
    except Exception as e:
        return DownloadFileOutput(
            success=False,
            size=0,
            message=f"Unexpected error: {e}",
            content=None,
            local_path=None
        )


async def nlsh_remote_cwd(
    path: Annotated[Optional[str], "Path to set as working directory (omit to get current)"] = None
) -> CwdOutput:
    """Get or set the remote working directory.

    If path is provided, changes to that directory.
    Always returns the current working directory.

    Args:
        path: Optional path to change to

    Returns:
        CwdOutput with current cwd, success status

    Examples:
        - nlsh_remote_cwd() - get current directory
        - nlsh_remote_cwd("/home/user/project") - change directory
        - nlsh_remote_cwd("~") - change to home
    """
    manager = RemoteConnectionManager.get_instance()

    try:
        await manager.ensure_connected()

        if path:
            # Change directory and verify
            result = await manager.execute_command(f"cd {path} && pwd")
            if result.success:
                manager.current_cwd = result.stdout.strip()
                return CwdOutput(
                    cwd=manager.current_cwd,
                    success=True,
                    message=f"Changed to {manager.current_cwd}"
                )
            else:
                return CwdOutput(
                    cwd=manager.current_cwd or "~",
                    success=False,
                    message=f"Failed to change directory: {result.stderr}"
                )

        # Just return current cwd
        return CwdOutput(
            cwd=manager.current_cwd or "~",
            success=True,
            message=None
        )

    except ConnectionFailedError as e:
        return CwdOutput(
            cwd="~",
            success=False,
            message=f"Connection failed: {e}"
        )
    except Exception as e:
        return CwdOutput(
            cwd=manager.current_cwd or "~",
            success=False,
            message=f"Error: {e}"
        )


async def nlsh_remote_status() -> ConnectionStatus:
    """Get the current remote connection status.

    Returns information about the connection state, host, port,
    and current working directory.

    Returns:
        ConnectionStatus with connection details
    """
    manager = RemoteConnectionManager.get_instance()

    return ConnectionStatus(
        connected=manager.is_connected,
        host=manager.host,
        port=manager.port,
        cwd=manager.current_cwd,
        uptime_seconds=manager.uptime_seconds
    )


async def nlsh_remote_ping() -> PingOutput:
    """Check if the remote server is responsive.

    Returns connection health status and latency.
    Use this to verify the connection is working before running commands.

    Returns:
        PingOutput with alive status, message, latency
    """
    manager = RemoteConnectionManager.get_instance()

    try:
        await manager.ensure_connected()
        is_alive, latency_ms = await manager.ping()

        return PingOutput(
            alive=is_alive,
            message="Remote server is responsive" if is_alive else "Remote server not responding",
            latency_ms=latency_ms if is_alive else None
        )

    except ConnectionFailedError as e:
        return PingOutput(
            alive=False,
            message=f"Connection failed: {e}",
            latency_ms=None
        )
    except Exception as e:
        return PingOutput(
            alive=False,
            message=f"Ping failed: {e}",
            latency_ms=None
        )
