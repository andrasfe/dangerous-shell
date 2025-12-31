#!/usr/bin/env python3
"""
nlsh-remote - Remote execution server for Natural Language Shell.

Accepts WebSocket connections from nlsh clients, verifies HMAC signatures,
and executes commands on the local system.

Security: Use SSH tunnel for secure access (recommended over SSL).
"""

import os
import sys
import json
import asyncio
import subprocess
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from dotenv import load_dotenv
import uvicorn

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

# Load environment variables
load_dotenv()

# Configuration
SHARED_SECRET = os.getenv("NLSH_SHARED_SECRET", "")
HOST = os.getenv("NLSH_REMOTE_HOST", "127.0.0.1")  # localhost by default (use SSH tunnel)
PORT = int(os.getenv("NLSH_REMOTE_PORT", "8765"))
SHELL_EXECUTABLE = os.getenv("NLSH_SHELL", os.getenv("SHELL", "/bin/bash"))

# Create FastAPI app
app = FastAPI(
    title="nlsh-remote",
    description="Remote execution server for Natural Language Shell"
)


def send_error(error: str, code: str = "ERROR") -> dict[str, Any]:
    """Create a signed error response."""
    response = ErrorResponse(error=error, code=code)
    return sign_message(SHARED_SECRET, MessageType.ERROR, response.to_payload())


async def handle_command(payload: dict[str, Any]) -> dict[str, Any]:
    """Handle command execution request."""
    try:
        request = CommandRequest.from_payload(payload)
    except (KeyError, TypeError) as e:
        return send_error(f"Invalid command request: {e}", "INVALID_REQUEST")

    try:
        # Determine working directory
        cwd = request.cwd if request.cwd else os.getcwd()
        if not os.path.isdir(cwd):
            return send_error(f"Directory not found: {cwd}", "DIR_NOT_FOUND")

        # Execute command
        result = await asyncio.to_thread(
            subprocess.run,
            request.command,
            shell=True,
            executable=SHELL_EXECUTABLE,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=request.timeout
        )

        response = CommandResponse(
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
            success=(result.returncode == 0)
        )
        return sign_message(SHARED_SECRET, MessageType.RESPONSE, response.to_payload())

    except subprocess.TimeoutExpired:
        return send_error(f"Command timed out after {request.timeout}s", "TIMEOUT")
    except Exception as e:
        return send_error(f"Command execution failed: {e}", "EXEC_ERROR")


async def handle_upload(payload: dict[str, Any]) -> dict[str, Any]:
    """Handle file upload request."""
    try:
        request = UploadRequest.from_payload(payload)
    except (KeyError, TypeError) as e:
        return send_error(f"Invalid upload request: {e}", "INVALID_REQUEST")

    try:
        # Resolve and validate path
        remote_path = Path(request.remote_path).expanduser().resolve()

        # Create parent directories if needed
        remote_path.parent.mkdir(parents=True, exist_ok=True)

        # Write file
        remote_path.write_bytes(request.data)

        # Set permissions
        try:
            os.chmod(remote_path, int(request.mode, 8))
        except (ValueError, OSError):
            pass  # Ignore permission errors

        response = UploadResponse(
            success=True,
            message=f"File written to {remote_path}",
            bytes_written=len(request.data)
        )
        return sign_message(SHARED_SECRET, MessageType.RESPONSE, response.to_payload())

    except PermissionError:
        return send_error(f"Permission denied: {request.remote_path}", "PERMISSION_DENIED")
    except Exception as e:
        return send_error(f"Upload failed: {e}", "UPLOAD_ERROR")


async def handle_download(payload: dict[str, Any]) -> dict[str, Any]:
    """Handle file download request."""
    try:
        request = DownloadRequest.from_payload(payload)
    except (KeyError, TypeError) as e:
        return send_error(f"Invalid download request: {e}", "INVALID_REQUEST")

    try:
        # Resolve and validate path
        remote_path = Path(request.remote_path).expanduser().resolve()

        if not remote_path.exists():
            return send_error(f"File not found: {request.remote_path}", "FILE_NOT_FOUND")

        if not remote_path.is_file():
            return send_error(f"Not a file: {request.remote_path}", "NOT_A_FILE")

        # Read file
        data = remote_path.read_bytes()

        response = DownloadResponse(
            success=True,
            data=data,
            size=len(data),
            message=f"Downloaded {len(data)} bytes"
        )
        return sign_message(SHARED_SECRET, MessageType.RESPONSE, response.to_payload())

    except PermissionError:
        return send_error(f"Permission denied: {request.remote_path}", "PERMISSION_DENIED")
    except Exception as e:
        return send_error(f"Download failed: {e}", "DOWNLOAD_ERROR")


async def handle_ping() -> dict[str, Any]:
    """Handle ping request."""
    return sign_message(SHARED_SECRET, MessageType.PONG, {"status": "ok"})


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for nlsh clients."""
    await websocket.accept()
    client_info = f"{websocket.client.host}:{websocket.client.port}" if websocket.client else "unknown"
    print(f"[+] Client connected: {client_info}")

    try:
        while True:
            # Receive message
            try:
                data = await websocket.receive_text()
                message = json.loads(data)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps(
                    send_error("Invalid JSON", "PARSE_ERROR")
                ))
                continue

            # Verify signature
            is_valid, error = verify_message(SHARED_SECRET, message)
            if not is_valid:
                print(f"[-] Auth failed from {client_info}: {error}")
                await websocket.send_text(json.dumps(
                    send_error(f"Authentication failed: {error}", "AUTH_FAILED")
                ))
                continue

            # Handle message based on type
            msg_type = message.get("type")
            payload = message.get("payload", {})

            print(f"[>] {client_info}: {msg_type}")

            if msg_type == MessageType.COMMAND:
                response = await handle_command(payload)
            elif msg_type == MessageType.UPLOAD:
                response = await handle_upload(payload)
            elif msg_type == MessageType.DOWNLOAD:
                response = await handle_download(payload)
            elif msg_type == MessageType.PING:
                response = await handle_ping()
            else:
                response = send_error(f"Unknown message type: {msg_type}", "UNKNOWN_TYPE")

            # Send response
            await websocket.send_text(json.dumps(response))

    except WebSocketDisconnect:
        print(f"[-] Client disconnected: {client_info}")
    except Exception as e:
        print(f"[!] Error with {client_info}: {e}")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "nlsh-remote"}


def main():
    """Run the server."""
    if not SHARED_SECRET:
        print("ERROR: NLSH_SHARED_SECRET not set in environment")
        print("Please set it in your .env file")
        sys.exit(1)

    print(f"Starting nlsh-remote server...")
    print(f"  Host: {HOST}")
    print(f"  Port: {PORT}")
    print(f"  Shell: {SHELL_EXECUTABLE}")
    print(f"  WebSocket: ws://{HOST}:{PORT}/ws")
    if HOST == "127.0.0.1":
        print(f"  Security: localhost only (use SSH tunnel)")
    print()

    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
