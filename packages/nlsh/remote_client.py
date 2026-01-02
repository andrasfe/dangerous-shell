"""Remote client for nlsh - connects to nlsh-remote servers via SSH tunnel."""

import os
import sys
import json
import asyncio
from pathlib import Path
from typing import Any, Union

import websockets
from nacl.signing import SigningKey

# Add shared package to path
sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.asymmetric_crypto import sign_message, load_private_key
from shared.protocol import (
    MessageType,
    CommandRequest, CommandResponse,
    UploadRequest, UploadResponse,
    DownloadRequest, DownloadResponse,
    ErrorResponse,
    CacheLookupRequest, CacheLookupResponse,
    CacheStoreExecRequest,
)


class RemoteClient:
    """Client for connecting to nlsh-remote servers."""

    def __init__(
        self,
        host: str,
        port: int,
        private_key: SigningKey,
        timeout: float = 30.0
    ):
        """Initialize remote client.

        Args:
            host: Server hostname/IP (usually localhost via SSH tunnel)
            port: Server port
            private_key: Ed25519 signing key for authentication
            timeout: Connection timeout in seconds
        """
        self.host = host
        self.port = port
        self.private_key = private_key
        self.timeout = timeout
        self.ws_url = f"ws://{host}:{port}/ws"
        self._websocket = None

    async def connect(self) -> bool:
        """Connect to the remote server."""
        try:
            ws = await asyncio.wait_for(
                websockets.connect(self.ws_url),
                timeout=self.timeout
            )
            self._websocket = ws  # type: ignore[assignment]
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
        """Send a message and wait for response."""
        if not self._websocket:
            raise ConnectionError("Not connected to remote server")

        await self._websocket.send(json.dumps(message))
        response_text = await asyncio.wait_for(
            self._websocket.recv(),
            timeout=self.timeout
        )
        response = json.loads(response_text)

        # In asymmetric mode, server sends unsigned responses over trusted SSH tunnel
        # No signature verification needed - trust is established via SSH tunnel
        return response

    async def execute_command(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int = 300
    ) -> CommandResponse:
        """Execute a command on the remote server."""
        request = CommandRequest(command=command, cwd=cwd, timeout=timeout)
        message = sign_message(
            self.private_key,
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
        """Upload a file to the remote server."""
        local_path = Path(local_path).expanduser().resolve()
        if not local_path.exists():
            raise FileNotFoundError(f"Local file not found: {local_path}")
        if not local_path.is_file():
            raise ValueError(f"Not a file: {local_path}")

        data = local_path.read_bytes()
        request = UploadRequest(remote_path=remote_path, data=data, mode=mode)
        message = sign_message(
            self.private_key,
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
        """Download a file from the remote server."""
        request = DownloadRequest(remote_path=remote_path)
        message = sign_message(
            self.private_key,
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
        """Send a ping to check connection."""
        message = sign_message(self.private_key, MessageType.PING, {"status": "ping"})
        response = await self._send_and_receive(message)
        return response["type"] == MessageType.PONG

    async def cache_lookup(self, key: str) -> CacheLookupResponse:
        """Look up a cached command by key.

        Args:
            key: UUID key to look up.

        Returns:
            CacheLookupResponse with hit/miss status and command if found.
        """
        request = CacheLookupRequest(key=key)
        message = sign_message(
            self.private_key,
            MessageType.CACHE_LOOKUP,
            request.to_payload()
        )

        response = await self._send_and_receive(message)

        if response["type"] == MessageType.ERROR:
            error = ErrorResponse.from_payload(response["payload"])
            raise RuntimeError(f"Cache lookup failed: {error.error} ({error.code})")

        return CacheLookupResponse.from_payload(response["payload"])

    async def cache_store_and_execute(
        self,
        key: str,
        command: str,
        cwd: str | None = None,
        timeout: int = 300
    ) -> CommandResponse:
        """Store a command in cache and execute it.

        Args:
            key: UUID key for the command.
            command: Shell command to store and execute.
            cwd: Working directory.
            timeout: Execution timeout in seconds.

        Returns:
            CommandResponse with execution results.
        """
        request = CacheStoreExecRequest(
            key=key,
            command=command,
            cwd=cwd,
            timeout=timeout
        )
        message = sign_message(
            self.private_key,
            MessageType.CACHE_STORE_EXEC,
            request.to_payload()
        )

        response = await self._send_and_receive(message)

        if response["type"] == MessageType.ERROR:
            error = ErrorResponse.from_payload(response["payload"])
            raise RuntimeError(f"Cache store/exec failed: {error.error} ({error.code})")

        return CommandResponse.from_payload(response["payload"])

    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()


def create_client_from_env() -> RemoteClient:
    """Create a RemoteClient from environment variables."""
    host = os.getenv("NLSH_REMOTE_HOST", "127.0.0.1")
    port = os.getenv("NLSH_REMOTE_PORT", "8765")
    private_key_path = os.getenv("NLSH_PRIVATE_KEY_PATH")

    if not private_key_path:
        raise ValueError("NLSH_PRIVATE_KEY_PATH not set")

    private_key = load_private_key(private_key_path)
    return RemoteClient(host=host, port=int(port), private_key=private_key)
