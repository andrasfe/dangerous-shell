#!/usr/bin/env python3
"""
nlsh-remote - Remote execution server for Natural Language Shell.

Accepts WebSocket connections from nlsh-mcp servers, verifies Ed25519 signatures,
and executes commands on the local system.

Security Model (Chain of Trust):
- nlsh signs messages with nlsh_private -> nlsh_mcp verifies with nlsh_public
- nlsh_mcp re-signs with mcp_private -> nlsh_remote verifies with mcp_public
- Responses are sent over the trusted SSH tunnel (not cryptographically signed)

Security: Use SSH tunnel for secure access (recommended over SSL).
"""

import os
import sys
import json
import asyncio
import subprocess
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from dotenv import load_dotenv
import uvicorn

# Add shared package to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Try to import asymmetric crypto first (new), fall back to HMAC (legacy)
try:
    from shared.asymmetric_crypto import verify_message, load_public_key, KeyLoadError
    USE_ASYMMETRIC = True
except ImportError:
    from shared.crypto import verify_message
    USE_ASYMMETRIC = False

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
HOST = os.getenv("NLSH_REMOTE_HOST", "127.0.0.1")  # localhost by default (use SSH tunnel)
PORT = int(os.getenv("NLSH_REMOTE_PORT", "8765"))
SHELL_EXECUTABLE = os.getenv("NLSH_SHELL", os.getenv("SHELL", "/bin/bash"))

# Security configuration
if USE_ASYMMETRIC:
    # Ed25519 mode: verify with MCP server's public key
    MCP_PUBLIC_KEY_PATH = os.getenv("NLSH_MCP_PUBLIC_KEY_PATH", "")
    MCP_PUBLIC_KEY = None
    SHARED_SECRET = None  # Not used in asymmetric mode
else:
    # Legacy HMAC mode: use shared secret
    SHARED_SECRET = os.getenv("NLSH_SHARED_SECRET", "")
    MCP_PUBLIC_KEY_PATH = None
    MCP_PUBLIC_KEY = None

# Create FastAPI app
app = FastAPI(
    title="nlsh-remote",
    description="Remote execution server for Natural Language Shell"
)


def send_response(msg_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Create a response message.

    In asymmetric mode, responses are not cryptographically signed
    (trusting the SSH tunnel). In legacy mode, responses are HMAC signed.
    """
    if USE_ASYMMETRIC:
        # Asymmetric mode: send unsigned response over trusted connection
        return {
            "type": msg_type,
            "payload": payload,
        }
    else:
        # Legacy HMAC mode: sign response
        from shared.crypto import sign_message
        return sign_message(SHARED_SECRET, msg_type, payload)


def send_error(error: str, code: str = "ERROR") -> Dict[str, Any]:
    """Create an error response."""
    response = ErrorResponse(error=error, code=code)
    return send_response(MessageType.ERROR, response.to_payload())


async def handle_command(payload: Dict[str, Any]) -> Dict[str, Any]:
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
        return send_response(MessageType.RESPONSE, response.to_payload())

    except subprocess.TimeoutExpired:
        return send_error(f"Command timed out after {request.timeout}s", "TIMEOUT")
    except Exception as e:
        return send_error(f"Command execution failed: {e}", "EXEC_ERROR")


async def handle_upload(payload: Dict[str, Any]) -> Dict[str, Any]:
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
        return send_response(MessageType.RESPONSE, response.to_payload())

    except PermissionError:
        return send_error(f"Permission denied: {request.remote_path}", "PERMISSION_DENIED")
    except Exception as e:
        return send_error(f"Upload failed: {e}", "UPLOAD_ERROR")


async def handle_download(payload: Dict[str, Any]) -> Dict[str, Any]:
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
        return send_response(MessageType.RESPONSE, response.to_payload())

    except PermissionError:
        return send_error(f"Permission denied: {request.remote_path}", "PERMISSION_DENIED")
    except Exception as e:
        return send_error(f"Download failed: {e}", "DOWNLOAD_ERROR")


async def handle_ping() -> Dict[str, Any]:
    """Handle ping request."""
    return send_response(MessageType.PONG, {"status": "ok"})


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
            if USE_ASYMMETRIC:
                # Ed25519 verification with MCP public key
                is_valid, error = verify_message(MCP_PUBLIC_KEY, message)
            else:
                # Legacy HMAC verification
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
    global MCP_PUBLIC_KEY

    if USE_ASYMMETRIC:
        # Ed25519 mode: load MCP public key
        if not MCP_PUBLIC_KEY_PATH:
            print("ERROR: NLSH_MCP_PUBLIC_KEY_PATH not set in environment")
            print("This should point to the MCP server's Ed25519 public key.")
            print("Generate keys on the MCP server with: python -m shared.keygen mcp")
            print("Then copy mcp_public.key to this machine.")
            sys.exit(1)

        try:
            MCP_PUBLIC_KEY = load_public_key(MCP_PUBLIC_KEY_PATH)
            print(f"Loaded MCP public key from: {MCP_PUBLIC_KEY_PATH}")
        except KeyLoadError as e:
            print(f"ERROR: Failed to load MCP public key: {e}")
            sys.exit(1)

        security_mode = "Ed25519 asymmetric"
    else:
        # Legacy HMAC mode
        if not SHARED_SECRET:
            print("ERROR: NLSH_SHARED_SECRET not set in environment")
            print("Please set it in your .env file")
            sys.exit(1)
        security_mode = "HMAC-SHA256 (legacy)"

    print(f"Starting nlsh-remote server...")
    print(f"  Host: {HOST}")
    print(f"  Port: {PORT}")
    print(f"  Shell: {SHELL_EXECUTABLE}")
    print(f"  Security: {security_mode}")
    print(f"  WebSocket: ws://{HOST}:{PORT}/ws")
    if HOST == "127.0.0.1":
        print(f"  Network: localhost only (use SSH tunnel)")
    print()

    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
