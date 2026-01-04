"""Remote client for nlsh - connects to nlsh-remote servers via SSH tunnel."""

import os
import sys
import json
import asyncio
import queue
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Awaitable

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
    # Server-push message types
    PushTaskStatus, PushJobComplete, PushPrompt, PushNotification,
    PushHeartbeat, PushScriptProgress, PushResourceAlert,
)


# ============================================================================
# Server-Push Message Handling Infrastructure
# ============================================================================

class PushPriority(Enum):
    """Priority levels for server-push messages."""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass
class ServerPushMessage:
    """Wrapper for server-push messages with metadata."""
    msg_type: str
    payload: dict
    priority: PushPriority = PushPriority.NORMAL
    timestamp: float = 0.0


# Handler type aliases
PushHandler = Callable[[dict], Awaitable[None]]  # Async handler
SyncPushHandler = Callable[[ServerPushMessage], None]  # Sync handler


class MessageRouter:
    """Routes server-push messages to registered handlers.

    Supports both async handlers (in the event loop thread) and
    sync handlers (in the main thread via notification queue).
    """

    def __init__(self, notification_queue: "queue.Queue | None" = None):
        """Initialize the message router.

        Args:
            notification_queue: Queue for delivering messages to main thread.
                               If None, sync notifications are disabled.
        """
        self._async_handlers: dict[str, list[PushHandler]] = {}
        self._sync_handlers: dict[str, list[SyncPushHandler]] = {}
        self._notification_queue = notification_queue
        self._lock = threading.Lock()

    def register_async(self, msg_type: str, handler: PushHandler) -> None:
        """Register an async handler for a message type.

        Async handlers run in the event loop thread.

        Args:
            msg_type: Message type to handle (e.g., "push_notification")
            handler: Async function to call with the message payload
        """
        with self._lock:
            if msg_type not in self._async_handlers:
                self._async_handlers[msg_type] = []
            self._async_handlers[msg_type].append(handler)

    def register_sync(self, msg_type: str, handler: SyncPushHandler) -> None:
        """Register a sync handler for a message type.

        Sync handlers receive messages via the notification queue
        and should be called from the main thread.

        Args:
            msg_type: Message type to handle
            handler: Sync function to call with ServerPushMessage
        """
        with self._lock:
            if msg_type not in self._sync_handlers:
                self._sync_handlers[msg_type] = []
            self._sync_handlers[msg_type].append(handler)

    def unregister(self, msg_type: str, handler: Any) -> bool:
        """Unregister a handler.

        Args:
            msg_type: Message type
            handler: Handler to remove

        Returns:
            True if handler was found and removed
        """
        with self._lock:
            if msg_type in self._async_handlers:
                try:
                    self._async_handlers[msg_type].remove(handler)
                    return True
                except ValueError:
                    pass
            if msg_type in self._sync_handlers:
                try:
                    self._sync_handlers[msg_type].remove(handler)
                    return True
                except ValueError:
                    pass
        return False

    async def route(self, message: dict) -> None:
        """Route a message to all registered handlers.

        Args:
            message: The complete server-push message
        """
        msg_type = message.get("type")
        payload = message.get("payload", {})

        if not msg_type:
            return

        # Create wrapper for sync handlers
        push_msg = ServerPushMessage(
            msg_type=msg_type,
            payload=payload,
            timestamp=message.get("timestamp", time.time()),
        )

        # Call async handlers
        with self._lock:
            async_handlers = list(self._async_handlers.get(msg_type, []))
            sync_handlers = list(self._sync_handlers.get(msg_type, []))

        for handler in async_handlers:
            try:
                await handler(payload)
            except Exception as e:
                print(f"\033[2m(async handler error for {msg_type}: {e})\033[0m")

        # Queue for sync handlers (called from main thread)
        if self._notification_queue and sync_handlers:
            for handler in sync_handlers:
                self._notification_queue.put((push_msg, handler))


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
    - Full duplex: receive loop for server-push messages
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

        # Full duplex: message routing and receive loop
        self._message_router: MessageRouter | None = None
        self._receive_task: asyncio.Task | None = None
        self._pending_requests: dict[str, asyncio.Future] = {}
        self._request_id_counter = 0
        self._pending_lock = asyncio.Lock()

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
            self._start_receive_loop()
            return True

    def set_message_router(self, router: MessageRouter) -> None:
        """Set the message router for server-push messages."""
        self._message_router = router

    def _start_ping_loop(self):
        """Start background ping task."""
        if self._ping_task and not self._ping_task.done():
            self._ping_task.cancel()
        self._ping_task = asyncio.create_task(self._ping_loop())

    def _start_receive_loop(self):
        """Start the background receive loop for all messages."""
        if self._receive_task and not self._receive_task.done():
            self._receive_task.cancel()
        self._receive_task = asyncio.create_task(self._receive_loop())

    async def _ping_loop(self):
        """Background keepalive task using correlation-based messaging."""
        while self._connected:
            try:
                await asyncio.sleep(self.ping_interval)
                if self._client and self._connected and self._client._websocket:
                    # Send ping through the correlation system
                    message = sign_message(
                        self.private_key,
                        MessageType.PING,
                        {"status": "ping"}
                    )
                    try:
                        await asyncio.wait_for(
                            self._send_and_wait(message, timeout=10.0),
                            timeout=15.0
                        )
                    except asyncio.TimeoutError:
                        # Ping timeout - connection may be dead
                        self._connected = False
                        break
            except asyncio.CancelledError:
                break
            except Exception:
                self._connected = False
                break

    async def _receive_loop(self):
        """Central receive loop for all incoming WebSocket messages.

        This loop handles both:
        1. Responses to client-initiated requests (correlation-based)
        2. Server-push messages (routed to handlers)
        """
        while self._connected:
            try:
                if not self._client or not self._client._websocket:
                    await asyncio.sleep(0.1)
                    continue

                # Receive message with timeout to allow checking _connected
                try:
                    response_text = await asyncio.wait_for(
                        self._client._websocket.recv(),
                        timeout=1.0  # Short timeout for responsiveness
                    )
                except asyncio.TimeoutError:
                    continue  # Check _connected and retry

                message = json.loads(response_text)
                msg_type = message.get("type")

                # Check if this is a response to a pending request
                request_id = message.get("request_id")
                if request_id and request_id in self._pending_requests:
                    # Complete the pending future
                    async with self._pending_lock:
                        future = self._pending_requests.pop(request_id, None)
                    if future and not future.done():
                        future.set_result(message)
                    continue

                # Check if this is a server-push message
                if msg_type and msg_type.startswith("push_"):
                    await self._handle_server_push(message)
                    continue

                # For backward compatibility: treat as response to most recent request
                # (This handles the current request-response pattern)
                if self._pending_requests:
                    async with self._pending_lock:
                        if self._pending_requests:
                            # Pop the oldest pending request
                            oldest_id = min(self._pending_requests.keys())
                            future = self._pending_requests.pop(oldest_id)
                            if not future.done():
                                future.set_result(message)

            except websockets.ConnectionClosed:
                self._connected = False
                break
            except asyncio.CancelledError:
                break
            except Exception as e:
                # Log error but continue
                print(f"\033[2m(receive error: {e})\033[0m")

    async def _handle_server_push(self, message: dict):
        """Route a server-push message to the appropriate handler."""
        if self._message_router:
            await self._message_router.route(message)

    async def ensure_connected(self) -> RemoteClient:
        """Get client, reconnecting if needed."""
        async with self._lock:
            if self._client and self._connected and self._client._websocket:
                # Trust the _connected flag - the receive loop will update it on errors
                return self._client

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
                self._start_receive_loop()
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

        # Cancel receive loop
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass

        # Cancel ping loop
        if self._ping_task:
            self._ping_task.cancel()
            try:
                await self._ping_task
            except asyncio.CancelledError:
                pass

        # Cancel any pending requests
        async with self._pending_lock:
            for future in self._pending_requests.values():
                if not future.done():
                    future.cancel()
            self._pending_requests.clear()

        if self._client:
            await self._client.disconnect()
            self._client = None

    async def _send_and_wait(
        self,
        message: dict[str, Any],
        timeout: float = 300.0
    ) -> dict[str, Any]:
        """Send a message and wait for its correlated response.

        Uses request_id for correlation with the central receive loop.
        """
        if not self._client or not self._client._websocket:
            raise ConnectionError("Not connected to remote server")

        # Generate unique request ID
        async with self._pending_lock:
            self._request_id_counter += 1
            request_id = f"req_{self._request_id_counter}"

        # Add request_id to message for correlation
        message["request_id"] = request_id

        # Create future for response
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()

        async with self._pending_lock:
            self._pending_requests[request_id] = future

        try:
            # Send the request
            await self._client._websocket.send(json.dumps(message))

            # Wait for correlated response from receive loop
            response = await asyncio.wait_for(future, timeout=timeout)
            return response

        except asyncio.TimeoutError:
            async with self._pending_lock:
                self._pending_requests.pop(request_id, None)
            raise
        except Exception:
            async with self._pending_lock:
                self._pending_requests.pop(request_id, None)
            raise

    async def execute_command(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int = 300
    ) -> CommandResponse:
        """Execute command using persistent connection with full duplex support."""
        await self.ensure_connected()

        request = CommandRequest(command=command, cwd=cwd, timeout=timeout)
        message = sign_message(
            self.private_key,
            MessageType.COMMAND,
            request.to_payload()
        )

        response = await self._send_and_wait(message, timeout=timeout + 10)

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
        """Upload file using persistent connection with full duplex support."""
        await self.ensure_connected()

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

        response = await self._send_and_wait(message, timeout=300.0)

        if response["type"] == MessageType.ERROR:
            error = ErrorResponse.from_payload(response["payload"])
            raise RuntimeError(f"Upload failed: {error.error} ({error.code})")

        return UploadResponse.from_payload(response["payload"])

    async def download_file(
        self,
        remote_path: str,
        local_path: str | Path | None = None
    ) -> tuple[bytes, DownloadResponse]:
        """Download file using persistent connection with full duplex support."""
        await self.ensure_connected()

        request = DownloadRequest(remote_path=remote_path)
        message = sign_message(
            self.private_key,
            MessageType.DOWNLOAD,
            request.to_payload()
        )

        response = await self._send_and_wait(message, timeout=300.0)

        if response["type"] == MessageType.ERROR:
            error = ErrorResponse.from_payload(response["payload"])
            raise RuntimeError(f"Download failed: {error.error} ({error.code})")

        download_response = DownloadResponse.from_payload(response["payload"])

        if local_path and download_response.data:
            local_path = Path(local_path).expanduser().resolve()
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(download_response.data)

        return download_response.data or b"", download_response

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
        """Execute script with streaming output using persistent connection.

        Note: Script execution temporarily pauses the receive loop to handle
        streaming output directly, then resumes it after completion.
        """
        await self.ensure_connected()

        if not self._client or not self._client._websocket:
            raise ConnectionError("Not connected to remote server")

        # Pause receive loop during script execution to handle streaming directly
        if self._receive_task and not self._receive_task.done():
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass

        try:
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
            await self._client._websocket.send(json.dumps(message))

            # Receive streaming output until completion
            while True:
                response_text = await asyncio.wait_for(
                    self._client._websocket.recv(),
                    timeout=timeout + 60  # Extra time for completion message
                )
                response = json.loads(response_text)

                msg_type = response["type"]
                payload = response["payload"]

                if msg_type == MessageType.SCRIPT_OUTPUT:
                    chunk = ScriptOutputChunk.from_payload(payload)
                    if on_output:
                        on_output(chunk.stream, chunk.data)

                elif msg_type == MessageType.SCRIPT_COMPLETE:
                    return ScriptCompleteResponse.from_payload(payload)

                elif msg_type == MessageType.ERROR:
                    error = ErrorResponse.from_payload(payload)
                    raise RuntimeError(f"Script execution failed: {error.error} ({error.code})")

        finally:
            # Resume receive loop
            self._start_receive_loop()


