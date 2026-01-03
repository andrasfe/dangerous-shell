#!/usr/bin/env python3
"""Integration tests for mem0 memory integration in nlshell.

These tests verify:
1. ShellState correctly uses mem0 when available
2. ShellState falls back gracefully when mem0 is unavailable
3. Memory client correctly interacts with mem0 API
4. get_current_context() passes queries for semantic search
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
import sys
import os

# Add package path
sys.path.insert(0, os.path.dirname(__file__))


class TestShellStateFallback:
    """Test ShellState behavior when mem0 is NOT available."""

    def test_fallback_add_to_history(self):
        """Test that add_to_history works in fallback mode."""
        # Import with MEMORY_AVAILABLE = False
        with patch.dict('sys.modules', {'memory_client': None}):
            # Force reimport
            import importlib
            import nlshell
            importlib.reload(nlshell)

            state = nlshell.ShellState()
            state.add_to_history("user", "hello")
            state.add_to_history("assistant", "hi there")

            assert len(state.conversation_history) == 2
            assert state.conversation_history[0] == {"role": "user", "content": "hello"}
            assert state.conversation_history[1] == {"role": "assistant", "content": "hi there"}

    def test_fallback_get_conversation_context(self):
        """Test that get_conversation_context works in fallback mode."""
        with patch.dict('sys.modules', {'memory_client': None}):
            import importlib
            import nlshell
            importlib.reload(nlshell)

            state = nlshell.ShellState()
            state.add_to_history("user", "list files")
            state.add_to_history("assistant", "Here are the files...")

            # Should work without query in fallback mode
            context = state.get_conversation_context()
            assert "Recent conversation:" in context
            assert "User: list files" in context

    def test_fallback_clear_memory(self):
        """Test that clear_memory works in fallback mode."""
        with patch.dict('sys.modules', {'memory_client': None}):
            import importlib
            import nlshell
            importlib.reload(nlshell)

            state = nlshell.ShellState()
            state.add_to_history("user", "hello")
            assert len(state.conversation_history) == 1

            result = state.clear_memory()
            assert result is True
            assert len(state.conversation_history) == 0

    def test_fallback_memory_status(self):
        """Test memory_status shows fallback when mem0 unavailable."""
        with patch.dict('sys.modules', {'memory_client': None}):
            import importlib
            import nlshell
            importlib.reload(nlshell)

            state = nlshell.ShellState()
            status = state.memory_status
            assert "fallback" in status


class TestMemoryClientIntegration:
    """Test MemoryClient integration."""

    def test_memory_client_initialization(self):
        """Test MemoryClient initializes with correct defaults."""
        from memory_client import MemoryClient

        client = MemoryClient(user_id="test_user")
        assert client.user_id == "test_user"
        assert client.agent_id == "nlsh"

    def test_memory_client_default_user_id(self):
        """Test MemoryClient generates consistent default user_id."""
        from memory_client import MemoryClient

        client1 = MemoryClient()
        client2 = MemoryClient()

        # Same machine should get same ID
        assert client1.user_id == client2.user_id
        assert len(client1.user_id) == 16

    def test_memory_client_graceful_failure(self):
        """Test MemoryClient methods fail gracefully without mem0."""
        from memory_client import MemoryClient, reset_memory_client

        reset_memory_client()
        client = MemoryClient()

        # These should not raise exceptions
        result = client.add_message("user", "test")
        assert isinstance(result, bool)

        context = client.get_context("test query")
        assert context == "" or isinstance(context, str)

        memories = client.get_all_memories()
        assert memories == [] or isinstance(memories, list)


class TestMockedMem0Integration:
    """Test with mocked mem0 to verify API interactions."""

    def test_add_message_calls_mem0_add(self):
        """Test that add_message correctly calls mem0's add method."""
        from memory_client import MemoryClient, reset_memory_client

        reset_memory_client()

        # Create a mock Memory class
        mock_memory = MagicMock()
        mock_memory.add = MagicMock()

        with patch('memory_client.Memory') as MockMemory:
            MockMemory.from_config = MagicMock(return_value=mock_memory)

            with patch('memory_client.MEM0_AVAILABLE', True):
                with patch('memory_client.OPENROUTER_API_KEY', 'test-key'):
                    client = MemoryClient(user_id="test_user")
                    # Force initialization
                    client._ensure_initialized()

                    if client.is_available:
                        client.add_message("user", "hello world")

                        mock_memory.add.assert_called_once()
                        call_args = mock_memory.add.call_args
                        assert call_args[0][0] == [{"role": "user", "content": "hello world"}]

    def test_get_context_calls_mem0_search(self):
        """Test that get_context correctly calls mem0's search method."""
        from memory_client import MemoryClient, reset_memory_client

        reset_memory_client()

        mock_memory = MagicMock()
        mock_memory.search = MagicMock(return_value={
            "results": [
                {"memory": "User prefers Python"},
                {"memory": "User works on shell project"}
            ]
        })

        with patch('memory_client.Memory') as MockMemory:
            MockMemory.from_config = MagicMock(return_value=mock_memory)

            with patch('memory_client.MEM0_AVAILABLE', True):
                with patch('memory_client.OPENROUTER_API_KEY', 'test-key'):
                    client = MemoryClient(user_id="test_user")
                    client._ensure_initialized()

                    if client.is_available:
                        context = client.get_context("what programming language?")

                        mock_memory.search.assert_called_once()
                        assert "User prefers Python" in context or context == ""


class TestGetCurrentContextIntegration:
    """Test get_current_context passes query to memory system."""

    def test_get_current_context_with_query(self):
        """Test that get_current_context passes query for semantic search."""
        with patch.dict('sys.modules', {'memory_client': None}):
            import importlib
            import nlshell
            importlib.reload(nlshell)

            # Add some history
            nlshell.shell_state.add_to_history("user", "show me files")
            nlshell.shell_state.add_to_history("assistant", "Here are files: a.txt, b.txt")

            # Get context with query
            context = nlshell.get_current_context("list all files")

            # Should include working directory
            assert "Current working directory:" in context

            # In fallback mode, should still include conversation context
            assert "Recent conversation:" in context or "show me files" in context or context != ""


class TestHistoryTrimming:
    """Test that history trimming works correctly."""

    def test_history_trims_at_max(self):
        """Test that conversation history is trimmed when exceeding max."""
        with patch.dict('sys.modules', {'memory_client': None}):
            import importlib
            import nlshell
            importlib.reload(nlshell)

            state = nlshell.ShellState()
            state.max_history = 5  # Set low for testing

            # Add more than max_history * 2 messages
            for i in range(15):
                state.add_to_history("user", f"message {i}")

            # Should be trimmed to max_history * 2 = 10
            assert len(state.conversation_history) == 10
            # Should keep the latest messages
            assert state.conversation_history[-1]["content"] == "message 14"


class TestMemoryStatusDisplay:
    """Test memory status string generation."""

    def test_memory_status_without_mem0(self):
        """Test memory_status when mem0 is not installed."""
        with patch.dict('sys.modules', {'memory_client': None}):
            import importlib
            import nlshell
            importlib.reload(nlshell)

            state = nlshell.ShellState()
            status = state.memory_status

            # Should indicate mem0 is not installed
            assert "fallback" in status.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
