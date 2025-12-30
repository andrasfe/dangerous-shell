"""Remote client for nlsh - connects to nlsh-remote servers."""

import os
import sys
import json
import asyncio
from pathlib import Path
from typing import Any, Callable

import websockets
from websockets.exceptions import ConnectionClosed

# Add shared package to path
sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.crypto import sign_message, verify_message
from shared.protocol import (
    MessageType,
    CommandRequest, CommandResponse,
    UploadRequest, UploadResponse,
    DownloadRequest, DownloadResponse,
    ErrorResponse
)


class RemoteClient:
    """Client for connecting to nlsh-remote servers."""

    def __init__(
        self,
        host: str,
        port: int,
        shared_secret: str,
        timeout: float = 30.0
    ):
        """Initialize remote client.

        Args:
            host: Remote server hostname/IP
            port: Remote server port
            shared_secret: Shared secret for HMAC authentication
            timeout: Connection timeout in seconds
        """
        self.host = host
        self.port = port
        self.shared_secret = shared_secret
        self.timeout = timeout
        self.ws_url = f"ws://{host}:{port}/ws"
        self._websocket = None

    async def connect(self) -> bool:
        """Connect to the remote server.

        Returns:
            True if connection successful
        """
        try:
            self._websocket = await asyncio.wait_for(
                websockets.connect(self.ws_url),
                timeout=self.timeout
            )
            return True
        except asyncio.TimeoutError:
            raise ConnectionError(f"Connection timed out: {self.ws_url}")
        except Exception as e:
            raise ConnectionError(f"Failed to connect to {self.ws_url}: {e}")

    async def disconnect(self):
        """Disconnect from the remote server."""
        if self._websocket:
            await self._websocket.close()
            self._websocket = None

    async def _send_and_receive(self, message: dict[str, Any]) -> dict[str, Any]:
        """Send a message and wait for response.

        Args:
            message: Signed message to send

        Returns:
            Response message dict
        """
        if not self._websocket:
            raise ConnectionError("Not connected to remote server")

        await self._websocket.send(json.dumps(message))
        response_text = await asyncio.wait_for(
            self._websocket.recv(),
            timeout=self.timeout
        )
        response = json.loads(response_text)

        # Verify response signature
        is_valid, error = verify_message(self.shared_secret, response)
        if not is_valid:
            raise ValueError(f"Invalid response signature: {error}")

        return response

    async def execute_command(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int = 300
    ) -> CommandResponse:
        """Execute a command on the remote server.

        Args:
            command: Shell command to execute
            cwd: Working directory (default: server's cwd)
            timeout: Command timeout in seconds

        Returns:
            CommandResponse with stdout, stderr, returncode
        """
        request = CommandRequest(command=command, cwd=cwd, timeout=timeout)
        message = sign_message(
            self.shared_secret,
            MessageType.COMMAND,
            request.to_payload()
        )

        response = await self._send_and_receive(message)

        if response["type"] == MessageType.ERROR:
            error = ErrorResponse.from_payload(response["payload"])
            raise RuntimeError(f"Remote error: {error.error} ({error.code})")

        return CommandResponse.from_payload(response["payload"])

    async def upload_file(
        self,
        local_path: str | Path,
        remote_path: str,
        mode: str = "0644"
    ) -> UploadResponse:
        """Upload a file to the remote server.

        Args:
            local_path: Local file path to upload
            remote_path: Destination path on remote server
            mode: File permissions (octal string)

        Returns:
            UploadResponse with success status
        """
        local_path = Path(local_path).expanduser().resolve()
        if not local_path.exists():
            raise FileNotFoundError(f"Local file not found: {local_path}")
        if not local_path.is_file():
            raise ValueError(f"Not a file: {local_path}")

        data = local_path.read_bytes()
        request = UploadRequest(remote_path=remote_path, data=data, mode=mode)
        message = sign_message(
            self.shared_secret,
            MessageType.UPLOAD,
            request.to_payload()
        )

        response = await self._send_and_receive(message)

        if response["type"] == MessageType.ERROR:
            error = ErrorResponse.from_payload(response["payload"])
            raise RuntimeError(f"Upload failed: {error.error} ({error.code})")

        return UploadResponse.from_payload(response["payload"])

    async def download_file(
        self,
        remote_path: str,
        local_path: str | Path | None = None
    ) -> tuple[bytes, DownloadResponse]:
        """Download a file from the remote server.

        Args:
            remote_path: Remote file path to download
            local_path: Optional local path to save file

        Returns:
            Tuple of (file_data, DownloadResponse)
        """
        request = DownloadRequest(remote_path=remote_path)
        message = sign_message(
            self.shared_secret,
            MessageType.DOWNLOAD,
            request.to_payload()
        )

        response = await self._send_and_receive(message)

        if response["type"] == MessageType.ERROR:
            error = ErrorResponse.from_payload(response["payload"])
            raise RuntimeError(f"Download failed: {error.error} ({error.code})")

        download_response = DownloadResponse.from_payload(response["payload"])

        if local_path and download_response.data:
            local_path = Path(local_path).expanduser().resolve()
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(download_response.data)

        return download_response.data or b"", download_response

    async def ping(self) -> bool:
        """Send a ping to check connection.

        Returns:
            True if pong received
        """
        message = sign_message(self.shared_secret, MessageType.PING, {"status": "ping"})
        response = await self._send_and_receive(message)
        return response["type"] == MessageType.PONG

    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()


def create_client_from_env() -> RemoteClient:
    """Create a RemoteClient from environment variables.

    Expected env vars:
        NLSH_REMOTE_HOST: Remote server host
        NLSH_REMOTE_PORT: Remote server port
        NLSH_SHARED_SECRET: Shared secret for authentication

    Returns:
        Configured RemoteClient instance
    """
    host = os.getenv("NLSH_REMOTE_HOST")
    port = os.getenv("NLSH_REMOTE_PORT")
    secret = os.getenv("NLSH_SHARED_SECRET")

    if not host:
        raise ValueError("NLSH_REMOTE_HOST not set")
    if not port:
        raise ValueError("NLSH_REMOTE_PORT not set")
    if not secret:
        raise ValueError("NLSH_SHARED_SECRET not set")

    return RemoteClient(
        host=host,
        port=int(port),
        shared_secret=secret
    )


# Synchronous wrappers for convenience
def run_remote_command(
    host: str,
    port: int,
    shared_secret: str,
    command: str,
    cwd: str | None = None
) -> CommandResponse:
    """Synchronous wrapper for remote command execution."""
    async def _run():
        async with RemoteClient(host, port, shared_secret) as client:
            return await client.execute_command(command, cwd)
    return asyncio.run(_run())


def upload_file_sync(
    host: str,
    port: int,
    shared_secret: str,
    local_path: str,
    remote_path: str
) -> UploadResponse:
    """Synchronous wrapper for file upload."""
    async def _run():
        async with RemoteClient(host, port, shared_secret) as client:
            return await client.upload_file(local_path, remote_path)
    return asyncio.run(_run())


def download_file_sync(
    host: str,
    port: int,
    shared_secret: str,
    remote_path: str,
    local_path: str | None = None
) -> tuple[bytes, DownloadResponse]:
    """Synchronous wrapper for file download."""
    async def _run():
        async with RemoteClient(host, port, shared_secret) as client:
            return await client.download_file(remote_path, local_path)
    return asyncio.run(_run())
