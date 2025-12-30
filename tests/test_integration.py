"""Integration tests for nlsh-remote.

These tests start a real server and test the full client-server communication.
"""

import pytest
import asyncio
import tempfile
import os
import sys
import time
from pathlib import Path
from multiprocessing import Process

# Add packages to path
packages_path = str(Path(__file__).parent.parent / "packages")
sys.path.insert(0, packages_path)
sys.path.insert(0, str(Path(__file__).parent.parent / "packages" / "shared"))
sys.path.insert(0, str(Path(__file__).parent.parent / "packages" / "nlsh"))
sys.path.insert(0, str(Path(__file__).parent.parent / "packages" / "nlsh_remote"))

from crypto import sign_message, verify_message
from protocol import MessageType


# Test configuration
TEST_HOST = "127.0.0.1"
TEST_PORT = 18765  # Use non-standard port for tests
TEST_SECRET = "test_integration_secret_key_12345"


def start_server():
    """Start the server in a subprocess."""
    import uvicorn

    # Set up sys.path in subprocess (may not inherit from parent)
    packages_path = str(Path(__file__).parent.parent / "packages")
    if packages_path not in sys.path:
        sys.path.insert(0, packages_path)

    os.environ["NLSH_SHARED_SECRET"] = TEST_SECRET
    os.environ["NLSH_REMOTE_HOST"] = TEST_HOST
    os.environ["NLSH_REMOTE_PORT"] = str(TEST_PORT)

    # Import after setting env vars and sys.path
    from nlsh_remote.server import app
    uvicorn.run(app, host=TEST_HOST, port=TEST_PORT, log_level="error")


@pytest.fixture(scope="module")
def server():
    """Start server for tests."""
    # Start server in subprocess
    proc = Process(target=start_server, daemon=True)
    proc.start()

    # Wait for server to be ready
    time.sleep(2)

    yield proc

    # Cleanup
    proc.terminate()
    proc.join(timeout=5)


@pytest.fixture
def client():
    """Create a test client."""
    from nlsh.remote_client import RemoteClient
    return RemoteClient(
        host=TEST_HOST,
        port=TEST_PORT,
        shared_secret=TEST_SECRET,
        timeout=10.0
    )


class TestConnection:
    """Tests for basic connection handling."""

    @pytest.mark.asyncio
    async def test_connect_and_disconnect(self, server, client):
        """Test basic connection lifecycle."""
        await client.connect()
        assert client._websocket is not None
        await client.disconnect()
        assert client._websocket is None

    @pytest.mark.asyncio
    async def test_context_manager(self, server, client):
        """Test async context manager."""
        async with client:
            assert client._websocket is not None
        assert client._websocket is None

    @pytest.mark.asyncio
    async def test_ping_pong(self, server, client):
        """Test ping/pong keepalive."""
        async with client:
            result = await client.ping()
            assert result is True


class TestCommandExecution:
    """Tests for remote command execution."""

    @pytest.mark.asyncio
    async def test_simple_command(self, server, client):
        """Test executing a simple command."""
        async with client:
            result = await client.execute_command("echo hello")
            assert result.success is True
            assert result.returncode == 0
            assert "hello" in result.stdout

    @pytest.mark.asyncio
    async def test_command_with_args(self, server, client):
        """Test command with arguments."""
        async with client:
            result = await client.execute_command("echo -n 'test string'")
            assert result.success is True
            assert "test string" in result.stdout

    @pytest.mark.asyncio
    async def test_command_with_cwd(self, server, client):
        """Test command with working directory."""
        async with client:
            result = await client.execute_command("pwd", cwd="/tmp")
            assert result.success is True
            assert "/tmp" in result.stdout

    @pytest.mark.asyncio
    async def test_failing_command(self, server, client):
        """Test command that fails."""
        async with client:
            result = await client.execute_command("exit 42")
            assert result.success is False
            assert result.returncode == 42

    @pytest.mark.asyncio
    async def test_command_with_stderr(self, server, client):
        """Test command that writes to stderr."""
        async with client:
            result = await client.execute_command("echo error >&2")
            assert "error" in result.stderr

    @pytest.mark.asyncio
    async def test_command_output_capture(self, server, client):
        """Test capturing multi-line output."""
        async with client:
            result = await client.execute_command("echo -e 'line1\\nline2\\nline3'")
            assert result.success is True
            assert "line1" in result.stdout
            assert "line2" in result.stdout
            assert "line3" in result.stdout


