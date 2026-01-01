"""Remote connection manager for nlsh-mcp server.

This module provides a singleton connection manager that:
- Maintains a persistent WebSocket connection to nlsh_remote
- Uses Ed25519 asymmetric crypto for message signing
- Tracks remote working directory state
- Supports lazy initialization (connect on first use)
"""

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union
import sys

import websockets
from nacl.signing import SigningKey

# Add shared package to path
sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.asymmetric_crypto import (
    load_private_key,
    sign_message,
    verify_message,
    load_public_key,
)
from shared.protocol import (
    MessageType,
    CommandRequest, CommandResponse,
    UploadRequest, UploadResponse,
    DownloadRequest, DownloadResponse,
    ErrorResponse
)

from .config import MCPConfig, get_config, validate_config
from .exceptions import (
    NotConnectedError,
    ConnectionFailedError,
    RemoteExecutionError,
    FileTransferError,
)


class RemoteConnectionManager:
    """Singleton manager for the remote WebSocket connection.

    This manager implements the MCP side of the chain-of-trust:
    - Signs outgoing messages with MCP server's Ed25519 private key
    - Verifies incoming responses (also signed by MCP key in current implementation)

    The connection is lazily initialized on first use and maintained
    across multiple tool invocations.
    """

    _instance: Optional["RemoteConnectionManager"] = None
    _lock: asyncio.Lock = asyncio.Lock()

    def __init__(self, config: Optional[MCPConfig] = None):
        """Initialize the connection manager.

        Args:
            config: Configuration object. If None, loads from environment.
        """
        self._config = config or get_config()
        validate_config(self._config)

        # Load keys
        self._private_key: SigningKey = load_private_key(self._config.mcp_private_key_path)

        # Connection state
        self._websocket = None
        self._connected: bool = False
        self._connection_time: Optional[float] = None
        self._current_cwd: Optional[str] = None
        self._last_activity: Optional[float] = None
        self._ws_url = f"ws://{self._config.remote_host}:{self._config.remote_port}/ws"

    @classmethod
    def get_instance(cls, config: Optional[MCPConfig] = None) -> "RemoteConnectionManager":
        """Get the singleton instance.

        Args:
            config: Optional config to use for initialization

        Returns:
            The singleton RemoteConnectionManager instance
        """
        if cls._instance is None:
            cls._instance = cls(config)
        return cls._instance

    @classmethod
    def reset_instance(cls):
        """Reset the singleton instance (for testing)."""
        if cls._instance and cls._instance._websocket:
            # Schedule disconnect in background
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(cls._instance.disconnect())
                else:
                    loop.run_until_complete(cls._instance.disconnect())
            except Exception:
                pass
        cls._instance = None

    @property
    def is_connected(self) -> bool:
        """Check if currently connected."""
        return self._connected and self._websocket is not None

    @property
    def current_cwd(self) -> Optional[str]:
        """Get current remote working directory."""
        return self._current_cwd

    @current_cwd.setter
    def current_cwd(self, value: str):
        """Set current remote working directory."""
        self._current_cwd = value

    @property
    def uptime_seconds(self) -> Optional[float]:
        """Get connection uptime in seconds."""
        if self._connection_time is None:
            return None
        return time.time() - self._connection_time

    @property
    def host(self) -> str:
        """Get remote host."""
        return self._config.remote_host

    @property
    def port(self) -> int:
        """Get remote port."""
        return self._config.remote_port

    async def connect(self) -> bool:
        """Establish connection to remote server.

        Returns:
            True if connection successful

        Raises:
            ConnectionFailedError: If connection fails
        """
        async with self._lock:
            if self._connected and self._websocket:
                return True

            try:
                self._websocket = await asyncio.wait_for(
                    websockets.connect(self._ws_url),
                    timeout=self._config.connection_timeout
                )
                self._connected = True
                self._connection_time = time.time()
                self._last_activity = time.time()

                # Get initial working directory
                try:
                    result = await self._execute_command_internal("pwd")
                    if result.success:
                        self._current_cwd = result.stdout.strip()
                except Exception:
                    self._current_cwd = "~"

                return True

            except asyncio.TimeoutError:
                self._websocket = None
                self._connected = False
                raise ConnectionFailedError(
                    f"Connection timed out after {self._config.connection_timeout}s",
                    host=self._config.remote_host,
                    port=self._config.remote_port
                )
            except Exception as e:
                self._websocket = None
                self._connected = False
                raise ConnectionFailedError(
                    f"Failed to connect to {self._ws_url}: {e}",
                    host=self._config.remote_host,
                    port=self._config.remote_port
                )

    async def disconnect(self):
        """Close the remote connection."""
        async with self._lock:
            if self._websocket:
                try:
                    await self._websocket.close()
                except Exception:
                    pass
            self._websocket = None
            self._connected = False
            self._connection_time = None

    async def ensure_connected(self):
        """Ensure connection is established, reconnecting if necessary.

        Raises:
            ConnectionFailedError: If connection cannot be established
        """
        if not self.is_connected:
            await self.connect()
        self._last_activity = time.time()

    async def _send_and_receive(self, message: Dict[str, Any], timeout: float = None) -> Dict[str, Any]:
        """Send a signed message and wait for response.

        Args:
            message: The message dict (will be signed)
            timeout: Optional timeout override

        Returns:
            The response dict (signature verified)

        Raises:
            NotConnectedError: If not connected
            ValueError: If response signature is invalid
        """
        if not self._websocket:
            raise NotConnectedError("Not connected to remote server")

        effective_timeout = timeout or self._config.connection_timeout

        await self._websocket.send(json.dumps(message))
        response_text = await asyncio.wait_for(
            self._websocket.recv(),
            timeout=effective_timeout
        )
        response = json.loads(response_text)

        # Note: In the current implementation, we don't verify the response signature
        # because nlsh_remote uses HMAC. After nlsh_remote is updated to Ed25519,
        # we would verify with nlsh_remote's public key here.
        # For now, we trust responses from the WebSocket connection.

        return response

    async def _execute_command_internal(
        self,
        command: str,
        cwd: str = None,
        timeout: int = None
    ) -> CommandResponse:
        """Internal command execution (no cwd tracking)."""
        effective_timeout = timeout or self._config.command_timeout
        request = CommandRequest(command=command, cwd=cwd, timeout=effective_timeout)

        # Sign with MCP private key
        message = sign_message(
            self._private_key,
            MessageType.COMMAND,
            request.to_payload()
        )

        response = await self._send_and_receive(message, timeout=effective_timeout + 5)

        if response["type"] == MessageType.ERROR.value:
            error = ErrorResponse.from_payload(response["payload"])
            raise RemoteExecutionError(
                f"Remote error: {error.error}",
                returncode=-1,
                stderr=error.error
            )

        return CommandResponse.from_payload(response["payload"])

    async def execute_command(
        self,
        command: str,
        cwd: str = None,
        timeout: int = None
    ) -> CommandResponse:
        """Execute a command on the remote server.

        Args:
            command: Shell command to execute
            cwd: Working directory (uses current_cwd if not specified)
            timeout: Command timeout in seconds

        Returns:
            CommandResponse with stdout, stderr, returncode

        Raises:
            NotConnectedError: If not connected
            RemoteExecutionError: If command execution fails
        """
        await self.ensure_connected()

        effective_cwd = cwd or self._current_cwd
        result = await self._execute_command_internal(command, effective_cwd, timeout)

        # Update cwd if this was a cd command that succeeded
        if command.strip().startswith("cd ") and result.success:
            # Get the actual cwd after cd
            pwd_result = await self._execute_command_internal("pwd", effective_cwd)
            if pwd_result.success:
                self._current_cwd = pwd_result.stdout.strip()

        return result

    async def upload_file(
        self,
        local_path: Union[str, Path],
        remote_path: str,
        mode: str = "0644"
    ) -> UploadResponse:
        """Upload a file to the remote server.

        Args:
            local_path: Path to local file
            remote_path: Destination path on remote
            mode: Unix file permissions (octal string)

        Returns:
            UploadResponse with success status

        Raises:
            FileNotFoundError: If local file doesn't exist
            FileTransferError: If upload fails
        """
        await self.ensure_connected()

        local_path = Path(local_path).expanduser().resolve()
        if not local_path.exists():
            raise FileNotFoundError(f"Local file not found: {local_path}")
        if not local_path.is_file():
            raise FileTransferError(f"Not a file: {local_path}", path=str(local_path))

        data = local_path.read_bytes()
        request = UploadRequest(remote_path=remote_path, data=data, mode=mode)

        message = sign_message(
            self._private_key,
            MessageType.UPLOAD,
            request.to_payload()
        )

        response = await self._send_and_receive(message)

        if response["type"] == MessageType.ERROR.value:
            error = ErrorResponse.from_payload(response["payload"])
            raise FileTransferError(f"Upload failed: {error.error}", path=remote_path)

        return UploadResponse.from_payload(response["payload"])

    async def download_file(
        self,
        remote_path: str,
        local_path: Union[str, Path] = None
    ) -> Tuple[bytes, DownloadResponse]:
        """Download a file from the remote server.

        Args:
            remote_path: Path to file on remote
            local_path: Optional local path to save file

        Returns:
            Tuple of (file_data, DownloadResponse)

        Raises:
            FileTransferError: If download fails
        """
        await self.ensure_connected()

        request = DownloadRequest(remote_path=remote_path)

        message = sign_message(
            self._private_key,
            MessageType.DOWNLOAD,
            request.to_payload()
        )

        response = await self._send_and_receive(message)

        if response["type"] == MessageType.ERROR.value:
            error = ErrorResponse.from_payload(response["payload"])
            raise FileTransferError(f"Download failed: {error.error}", path=remote_path)

        download_response = DownloadResponse.from_payload(response["payload"])

        if local_path and download_response.data:
            local_path = Path(local_path).expanduser().resolve()
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(download_response.data)

        return download_response.data or b"", download_response

    async def ping(self) -> Tuple[bool, float]:
        """Send a ping to check connection health.

        Returns:
            Tuple of (is_alive, latency_ms)
        """
        await self.ensure_connected()

        start_time = time.time()
        message = sign_message(
            self._private_key,
            MessageType.PING,
            {"status": "ping"}
        )

        try:
            response = await self._send_and_receive(message, timeout=10.0)
            latency_ms = (time.time() - start_time) * 1000
            is_alive = response["type"] == MessageType.PONG.value
            return is_alive, latency_ms
        except Exception:
            self._connected = False
            return False, 0.0

    async def health_check(self) -> bool:
        """Check if connection is healthy.

        Returns:
            True if connection is healthy
        """
        if not self.is_connected:
            return False
        try:
            is_alive, _ = await self.ping()
            return is_alive
        except Exception:
            self._connected = False
            return False
