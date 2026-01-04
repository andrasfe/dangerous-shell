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
    ScriptRequest, ScriptOutputChunk, ScriptCompleteResponse,
    ScriptCancelRequest, ScriptCancelledResponse,
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

    async def execute_script(
        self,
        script_id: str,
        script: str,
        on_output: Any | None = None,  # Callable[[str, str], None]
        cwd: str | None = None,
        timeout: int = 3600,
        interpreter: str = "/bin/bash",
        env: dict[str, str] | None = None,
    ) -> ScriptCompleteResponse:
        """Execute a script with streaming output.

        Args:
            script_id: Unique identifier for tracking
            script: The script content
            on_output: Callback(stream_name, data) for each output chunk
            cwd: Working directory
            timeout: Script timeout in seconds
            interpreter: Script interpreter
            env: Additional environment variables

        Returns:
            ScriptCompleteResponse with execution details
        """
        if not self._websocket:
            raise ConnectionError("Not connected to remote server")

        request = ScriptRequest(
            script_id=script_id,
            script=script,
            interpreter=interpreter,
            cwd=cwd,
            timeout=timeout,
            env=env,
        )

        message = sign_message(
            self.private_key,
            MessageType.SCRIPT,
            request.to_payload()
        )

        # Send request
        await self._websocket.send(json.dumps(message))

        # Receive streaming output until completion
        stdout_buffer: list[str] = []
        stderr_buffer: list[str] = []

        while True:
            response_text = await asyncio.wait_for(
                self._websocket.recv(),
                timeout=timeout + 60  # Extra time for completion message
            )
            response = json.loads(response_text)

            msg_type = response["type"]
            payload = response["payload"]

            if msg_type == MessageType.SCRIPT_OUTPUT:
                chunk = ScriptOutputChunk.from_payload(payload)
                if chunk.stream == "stdout":
                    stdout_buffer.append(chunk.data)
                else:
                    stderr_buffer.append(chunk.data)

                if on_output:
                    on_output(chunk.stream, chunk.data)

            elif msg_type == MessageType.SCRIPT_COMPLETE:
                return ScriptCompleteResponse.from_payload(payload)

            elif msg_type == MessageType.ERROR:
                error = ErrorResponse.from_payload(payload)
                raise RuntimeError(f"Script execution failed: {error.error} ({error.code})")

    async def cancel_script(
        self,
        script_id: str,
        signal: int = 15,
    ) -> ScriptCancelledResponse:
        """Cancel a running script.

        Args:
            script_id: ID of script to cancel
            signal: Signal to send (15=SIGTERM, 9=SIGKILL)

        Returns:
            Cancellation response with partial output
        """
        request = ScriptCancelRequest(script_id=script_id, signal=signal)
        message = sign_message(
            self.private_key,
            MessageType.SCRIPT_CANCEL,
            request.to_payload()
        )

        response = await self._send_and_receive(message)

        if response["type"] == MessageType.ERROR:
            error = ErrorResponse.from_payload(response["payload"])
            raise RuntimeError(f"Cancel failed: {error.error} ({error.code})")

        return ScriptCancelledResponse.from_payload(response["payload"])

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


