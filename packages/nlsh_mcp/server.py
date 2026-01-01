#!/usr/bin/env python3
"""nlsh-remote MCP Server.

Provides MCP tools for remote command execution, file upload/download,
and working directory management via SSH tunnel to nlsh-remote.

This server implements the MCP side of the chain-of-trust security model:
- Verifies incoming messages signed by nlsh (future implementation)
- Signs outgoing messages to nlsh_remote with MCP server's Ed25519 private key

Usage:
    python -m nlsh_mcp              # Run via module
    python server.py                # Run directly

Environment Variables:
    NLSH_MCP_PRIVATE_KEY_PATH: Path to MCP server's Ed25519 private key
    NLSH_PUBLIC_KEY_PATH: Path to nlsh client's Ed25519 public key
    NLSH_REMOTE_HOST: Remote server host (default: 127.0.0.1)
    NLSH_REMOTE_PORT: Remote server port (default: 8765)
"""

import sys
from pathlib import Path
from typing import Optional

# Add parent package to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.server.fastmcp import FastMCP

from .config import get_config, ConfigurationError
from .tools import (
    nlsh_remote_execute,
    nlsh_remote_upload,
    nlsh_remote_download,
    nlsh_remote_cwd,
    nlsh_remote_status,
    nlsh_remote_ping,
)


def create_server() -> FastMCP:
    """Create and configure the MCP server.

    Returns:
        Configured FastMCP server instance

    Raises:
        ConfigurationError: If required configuration is missing
    """
    try:
        config = get_config()
    except ConfigurationError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    # Initialize FastMCP server
    mcp = FastMCP(
        name=config.server_name,
        version=config.server_version,
    )

    # Register tools with proper annotations

    @mcp.tool(
        name="nlsh_remote_execute",
        annotations={
            "title": "Execute Remote Command",
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
        }
    )
    async def execute_tool(
        command: str,
        cwd: Optional[str] = None,
        timeout: int = 300
    ) -> dict:
        """Execute a shell command on the remote server.

        Runs the specified shell command on the remote machine connected via SSH tunnel.
        The command executes in the specified working directory (or current remote cwd).

        Args:
            command: The shell command to execute (e.g., "ls -la", "pwd", "cat file.txt")
            cwd: Optional working directory. If not specified, uses current remote working directory.
            timeout: Command timeout in seconds (1-3600, default: 300)

        Returns:
            dict with keys: success (bool), stdout (str), stderr (str), returncode (int), cwd (str)

        Examples:
            - Execute "ls -la" to list files
            - Execute "grep pattern file.txt" to search
            - Execute "python script.py" to run scripts
        """
        result = await nlsh_remote_execute(command, cwd, timeout)
        return result.model_dump()

    @mcp.tool(
        name="nlsh_remote_upload",
        annotations={
            "title": "Upload File to Remote",
            "destructiveHint": True,
            "idempotentHint": True,
            "openWorldHint": True,
        }
    )
    async def upload_tool(
        local_path: str,
        remote_path: str,
        mode: str = "0644"
    ) -> dict:
        """Upload a file from the local machine to the remote server.

        Transfers the specified local file to the remote server via the secure
        WebSocket connection. Parent directories are created automatically.

        Args:
            local_path: Path to the local file to upload
            remote_path: Destination path on the remote server
            mode: Unix file permissions in octal (e.g., '0644' for rw-r--r--, '0755' for rwxr-xr-x)

        Returns:
            dict with keys: success (bool), message (str), bytes_written (int), remote_path (str)

        Examples:
            - Upload script: nlsh_remote_upload("./script.sh", "/home/user/script.sh", "0755")
            - Upload config: nlsh_remote_upload("config.json", "~/config.json")
        """
        result = await nlsh_remote_upload(local_path, remote_path, mode)
        return result.model_dump()

    @mcp.tool(
        name="nlsh_remote_download",
        annotations={
            "title": "Download File from Remote",
            "readOnlyHint": True,
            "idempotentHint": True,
            "openWorldHint": True,
        }
    )
    async def download_tool(
        remote_path: str,
        local_path: Optional[str] = None
    ) -> dict:
        """Download a file from the remote server.

        Retrieves a file from the remote server. If local_path is specified,
        saves the file there. Otherwise, returns the content base64-encoded.

        Args:
            remote_path: Path to the file on the remote server
            local_path: Optional local path to save the file. If not specified, returns content in response.

        Returns:
            dict with keys: success (bool), size (int), message (str),
                           content (str|null, base64-encoded if no local_path),
                           local_path (str|null, path where saved)

        Examples:
            - Get content: nlsh_remote_download("/etc/hosts")
            - Save locally: nlsh_remote_download("~/data.csv", "./data.csv")
        """
        result = await nlsh_remote_download(remote_path, local_path)
        return result.model_dump()

    @mcp.tool(
        name="nlsh_remote_cwd",
        annotations={
            "title": "Remote Working Directory",
            "destructiveHint": False,
            "idempotentHint": True,
        }
    )
    async def cwd_tool(path: Optional[str] = None) -> dict:
        """Get or set the remote working directory.

        If path is provided, changes to that directory and returns the new location.
        If path is omitted, returns the current working directory.

        Args:
            path: Optional path to change to. Use "~" for home directory.

        Returns:
            dict with keys: cwd (str), success (bool), message (str|null)

        Examples:
            - Get current: nlsh_remote_cwd()
            - Change dir: nlsh_remote_cwd("/home/user/project")
            - Go home: nlsh_remote_cwd("~")
        """
        result = await nlsh_remote_cwd(path)
        return result.model_dump()

    @mcp.tool(
        name="nlsh_remote_status",
        annotations={
            "title": "Connection Status",
            "readOnlyHint": True,
            "idempotentHint": True,
        }
    )
    async def status_tool() -> dict:
        """Get the current remote connection status.

        Returns information about the connection state including whether
        connected, host/port details, current working directory, and uptime.

        Returns:
            dict with keys: connected (bool), host (str), port (int),
                           cwd (str|null), uptime_seconds (float|null)
        """
        result = await nlsh_remote_status()
        return result.model_dump()

    @mcp.tool(
        name="nlsh_remote_ping",
        annotations={
            "title": "Ping Remote Server",
            "readOnlyHint": True,
            "idempotentHint": True,
        }
    )
    async def ping_tool() -> dict:
        """Check if the remote server is responsive.

        Sends a ping to verify the connection is working and measures latency.
        Use this to verify connectivity before running commands.

        Returns:
            dict with keys: alive (bool), message (str), latency_ms (float|null)
        """
        result = await nlsh_remote_ping()
        return result.model_dump()

    return mcp


# Create global server instance
mcp = create_server()


def main():
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