class RemoteSession:
    """Synchronous interface to persistent remote connection.

    Runs the async event loop in a background thread, providing
    synchronous methods for use in the main shell loop.

    Supports server-push message handling with sync notification.
    """

    def __init__(self, host: str, port: int, private_key: SigningKey):
        self._connection = PersistentRemoteConnection(host, port, private_key)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._started = False

        # Thread-safe notification queue for server-push messages
        self._notification_queue: queue.Queue = queue.Queue()
        self._message_router: MessageRouter | None = None

    def start(self, timeout: float = 30.0):
        """Start the background event loop and connect."""
        if self._started:
            return

        # Create message router with notification queue
        self._message_router = MessageRouter(self._notification_queue)

        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._loop_thread.start()

        # Set router on connection before connecting
        def set_router():
            self._connection.set_message_router(self._message_router)
        self._loop.call_soon_threadsafe(set_router)

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

    # =========================================================================
    # Server-Push Message Handling
    # =========================================================================

    def register_push_handler(
        self,
        msg_type: str,
        handler: SyncPushHandler,
    ) -> None:
        """Register a sync handler for server-push messages.

        Handlers are called from process_notifications() in the main thread.

        Args:
            msg_type: Message type to handle (e.g., "push_notification")
            handler: Sync function to call with ServerPushMessage
        """
        if self._message_router:
            self._message_router.register_sync(msg_type, handler)

    def register_async_push_handler(
        self,
        msg_type: str,
        handler: PushHandler,
    ) -> None:
        """Register an async handler for server-push messages.

        Handlers run in the event loop thread (background).

        Args:
            msg_type: Message type to handle
            handler: Async function to call with payload dict
        """
        if self._message_router and self._loop:
            def do_register():
                self._message_router.register_async(msg_type, handler)
            self._loop.call_soon_threadsafe(do_register)

    def process_notifications(self, max_count: int = 10) -> int:
        """Process pending server-push notifications in the main thread.

        This should be called periodically from the main shell loop,
        typically during idle time or after each user interaction.

        Args:
            max_count: Maximum notifications to process per call

        Returns:
            Number of notifications processed
        """
        processed = 0
        while processed < max_count:
            try:
                msg, handler = self._notification_queue.get_nowait()
                try:
                    handler(msg)
                except Exception as e:
                    print(f"\033[2m(notification handler error: {e})\033[0m")
                processed += 1
            except queue.Empty:
                break
        return processed

    def has_pending_notifications(self) -> bool:
        """Check if there are pending notifications."""
        return not self._notification_queue.empty()