class PersistentRemoteConnection:
    """Manages a persistent WebSocket connection for the entire session.

    Features:
    - Single connection reused for all commands
    - Automatic reconnection on connection loss
    - Background ping to keep connection alive
    - Thread-safe for use from synchronous code
    """

    def __init__(
        self,
        host: str,
        port: int,
        private_key: SigningKey,
        ping_interval: float = 30.0,
        reconnect_delay: float = 1.0,
        max_reconnect_attempts: int = 5
    ):
        self.host = host
        self.port = port
        self.private_key = private_key
        self.ping_interval = ping_interval
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_attempts = max_reconnect_attempts

        self._client: RemoteClient | None = None
        self._connected = False
        self._lock = asyncio.Lock()
        self._ping_task: asyncio.Task | None = None

    async def connect(self) -> bool:
        """Establish the persistent connection."""
        async with self._lock:
            if self._connected and self._client:
                return True

            self._client = RemoteClient(
                host=self.host,
                port=self.port,
                private_key=self.private_key
            )
            await self._client.connect()
            self._connected = True
            self._start_ping_loop()
            return True

    def _start_ping_loop(self):
        """Start background ping task."""
        if self._ping_task and not self._ping_task.done():
            self._ping_task.cancel()
        self._ping_task = asyncio.create_task(self._ping_loop())

    async def _ping_loop(self):
        """Background keepalive task."""
        while self._connected:
            try:
                await asyncio.sleep(self.ping_interval)
                if self._client and self._connected:
                    await self._client.ping()
            except asyncio.CancelledError:
                break
            except Exception:
                self._connected = False
                break

    async def ensure_connected(self) -> RemoteClient:
        """Get client, reconnecting if needed."""
        async with self._lock:
            if self._client and self._connected:
                try:
                    await asyncio.wait_for(self._client.ping(), timeout=5.0)
                    return self._client
                except Exception:
                    self._connected = False

            return await self._reconnect()

    async def _reconnect(self) -> RemoteClient:
        """Attempt to reconnect with exponential backoff."""
        delay = self.reconnect_delay
        for attempt in range(self.max_reconnect_attempts):
            try:
                print(f"\033[2m(reconnecting to remote, attempt {attempt + 1}...)\033[0m")

                if self._client:
                    try:
                        await self._client.disconnect()
                    except Exception:
                        pass

                self._client = RemoteClient(
                    host=self.host,
                    port=self.port,
                    private_key=self.private_key
                )
                await self._client.connect()
                self._connected = True
                self._start_ping_loop()
                print(f"\033[2m(reconnected)\033[0m")
                return self._client
            except Exception as e:
                if attempt < self.max_reconnect_attempts - 1:
                    await asyncio.sleep(delay)
                    delay *= 2

        raise ConnectionError("Failed to reconnect after max attempts")

    async def disconnect(self):
        """Clean shutdown."""
        self._connected = False
        if self._ping_task:
            self._ping_task.cancel()
            try:
                await self._ping_task
            except asyncio.CancelledError:
                pass
        if self._client:
            await self._client.disconnect()
            self._client = None

    async def execute_command(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int = 300
    ) -> CommandResponse:
        """Execute command using persistent connection."""
        client = await self.ensure_connected()
        return await client.execute_command(command, cwd=cwd, timeout=timeout)

    async def upload_file(
        self,
        local_path: str | Path,
        remote_path: str,
        mode: str = "0644"
    ) -> UploadResponse:
        """Upload file using persistent connection."""
        client = await self.ensure_connected()
        return await client.upload_file(local_path, remote_path, mode)

    async def download_file(
        self,
        remote_path: str,
        local_path: str | Path | None = None
    ) -> tuple[bytes, DownloadResponse]:
        """Download file using persistent connection."""
        client = await self.ensure_connected()
        return await client.download_file(remote_path, local_path)

    async def execute_script(
        self,
        script_id: str,
        script: str,
        on_output: Any | None = None,
        cwd: str | None = None,
        timeout: int = 3600,
        interpreter: str = "/bin/bash",
        env: dict[str, str] | None = None,
    ) -> ScriptCompleteResponse:
        """Execute script with streaming output using persistent connection."""
        client = await self.ensure_connected()
        return await client.execute_script(
            script_id=script_id,
            script=script,
            on_output=on_output,
            cwd=cwd,
            timeout=timeout,
            interpreter=interpreter,
            env=env,
        )


import threading


class RemoteSession:
    """Synchronous interface to persistent remote connection.

    Runs the async event loop in a background thread, providing
    synchronous methods for use in the main shell loop.
    """

    def __init__(self, host: str, port: int, private_key: SigningKey):
        self._connection = PersistentRemoteConnection(host, port, private_key)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._started = False

    def start(self, timeout: float = 30.0):
        """Start the background event loop and connect."""
        if self._started:
            return

        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._loop_thread.start()

        future = asyncio.run_coroutine_threadsafe(
            self._connection.connect(), self._loop
        )
        future.result(timeout=timeout)
        self._started = True

    def _run_loop(self):
        """Run event loop in background thread."""
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _run_async(self, coro, timeout: float = 300.0):
        """Run an async coroutine from sync code."""
        if not self._loop or not self._started:
            raise ConnectionError("Remote session not started")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    def execute_command(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int = 300
    ) -> tuple[bool, str, str, int]:
        """Execute command synchronously using persistent connection."""
        response = self._run_async(
            self._connection.execute_command(command, cwd=cwd, timeout=timeout),
            timeout=timeout + 10
        )
        return response.success, response.stdout, response.stderr, response.returncode

    def upload_file(
        self,
        local_path: str | Path,
        remote_path: str,
        mode: str = "0644"
    ) -> UploadResponse:
        """Upload file using persistent connection."""
        return self._run_async(
            self._connection.upload_file(local_path, remote_path, mode)
        )

    def download_file(
        self,
        remote_path: str,
        local_path: str | Path | None = None
    ) -> tuple[bytes, DownloadResponse]:
        """Download file using persistent connection."""
        return self._run_async(
            self._connection.download_file(remote_path, local_path)
        )

    def execute_script(
        self,
        script_id: str,
        script: str,
        on_output: Any | None = None,
        cwd: str | None = None,
        timeout: int = 3600,
        interpreter: str = "/bin/bash",
        env: dict[str, str] | None = None,
    ) -> ScriptCompleteResponse:
        """Execute script with streaming output."""
        return self._run_async(
            self._connection.execute_script(
                script_id=script_id,
                script=script,
                on_output=on_output,
                cwd=cwd,
                timeout=timeout,
                interpreter=interpreter,
                env=env,
            ),
            timeout=timeout + 60
        )

    def stop(self):
        """Clean shutdown of connection and event loop."""
        if not self._started:
            return

        if self._loop:
            future = asyncio.run_coroutine_threadsafe(
                self._connection.disconnect(), self._loop
            )
            try:
                future.result(timeout=5.0)
            except Exception:
                pass

            self._loop.call_soon_threadsafe(self._loop.stop)

        if self._loop_thread:
            self._loop_thread.join(timeout=2.0)

        self._started = False

    @property
    def is_connected(self) -> bool:
        """Check if session is connected."""
        return self._started and self._connection._connected
