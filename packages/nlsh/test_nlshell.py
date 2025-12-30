#!/usr/bin/env python3
"""Unit tests for nlshell."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
import tempfile
import os

# Import functions to test
from nlshell import (
    ShellState,
    requires_interactive_mode,
    read_file,
    list_directory,
    load_recent_history,
    format_history_context,
    shell_state,
)


class TestShellState:
    """Tests for ShellState class."""

    def test_init(self):
        state = ShellState()
        assert state.cwd == Path.cwd()
        assert state.last_command is None
        assert state.last_output is None
        assert state.conversation_history == []

    def test_add_to_history(self):
        state = ShellState()
        state.add_to_history("user", "hello")
        state.add_to_history("assistant", "hi there")

        assert len(state.conversation_history) == 2
        assert state.conversation_history[0] == {"role": "user", "content": "hello"}
        assert state.conversation_history[1] == {"role": "assistant", "content": "hi there"}

    def test_history_trimming(self):
        state = ShellState()
        state.max_history = 5

        # Add more than max_history * 2 messages
        for i in range(15):
            state.add_to_history("user", f"message {i}")

        # Should be trimmed to last max_history * 2
        assert len(state.conversation_history) == 10

    def test_get_conversation_context_empty(self):
        state = ShellState()
        assert state.get_conversation_context() == ""

    def test_get_conversation_context_with_messages(self):
        state = ShellState()
        state.add_to_history("user", "list files")
        state.add_to_history("assistant", "Here are the files...")

        context = state.get_conversation_context()
        assert "Recent conversation:" in context
        assert "User: list files" in context
        assert "You: Here are the files..." in context


class TestInteractiveMode:
    """Tests for interactive mode detection."""

    def test_sudo_commands(self):
        assert requires_interactive_mode("sudo apt update") is True
        assert requires_interactive_mode("sudo pip install package") is True
        assert requires_interactive_mode("SUDO apt update") is True  # case insensitive

    def test_ssh_commands(self):
        assert requires_interactive_mode("ssh user@host") is True
        assert requires_interactive_mode("scp file.txt user@host:") is True
        assert requires_interactive_mode("sftp user@host") is True

    def test_other_interactive_commands(self):
        assert requires_interactive_mode("su -") is True
        assert requires_interactive_mode("passwd") is True
        assert requires_interactive_mode("docker login") is True
        assert requires_interactive_mode("npm login") is True
        assert requires_interactive_mode("gh auth login") is True

    def test_sudo_in_pipeline(self):
        assert requires_interactive_mode("echo hello | sudo tee /etc/file") is True
        assert requires_interactive_mode("cat file && sudo rm it") is True

    def test_non_interactive_commands(self):
        assert requires_interactive_mode("ls -la") is False
        assert requires_interactive_mode("git status") is False
        assert requires_interactive_mode("pip install package") is False
        assert requires_interactive_mode("echo hello") is False


class TestReadFile:
    """Tests for read_file function."""

    def test_read_existing_file(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Hello, World!\nLine 2\n")
            f.flush()
            temp_path = f.name

        try:
            content = read_file(temp_path)
            assert "Hello, World!" in content
            assert "Line 2" in content
        finally:
            os.unlink(temp_path)

    def test_read_nonexistent_file(self):
        result = read_file("/nonexistent/path/file.txt")
        assert "Error: File not found" in result

    def test_read_directory_as_file(self):
        result = read_file("/tmp")
        assert "Error: Not a file" in result

    def test_read_with_max_lines(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            for i in range(100):
                f.write(f"Line {i}\n")
            f.flush()
            temp_path = f.name

        try:
            content = read_file(temp_path, max_lines=10)
            assert "truncated" in content
            assert "Line 0" in content
            assert "Line 9" in content
        finally:
            os.unlink(temp_path)


class TestListDirectory:
    """Tests for list_directory function."""

    def test_list_existing_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create some files
            Path(tmpdir, "file1.txt").touch()
            Path(tmpdir, "file2.py").touch()
            Path(tmpdir, "subdir").mkdir()

            result = list_directory(tmpdir)
            assert "file1.txt" in result
            assert "file2.py" in result
            assert "[DIR]" in result
            assert "subdir" in result

    def test_list_nonexistent_directory(self):
        result = list_directory("/nonexistent/path")
        assert "Error: Directory not found" in result

    def test_list_file_as_directory(self):
        with tempfile.NamedTemporaryFile() as f:
            result = list_directory(f.name)
            assert "Error: Not a directory" in result

    def test_hidden_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, ".hidden").touch()
            Path(tmpdir, "visible").touch()

            # Without hidden
            result = list_directory(tmpdir, show_hidden=False)
            assert ".hidden" not in result
            assert "visible" in result

            # With hidden
            result = list_directory(tmpdir, show_hidden=True)
            assert ".hidden" in result
            assert "visible" in result


class TestHistoryFunctions:
    """Tests for history loading and formatting."""

    def test_format_history_context_empty(self):
        result = format_history_context([])
        assert result == "No previous commands in history."

    def test_format_history_context_with_entries(self):
        history = [
            {"input": "list files", "command": "ls -la", "success": True},
            {"input": "show disk", "command": "df -h", "success": False},
        ]
        result = format_history_context(history)
        assert "list files" in result
        assert "ls -la" in result
        assert "[OK]" in result
        assert "[FAILED]" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
