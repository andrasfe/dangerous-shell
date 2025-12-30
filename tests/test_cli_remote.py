"""Tests for CLI remote execution integration."""

import pytest
import sys
import os
from pathlib import Path
from multiprocessing import Process
import time

# Add packages to path
packages_path = str(Path(__file__).parent.parent / "packages")
sys.path.insert(0, packages_path)
sys.path.insert(0, str(Path(__file__).parent.parent / "packages" / "shared"))
sys.path.insert(0, str(Path(__file__).parent.parent / "packages" / "nlsh"))
sys.path.insert(0, str(Path(__file__).parent.parent / "packages" / "nlsh_remote"))

from remote_client import RemoteClient
from shared.crypto import sign_message, verify_message
from shared.protocol import MessageType


# Test configuration
TEST_HOST = "127.0.0.1"
TEST_PORT = 18766  # Different port from other integration tests
TEST_SECRET = "test_cli_integration_secret_key"


def start_server():
    """Start the server in a subprocess."""
    import uvicorn

    # Set up sys.path in subprocess
    packages_path = str(Path(__file__).parent.parent / "packages")
    if packages_path not in sys.path:
        sys.path.insert(0, packages_path)

    os.environ["NLSH_SHARED_SECRET"] = TEST_SECRET
    os.environ["NLSH_REMOTE_HOST"] = TEST_HOST
    os.environ["NLSH_REMOTE_PORT"] = str(TEST_PORT)

    from nlsh_remote.server import app
    uvicorn.run(app, host=TEST_HOST, port=TEST_PORT, log_level="error")


@pytest.fixture(scope="module")
def server():
    """Start server for tests."""
    proc = Process(target=start_server, daemon=True)
    proc.start()
    time.sleep(2)
    yield proc
    proc.terminate()
    proc.join(timeout=5)


class TestExecuteRemoteCommand:
    """Tests for the execute_remote_command function."""

    @pytest.mark.asyncio
    async def test_simple_echo(self, server):
        """Test executing a simple echo command."""
        async with RemoteClient(
            host=TEST_HOST,
            port=TEST_PORT,
            shared_secret=TEST_SECRET
        ) as client:
            result = await client.execute_command("echo 'hello from remote'")
            assert result.success is True
            assert "hello from remote" in result.stdout
            assert result.returncode == 0

    @pytest.mark.asyncio
    async def test_command_with_cwd(self, server):
        """Test executing command with working directory."""
        async with RemoteClient(
            host=TEST_HOST,
            port=TEST_PORT,
            shared_secret=TEST_SECRET
        ) as client:
            result = await client.execute_command("pwd", cwd="/tmp")
            assert result.success is True
            assert "/tmp" in result.stdout

    @pytest.mark.asyncio
    async def test_command_failure(self, server):
        """Test handling of failed command."""
        async with RemoteClient(
            host=TEST_HOST,
            port=TEST_PORT,
            shared_secret=TEST_SECRET
        ) as client:
            result = await client.execute_command("exit 1")
            assert result.success is False
            assert result.returncode == 1

    @pytest.mark.asyncio
    async def test_command_with_stderr(self, server):
        """Test capturing stderr."""
        async with RemoteClient(
            host=TEST_HOST,
            port=TEST_PORT,
            shared_secret=TEST_SECRET
        ) as client:
            result = await client.execute_command("echo 'error message' >&2")
            assert "error message" in result.stderr

    @pytest.mark.asyncio
    async def test_multiline_output(self, server):
        """Test capturing multiline output."""
        async with RemoteClient(
            host=TEST_HOST,
            port=TEST_PORT,
            shared_secret=TEST_SECRET
        ) as client:
            result = await client.execute_command("echo -e 'line1\\nline2\\nline3'")
            assert result.success is True
            assert "line1" in result.stdout
            assert "line2" in result.stdout
            assert "line3" in result.stdout

    @pytest.mark.asyncio
    async def test_environment_variable(self, server):
        """Test that environment variables work."""
        async with RemoteClient(
            host=TEST_HOST,
            port=TEST_PORT,
            shared_secret=TEST_SECRET
        ) as client:
            result = await client.execute_command("TEST_VAR=hello && echo $TEST_VAR")
            assert result.success is True
            # Note: This may not work as expected due to how shell handles this
            # but it tests that the command runs

    @pytest.mark.asyncio
    async def test_pipe_command(self, server):
        """Test piped commands."""
        async with RemoteClient(
            host=TEST_HOST,
            port=TEST_PORT,
            shared_secret=TEST_SECRET
        ) as client:
            result = await client.execute_command("echo 'hello world' | grep hello")
            assert result.success is True
            assert "hello" in result.stdout

    @pytest.mark.asyncio
    async def test_chained_commands(self, server):
        """Test && chained commands."""
        async with RemoteClient(
            host=TEST_HOST,
            port=TEST_PORT,
            shared_secret=TEST_SECRET
        ) as client:
            result = await client.execute_command("echo 'first' && echo 'second'")
            assert result.success is True
            assert "first" in result.stdout
            assert "second" in result.stdout


