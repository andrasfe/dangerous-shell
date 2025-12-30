"""Unit tests for shared protocol module."""

import pytest
import base64
from protocol import (
    MessageType,
    CommandRequest, CommandResponse,
    UploadRequest, UploadResponse,
    DownloadRequest, DownloadResponse,
    ErrorResponse
)


class TestMessageType:
    """Tests for MessageType enum."""

    def test_message_types_exist(self):
        assert MessageType.COMMAND == "command"
        assert MessageType.UPLOAD == "upload"
        assert MessageType.DOWNLOAD == "download"
        assert MessageType.RESPONSE == "response"
        assert MessageType.ERROR == "error"
        assert MessageType.PING == "ping"
        assert MessageType.PONG == "pong"


class TestCommandRequest:
    """Tests for CommandRequest."""

    def test_to_payload(self):
        req = CommandRequest(command="ls -la", cwd="/tmp", timeout=60)
        payload = req.to_payload()

        assert payload["command"] == "ls -la"
        assert payload["cwd"] == "/tmp"
        assert payload["timeout"] == 60

    def test_from_payload(self):
        payload = {"command": "pwd", "cwd": "/home", "timeout": 120}
        req = CommandRequest.from_payload(payload)

        assert req.command == "pwd"
        assert req.cwd == "/home"
        assert req.timeout == 120

    def test_default_values(self):
        req = CommandRequest(command="echo hello")
        assert req.cwd is None
        assert req.timeout == 300

    def test_roundtrip(self):
        original = CommandRequest(command="cat file.txt", cwd="/var/log", timeout=30)
        payload = original.to_payload()
        restored = CommandRequest.from_payload(payload)

        assert restored.command == original.command
        assert restored.cwd == original.cwd
        assert restored.timeout == original.timeout


class TestCommandResponse:
    """Tests for CommandResponse."""

    def test_to_payload(self):
        resp = CommandResponse(
            stdout="output",
            stderr="error",
            returncode=1,
            success=False
        )
        payload = resp.to_payload()

        assert payload["stdout"] == "output"
        assert payload["stderr"] == "error"
        assert payload["returncode"] == 1
        assert payload["success"] is False

    def test_from_payload(self):
        payload = {
            "stdout": "hello world",
            "stderr": "",
            "returncode": 0,
            "success": True
        }
        resp = CommandResponse.from_payload(payload)

        assert resp.stdout == "hello world"
        assert resp.stderr == ""
        assert resp.returncode == 0
        assert resp.success is True


class TestUploadRequest:
    """Tests for UploadRequest."""

    def test_to_payload_encodes_base64(self):
        data = b"binary content here"
        req = UploadRequest(remote_path="/tmp/file.bin", data=data, mode="0755")
        payload = req.to_payload()

        assert payload["remote_path"] == "/tmp/file.bin"
        assert payload["mode"] == "0755"
        # Verify base64 encoding
        assert base64.b64decode(payload["data"]) == data

    def test_from_payload_decodes_base64(self):
        data = b"test data"
        payload = {
            "remote_path": "/tmp/test.txt",
            "data": base64.b64encode(data).decode('utf-8'),
            "mode": "0644"
        }
        req = UploadRequest.from_payload(payload)

        assert req.remote_path == "/tmp/test.txt"
        assert req.data == data
        assert req.mode == "0644"

    def test_roundtrip_binary_data(self):
        # Test with various binary data
        test_data = bytes(range(256))  # All possible byte values
        original = UploadRequest(
            remote_path="/tmp/binary.dat",
            data=test_data,
            mode="0600"
        )
        payload = original.to_payload()
        restored = UploadRequest.from_payload(payload)

        assert restored.data == test_data


class TestUploadResponse:
    """Tests for UploadResponse."""

    def test_to_payload(self):
        resp = UploadResponse(
            success=True,
            message="File uploaded",
            bytes_written=1024
        )
        payload = resp.to_payload()

        assert payload["success"] is True
        assert payload["message"] == "File uploaded"
        assert payload["bytes_written"] == 1024

    def test_from_payload(self):
        payload = {
            "success": False,
            "message": "Permission denied",
            "bytes_written": 0
        }
        resp = UploadResponse.from_payload(payload)

        assert resp.success is False
        assert resp.message == "Permission denied"


class TestDownloadRequest:
    """Tests for DownloadRequest."""

    def test_to_payload(self):
        req = DownloadRequest(remote_path="/etc/hosts")
        payload = req.to_payload()

        assert payload["remote_path"] == "/etc/hosts"

    def test_from_payload(self):
        payload = {"remote_path": "/var/log/syslog"}
        req = DownloadRequest.from_payload(payload)

        assert req.remote_path == "/var/log/syslog"


class TestDownloadResponse:
    """Tests for DownloadResponse."""

    def test_to_payload_with_data(self):
        data = b"file contents"
        resp = DownloadResponse(
            success=True,
            data=data,
            size=len(data),
            message="OK"
        )
        payload = resp.to_payload()

        assert payload["success"] is True
        assert payload["size"] == len(data)
        assert base64.b64decode(payload["data"]) == data

    def test_to_payload_without_data(self):
        resp = DownloadResponse(
            success=False,
            data=None,
            size=0,
            message="File not found"
        )
        payload = resp.to_payload()

        assert payload["data"] is None
        assert payload["size"] == 0

    def test_from_payload_with_data(self):
        data = b"test content"
        payload = {
            "success": True,
            "data": base64.b64encode(data).decode('utf-8'),
            "size": len(data),
            "message": ""
        }
        resp = DownloadResponse.from_payload(payload)

        assert resp.success is True
        assert resp.data == data
        assert resp.size == len(data)

    def test_from_payload_without_data(self):
        payload = {
            "success": False,
            "data": None,
            "size": 0,
            "message": "Error"
        }
        resp = DownloadResponse.from_payload(payload)

        assert resp.data is None


class TestErrorResponse:
    """Tests for ErrorResponse."""

    def test_to_payload(self):
        resp = ErrorResponse(error="Something went wrong", code="INTERNAL_ERROR")
        payload = resp.to_payload()

        assert payload["error"] == "Something went wrong"
        assert payload["code"] == "INTERNAL_ERROR"

    def test_from_payload(self):
        payload = {"error": "Not found", "code": "NOT_FOUND"}
        resp = ErrorResponse.from_payload(payload)

        assert resp.error == "Not found"
        assert resp.code == "NOT_FOUND"

    def test_default_code(self):
        resp = ErrorResponse(error="Unknown error")
        assert resp.code == "UNKNOWN_ERROR"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
