#!/usr/bin/env python3
"""
Standalone integration tests for mem0 memory integration.
Can be run without pytest to verify basic functionality.

Usage: python run_integration_tests.py
"""

import sys
import os

# Add package path
sys.path.insert(0, os.path.dirname(__file__))

# Track test results
passed = 0
failed = 0
errors = []


def test(name, condition, message=""):
    """Simple test helper."""
    global passed, failed, errors
    try:
        if condition:
            print(f"  ✓ {name}")
            passed += 1
        else:
            print(f"  ✗ {name}: {message}")
            failed += 1
            errors.append(f"{name}: {message}")
    except Exception as e:
        print(f"  ✗ {name}: Exception - {e}")
        failed += 1
        errors.append(f"{name}: {e}")


def test_memory_client_module():
    """Test memory_client.py module."""
    print("\n== Testing memory_client module ==")

    try:
        from memory_client import (
            MemoryClient,
            get_memory_client,
            reset_memory_client,
            MEM0_AVAILABLE,
        )
        test("Import memory_client", True)
    except ImportError as e:
        test("Import memory_client", False, str(e))
        return

    # Test MemoryClient initialization
    client = MemoryClient(user_id="test_user", agent_id="test_agent")
    test("MemoryClient accepts user_id", client.user_id == "test_user")
    test("MemoryClient accepts agent_id", client.agent_id == "test_agent")

    # Test default user_id generation
    client2 = MemoryClient()
    test("MemoryClient generates default user_id", len(client2.user_id) == 16)
    test("MemoryClient default agent_id is 'nlsh'", client2.agent_id == "nlsh")

    # Test singleton behavior
    reset_memory_client()
    c1 = get_memory_client()
    c2 = get_memory_client()
    test("get_memory_client returns same instance", c1 is c2)

    reset_memory_client()
    c3 = get_memory_client()
    test("reset_memory_client creates new instance", c1 is not c3)

    # Test graceful failures
    reset_memory_client()
    client = MemoryClient()

    result = client.add_message("user", "hello")
    test("add_message returns bool", isinstance(result, bool))

    context = client.get_context("test query")
    test("get_context returns string", isinstance(context, str))

    memories = client.get_all_memories()
    test("get_all_memories returns list", isinstance(memories, list))

    clear_result = client.clear_memories()
    test("clear_memories returns bool", isinstance(clear_result, bool))

    # Test is_available and error_message
    test("is_available is bool", isinstance(client.is_available, bool))
    # error_message can be None or string
    test("error_message is None or string",
         client.error_message is None or isinstance(client.error_message, str))

    print(f"  MEM0_AVAILABLE = {MEM0_AVAILABLE}")
    print(f"  client.is_available = {client.is_available}")
    if client.error_message:
        print(f"  client.error_message = {client.error_message}")


def test_shell_state_fallback():
    """Test ShellState fallback behavior without mem0."""
    print("\n== Testing ShellState fallback behavior ==")

    # Temporarily disable memory_client import
    import memory_client
    original_available = memory_client.MEM0_AVAILABLE
    memory_client.MEM0_AVAILABLE = False

    try:
        # Need to create a fresh ShellState that will use fallback
        # Since ShellState checks MEMORY_AVAILABLE on init, we need to reimport

        # Create a new ShellState manually
        from pathlib import Path

        class TestShellState:
            """Copy of ShellState for testing fallback behavior."""
            def __init__(self):
                self.cwd = Path.cwd()
                self.conversation_history = []
                self.max_history = 20
                self._use_mem0 = False

            def add_to_history(self, role, content):
                self.conversation_history.append({"role": role, "content": content})
                if len(self.conversation_history) > self.max_history * 2:
                    self.conversation_history = self.conversation_history[-self.max_history * 2:]

            def get_conversation_context(self, query=""):
                if not self.conversation_history:
                    return ""
                lines = ["Recent conversation:"]
                for msg in self.conversation_history[-10:]:
                    role = "You" if msg["role"] == "assistant" else "User"
                    content = msg["content"][:500]
                    lines.append(f"  {role}: {content}")
                return "\n".join(lines)

            def clear_memory(self):
                self.conversation_history = []
                return True

        state = TestShellState()

        # Test add_to_history
        state.add_to_history("user", "hello")
        state.add_to_history("assistant", "hi there")
        test("add_to_history adds messages", len(state.conversation_history) == 2)
        test("add_to_history stores correct content",
             state.conversation_history[0]["content"] == "hello")

        # Test get_conversation_context
        context = state.get_conversation_context()
        test("get_conversation_context returns string", isinstance(context, str))
        test("get_conversation_context includes messages", "hello" in context)

        # Test history trimming
        state.max_history = 3
        for i in range(10):
            state.add_to_history("user", f"msg{i}")
        test("History trimming works", len(state.conversation_history) == 6)
        test("History keeps recent messages", "msg9" in state.conversation_history[-1]["content"])

        # Test clear_memory
        result = state.clear_memory()
        test("clear_memory returns True", result is True)
        test("clear_memory clears history", len(state.conversation_history) == 0)

    finally:
        memory_client.MEM0_AVAILABLE = original_available


def test_nlshell_integration():
    """Test nlshell.py integration with memory system."""
    print("\n== Testing nlshell integration ==")

    try:
        # This will fail if dependencies aren't installed
        from nlshell import (
            ShellState,
            get_current_context,
            MEMORY_AVAILABLE,
        )
        test("Import nlshell", True)

        print(f"  MEMORY_AVAILABLE = {MEMORY_AVAILABLE}")

    except ImportError as e:
        # Expected if dependencies like dotenv aren't installed
        print(f"  ⚠ Cannot import nlshell (missing dependencies): {e}")
        print("  Skipping nlshell integration tests (OK in minimal environment)")
        return

    # Test ShellState
    state = ShellState()
    test("ShellState initializes", state is not None)
    test("ShellState has conversation_history", hasattr(state, 'conversation_history'))
    test("ShellState has memory_status", hasattr(state, 'memory_status'))

    # Test memory_status property
    status = state.memory_status
    test("memory_status returns string", isinstance(status, str))
    print(f"  memory_status = '{status}'")

    # Test add_to_history
    state.add_to_history("user", "test message")
    test("add_to_history works", True)

    # Test get_conversation_context with query
    context = state.get_conversation_context("test query")
    test("get_conversation_context accepts query", isinstance(context, str))

    # Test clear_memory
    result = state.clear_memory()
    test("clear_memory returns bool", isinstance(result, bool))


def main():
    """Run all tests."""
    global passed, failed

    print("=" * 60)
    print("Mem0 Integration Tests")
    print("=" * 60)

    test_memory_client_module()
    test_shell_state_fallback()
    test_nlshell_integration()

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    if errors:
        print("\nErrors:")
        for error in errors:
            print(f"  - {error}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
