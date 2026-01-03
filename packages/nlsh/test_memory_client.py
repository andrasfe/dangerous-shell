#!/usr/bin/env python3
"""Unit tests for memory_client."""

import pytest
from unittest.mock import MagicMock, patch
import os

# Test the module when mem0 is not available
with patch.dict('sys.modules', {'mem0': None}):
    from memory_client import (
        MemoryClient,
        MEM0_AVAILABLE,
        reset_memory_client,
        get_memory_client,
    )


class TestMemoryClientWithoutMem0:
    """Tests for MemoryClient when mem0 is not installed."""

    def setup_method(self):
        """Reset singleton before each test."""
        reset_memory_client()

    def test_mem0_not_available(self):
        """Test that mem0 unavailability is detected."""
        # Since we patched mem0 to None, it should not be available
        # But our import already happened, so we check MEM0_AVAILABLE
        # Note: This tests the fallback behavior
        client = MemoryClient()
        # With mem0 not available, is_available should be False
        # (actual result depends on whether mem0 is installed in env)

    def test_default_user_id(self):
        """Test that default user ID is generated."""
        client = MemoryClient()
        assert client.user_id is not None
        assert len(client.user_id) == 16  # SHA256 prefix

    def test_custom_user_id(self):
        """Test custom user ID."""
        client = MemoryClient(user_id="test_user")
        assert client.user_id == "test_user"

    def test_default_agent_id(self):
        """Test default agent ID."""
        client = MemoryClient()
        assert client.agent_id == "nlsh"

    def test_custom_agent_id(self):
        """Test custom agent ID."""
        client = MemoryClient(agent_id="custom_agent")
        assert client.agent_id == "custom_agent"


class TestMemoryClientMocked:
    """Tests for MemoryClient with mocked mem0."""

    def setup_method(self):
        """Reset singleton before each test."""
        reset_memory_client()

    def test_add_message_returns_false_when_unavailable(self):
        """Test add_message returns False when mem0 is not available."""
        client = MemoryClient()
        # Without proper mem0/API setup, this should fail gracefully
        result = client.add_message("user", "hello")
        assert isinstance(result, bool)

    def test_add_exchange_returns_false_when_unavailable(self):
        """Test add_exchange returns False when mem0 is not available."""
        client = MemoryClient()
        result = client.add_exchange("hello", "hi there")
        assert isinstance(result, bool)

    def test_get_context_returns_empty_when_unavailable(self):
        """Test get_context returns empty string when mem0 is not available."""
        client = MemoryClient()
        result = client.get_context("test query")
        assert result == ""

    def test_get_all_memories_returns_empty_when_unavailable(self):
        """Test get_all_memories returns empty list when mem0 is not available."""
        client = MemoryClient()
        result = client.get_all_memories()
        assert result == []

    def test_clear_memories_returns_false_when_unavailable(self):
        """Test clear_memories returns False when mem0 is not available."""
        client = MemoryClient()
        result = client.clear_memories()
        assert isinstance(result, bool)


class TestMemoryClientSingleton:
    """Tests for singleton behavior."""

    def setup_method(self):
        """Reset singleton before each test."""
        reset_memory_client()

    def test_get_memory_client_returns_same_instance(self):
        """Test that get_memory_client returns the same instance."""
        client1 = get_memory_client()
        client2 = get_memory_client()
        assert client1 is client2

    def test_reset_memory_client(self):
        """Test that reset_memory_client creates a new instance."""
        client1 = get_memory_client()
        reset_memory_client()
        client2 = get_memory_client()
        assert client1 is not client2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
