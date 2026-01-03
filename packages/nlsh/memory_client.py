"""Mem0 memory client for persistent agentic memory.

This module provides a wrapper around mem0 for long-term memory storage
and retrieval, replacing the simple 20-entry conversation history.
"""

import os
import hashlib
from typing import Optional
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Configuration
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
MEM0_MODEL = os.getenv("MEM0_MODEL", "anthropic/claude-3.5-sonnet")

# Try to import mem0
try:
    from mem0 import Memory
    MEM0_AVAILABLE = True
except ImportError:
    MEM0_AVAILABLE = False
    Memory = None


class MemoryError(Exception):
    """Error with memory operations."""
    pass


class MemoryClient:
    """Client for persistent agentic memory using mem0.

    Provides semantic memory storage and retrieval, replacing the simple
    in-memory conversation history with a more intelligent approach.
    """

    def __init__(
        self,
        user_id: str | None = None,
        agent_id: str = "nlsh",
    ):
        """Initialize memory client.

        Args:
            user_id: Unique user identifier. Defaults to machine-based ID.
            agent_id: Agent identifier for scoping memories.
        """
        self.agent_id = agent_id
        self.user_id = user_id or self._get_default_user_id()
        self._memory: Optional["Memory"] = None
        self._initialized = False
        self._init_error: Optional[str] = None

    def _get_default_user_id(self) -> str:
        """Generate a default user ID based on machine identity."""
        # Use a combination of home directory and machine name for uniqueness
        home = str(Path.home())
        hostname = os.uname().nodename if hasattr(os, 'uname') else "unknown"
        identity = f"{home}:{hostname}"
        return hashlib.sha256(identity.encode()).hexdigest()[:16]

    def _ensure_initialized(self) -> bool:
        """Ensure mem0 is initialized. Returns True if available."""
        if self._initialized:
            return self._memory is not None

        self._initialized = True

        if not MEM0_AVAILABLE:
            self._init_error = "mem0 not installed (pip install mem0ai)"
            return False

        if not OPENROUTER_API_KEY:
            self._init_error = "OPENROUTER_API_KEY not set"
            return False

        try:
            # Configure mem0 to use OpenRouter
            config = {
                "llm": {
                    "provider": "openai",
                    "config": {
                        "model": MEM0_MODEL,
                        "api_key": OPENROUTER_API_KEY,
                        "openai_base_url": "https://openrouter.ai/api/v1",
                    }
                },
                "embedder": {
                    "provider": "openai",
                    "config": {
                        "model": "openai/text-embedding-3-small",
                        "api_key": OPENROUTER_API_KEY,
                        "openai_base_url": "https://openrouter.ai/api/v1",
                    }
                },
                "version": "v1.1",
            }
            self._memory = Memory.from_config(config)
            return True
        except Exception as e:
            self._init_error = str(e)
            return False

    @property
    def is_available(self) -> bool:
        """Check if memory system is available."""
        return self._ensure_initialized()

    @property
    def error_message(self) -> Optional[str]:
        """Get initialization error message if any."""
        self._ensure_initialized()
        return self._init_error

    def add_message(self, role: str, content: str) -> bool:
        """Add a message to memory.

        Args:
            role: Message role ('user' or 'assistant').
            content: Message content.

        Returns:
            True if added successfully, False otherwise.
        """
        if not self._ensure_initialized():
            return False

        try:
            messages = [{"role": role, "content": content}]
            self._memory.add(
                messages,
                user_id=self.user_id,
                agent_id=self.agent_id,
            )
            return True
        except Exception:
            return False

    def add_exchange(self, user_message: str, assistant_message: str) -> bool:
        """Add a user-assistant exchange to memory.

        Args:
            user_message: User's message.
            assistant_message: Assistant's response.

        Returns:
            True if added successfully, False otherwise.
        """
        if not self._ensure_initialized():
            return False

        try:
            messages = [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": assistant_message},
            ]
            self._memory.add(
                messages,
                user_id=self.user_id,
                agent_id=self.agent_id,
            )
            return True
        except Exception:
            return False

    def get_context(self, query: str, limit: int = 10) -> str:
        """Get relevant context for a query.

        Args:
            query: The current user query to find relevant context for.
            limit: Maximum number of memories to retrieve.

        Returns:
            Formatted string of relevant memories, or empty string if none.
        """
        if not self._ensure_initialized():
            return ""

        try:
            results = self._memory.search(
                query=query,
                user_id=self.user_id,
                agent_id=self.agent_id,
                limit=limit,
            )

            if not results or not results.get("results"):
                return ""

            memories = results["results"]
            if not memories:
                return ""

            lines = ["Relevant memories from previous conversations:"]
            for mem in memories:
                memory_text = mem.get("memory", "")
                if memory_text:
                    lines.append(f"  - {memory_text}")

            return "\n".join(lines)
        except Exception:
            return ""

    def get_all_memories(self, limit: int = 50) -> list[dict]:
        """Get all memories for the current user/agent.

        Args:
            limit: Maximum number of memories to retrieve.

        Returns:
            List of memory dictionaries.
        """
        if not self._ensure_initialized():
            return []

        try:
            results = self._memory.get_all(
                user_id=self.user_id,
                agent_id=self.agent_id,
            )

            if not results or not results.get("results"):
                return []

            return results["results"][:limit]
        except Exception:
            return []

    def clear_memories(self) -> bool:
        """Clear all memories for the current user/agent.

        Returns:
            True if cleared successfully, False otherwise.
        """
        if not self._ensure_initialized():
            return False

        try:
            self._memory.delete_all(
                user_id=self.user_id,
                agent_id=self.agent_id,
            )
            return True
        except Exception:
            return False


# Module-level singleton
_memory_client: Optional[MemoryClient] = None


def get_memory_client() -> MemoryClient:
    """Get or create the memory client singleton."""
    global _memory_client
    if _memory_client is None:
        _memory_client = MemoryClient()
    return _memory_client


def reset_memory_client():
    """Reset the memory client singleton (useful for testing)."""
    global _memory_client
    _memory_client = None