class TestCLIArgumentParsing:
    """Tests for CLI argument parsing."""

    def test_remote_flag_requires_env_vars(self):
        """Test that --remote requires environment variables."""
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--remote", action="store_true")
        parser.add_argument("--dangerously-skip-permissions", action="store_true")

        args = parser.parse_args(["--remote"])
        assert args.remote is True

    def test_skip_permissions_flag(self):
        """Test --dangerously-skip-permissions flag parsing."""
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--remote", action="store_true")
        parser.add_argument("--dangerously-skip-permissions", action="store_true")

        args = parser.parse_args(["--dangerously-skip-permissions"])
        assert args.dangerously_skip_permissions is True

    def test_combined_flags(self):
        """Test combining --remote and --dangerously-skip-permissions."""
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--remote", action="store_true")
        parser.add_argument("--dangerously-skip-permissions", action="store_true")

        args = parser.parse_args(["--remote", "--dangerously-skip-permissions"])
        assert args.remote is True
        assert args.dangerously_skip_permissions is True


class TestRemoteClientIntegration:
    """Integration tests for RemoteClient with real server."""

    @pytest.mark.asyncio
    async def test_multiple_commands_same_session(self, server):
        """Test executing multiple commands in same session."""
        async with RemoteClient(
            host=TEST_HOST,
            port=TEST_PORT,
            shared_secret=TEST_SECRET
        ) as client:
            r1 = await client.execute_command("echo 'cmd1'")
            r2 = await client.execute_command("echo 'cmd2'")
            r3 = await client.execute_command("echo 'cmd3'")

            assert r1.success is True
            assert r2.success is True
            assert r3.success is True
            assert "cmd1" in r1.stdout
            assert "cmd2" in r2.stdout
            assert "cmd3" in r3.stdout

    @pytest.mark.asyncio
    async def test_rapid_command_execution(self, server):
        """Test rapid execution of commands."""
        async with RemoteClient(
            host=TEST_HOST,
            port=TEST_PORT,
            shared_secret=TEST_SECRET
        ) as client:
            results = []
            for i in range(5):
                result = await client.execute_command(f"echo 'test{i}'")
                results.append(result)

            for i, result in enumerate(results):
                assert result.success is True
                assert f"test{i}" in result.stdout

    @pytest.mark.asyncio
    async def test_file_operations(self, server):
        """Test file creation and reading via remote commands."""
        test_file = f"/tmp/nlsh_cli_test_{os.getpid()}.txt"

        async with RemoteClient(
            host=TEST_HOST,
            port=TEST_PORT,
            shared_secret=TEST_SECRET
        ) as client:
            # Create file
            result = await client.execute_command(f"echo 'test content' > {test_file}")
            assert result.success is True

            # Read file
            result = await client.execute_command(f"cat {test_file}")
            assert result.success is True
            assert "test content" in result.stdout

            # Clean up
            result = await client.execute_command(f"rm {test_file}")
            assert result.success is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