class TestFileTransfer:
    """Tests for file upload/download."""

    @pytest.mark.asyncio
    async def test_upload_file(self, server, client):
        """Test uploading a file."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"test upload content")
            local_path = f.name

        remote_path = f"/tmp/nlsh_test_upload_{os.getpid()}.txt"

        try:
            async with client:
                result = await client.upload_file(local_path, remote_path)
                assert result.success is True
                assert result.bytes_written == 19

                # Verify file exists on remote
                check = await client.execute_command(f"cat {remote_path}")
                assert check.success is True
                assert "test upload content" in check.stdout
        finally:
            os.unlink(local_path)
            # Cleanup remote file
            async with client:
                await client.execute_command(f"rm -f {remote_path}")

    @pytest.mark.asyncio
    async def test_download_file(self, server, client):
        """Test downloading a file."""
        remote_path = f"/tmp/nlsh_test_download_{os.getpid()}.txt"
        content = b"test download content"

        try:
            async with client:
                # Create file on remote
                await client.execute_command(
                    f"echo -n 'test download content' > {remote_path}"
                )

                # Download it
                data, result = await client.download_file(remote_path)
                assert result.success is True
                assert data == content
                assert result.size == len(content)
        finally:
            # Cleanup
            async with client:
                await client.execute_command(f"rm -f {remote_path}")

    @pytest.mark.asyncio
    async def test_download_to_local_file(self, server, client):
        """Test downloading directly to a local file."""
        remote_path = f"/tmp/nlsh_test_dl_{os.getpid()}.txt"

        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = Path(tmpdir) / "downloaded.txt"

            try:
                async with client:
                    # Create file on remote
                    await client.execute_command(
                        f"echo 'hello world' > {remote_path}"
                    )

                    # Download to local file
                    data, result = await client.download_file(remote_path, local_path)
                    assert result.success is True
                    assert local_path.exists()
                    assert "hello world" in local_path.read_text()
            finally:
                async with client:
                    await client.execute_command(f"rm -f {remote_path}")

    @pytest.mark.asyncio
    async def test_upload_binary_data(self, server, client):
        """Test uploading binary data."""
        # Create binary data with all byte values
        binary_data = bytes(range(256))
        remote_path = f"/tmp/nlsh_test_binary_{os.getpid()}.bin"

        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(binary_data)
            local_path = f.name

        try:
            async with client:
                result = await client.upload_file(local_path, remote_path)
                assert result.success is True
                assert result.bytes_written == 256

                # Download and verify
                data, dl_result = await client.download_file(remote_path)
                assert dl_result.success is True
                assert data == binary_data
        finally:
            os.unlink(local_path)
            async with client:
                await client.execute_command(f"rm -f {remote_path}")

    @pytest.mark.asyncio
    async def test_download_nonexistent_file(self, server, client):
        """Test downloading a file that doesn't exist."""
        async with client:
            with pytest.raises(RuntimeError) as exc:
                await client.download_file("/nonexistent/file/path.txt")
            assert "not found" in str(exc.value).lower() or "FILE_NOT_FOUND" in str(exc.value)


class TestAuthentication:
    """Tests for HMAC authentication."""

    @pytest.mark.asyncio
    async def test_wrong_secret_rejected(self, server):
        """Test that wrong secret is rejected."""
        from nlsh.remote_client import RemoteClient

        bad_client = RemoteClient(
            host=TEST_HOST,
            port=TEST_PORT,
            shared_secret="wrong_secret",
            timeout=5.0
        )

        async with bad_client:
            with pytest.raises((RuntimeError, ValueError)) as exc:
                await bad_client.execute_command("echo test")
            assert "auth" in str(exc.value).lower() or "signature" in str(exc.value).lower()


class TestErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_invalid_cwd(self, server, client):
        """Test command with invalid working directory."""
        async with client:
            with pytest.raises(RuntimeError) as exc:
                await client.execute_command("ls", cwd="/nonexistent/directory")
            assert "not found" in str(exc.value).lower() or "DIR_NOT_FOUND" in str(exc.value)

    @pytest.mark.asyncio
    async def test_upload_to_readonly_location(self, server, client):
        """Test uploading to a read-only location."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"test")
            local_path = f.name

        try:
            async with client:
                # Try to write to root directory (should fail without sudo)
                with pytest.raises(RuntimeError) as exc:
                    await client.upload_file(local_path, "/test_readonly.txt")
                error_msg = str(exc.value).lower()
                # Different systems return different errors for write attempts to /
                assert ("permission" in error_msg or
                        "read-only" in error_msg or
                        "PERMISSION_DENIED" in str(exc.value))
        finally:
            os.unlink(local_path)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
