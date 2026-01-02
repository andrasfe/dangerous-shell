"""Semantic command cache for nlsh.

Stores command embeddings locally and provides semantic search
to find similar cached commands. Works with the remote command store
to enable cache-based command execution.

The cache embeds USER REQUESTS (not LLM explanations) so that similar
requests can skip the LLM entirely and use cached commands.
"""

import sqlite3
import uuid
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, Callable

import numpy as np

from embedding_client import (
    get_embedding_client,
    cosine_similarity,
    EmbeddingError,
)


@dataclass
class CachedCommand:
    """A cached command with its embedding."""
    key: str  # UUID
    command: str
    explanation: str  # LLM's explanation (for display)
    user_request: str  # Original user request (for reference)
    embedding: np.ndarray  # Embedding of user_request
    created_at: datetime
    last_used: datetime
    use_count: int = 1


@dataclass
class CacheHit:
    """Result of a successful cache lookup."""
    key: str
    command: str
    explanation: str
    similarity: float


class CommandCache:
    """SQLite-backed semantic command cache.

    Stores commands with embeddings of USER REQUESTS for semantic search.
    This allows similar requests to skip the LLM entirely.
    """

    # Similarity thresholds
    EXACT_MATCH_THRESHOLD = 0.99  # Above this, no LLM validation needed
    SIMILARITY_THRESHOLD = 0.85   # Below this, treat as cache miss

    def __init__(
        self,
        db_path: Path | str | None = None,
        llm_validator: Optional[Callable[[str, str, str], bool]] = None
    ):
        """Initialize the command cache.

        Args:
            db_path: Path to SQLite database. Defaults to ~/.nlsh/cache/commands.db
            llm_validator: Function(natural_request, cached_command, cached_explanation) -> bool
                          Called for similarity matches between SIMILARITY_THRESHOLD and
                          EXACT_MATCH_THRESHOLD to validate if cached command is appropriate.
        """
        if db_path is None:
            db_path = Path.home() / ".nlsh" / "cache" / "commands.db"
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._llm_validator = llm_validator
        self._init_db()

    def _init_db(self):
        """Initialize the database schema."""
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS commands (
                key TEXT PRIMARY KEY,
                command TEXT NOT NULL,
                explanation TEXT NOT NULL,
                user_request TEXT NOT NULL,
                embedding BLOB NOT NULL,
                embedding_dim INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                last_used TEXT NOT NULL,
                use_count INTEGER DEFAULT 1
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_last_used ON commands(last_used)
        """)
        conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        """Get or create database connection."""
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
        return self._conn

    def _embedding_to_bytes(self, embedding: np.ndarray) -> bytes:
        """Convert numpy embedding to bytes for storage."""
        return embedding.astype(np.float32).tobytes()

    def _bytes_to_embedding(self, data: bytes, dim: int) -> np.ndarray:
        """Convert bytes back to numpy embedding."""
        return np.frombuffer(data, dtype=np.float32).reshape(dim)

    def set_llm_validator(self, validator: Callable[[str, str, str], bool]):
        """Set the LLM validator function.

        Args:
            validator: Function(natural_request, cached_command, cached_explanation) -> bool
        """
        self._llm_validator = validator

    def lookup(self, user_request: str) -> Optional[CacheHit]:
        """Look up a cached command by user request.

        This should be called BEFORE the LLM to potentially skip it entirely.

        Args:
            user_request: The user's natural language request.

        Returns:
            CacheHit with command and explanation if found, None otherwise.
        """
        try:
            # Get embedding for user request
            client = get_embedding_client()
            embedding = client.get_embedding(user_request)

            # Search for similar cached requests
            conn = self._get_conn()
            cursor = conn.execute(
                "SELECT key, command, explanation, user_request, embedding, embedding_dim "
                "FROM commands"
            )

            best_match: Optional[tuple] = None
            best_similarity = self.SIMILARITY_THRESHOLD

            for row in cursor:
                cached_embedding = self._bytes_to_embedding(row[4], row[5])
                similarity = cosine_similarity(embedding, cached_embedding)

                if similarity > best_similarity:
                    best_match = (row[0], row[1], row[2], row[3], similarity)
                    best_similarity = similarity

            if not best_match:
                return None

            key, command, explanation, cached_request, similarity = best_match

            # Exact match - no validation needed
            if similarity >= self.EXACT_MATCH_THRESHOLD:
                self._update_usage(key)
                return CacheHit(key=key, command=command, explanation=explanation, similarity=similarity)

            # Similar but not exact - validate with LLM if validator is set
            if self._llm_validator:
                is_valid = self._llm_validator(user_request, command, explanation)
                if is_valid:
                    self._update_usage(key)
                    return CacheHit(key=key, command=command, explanation=explanation, similarity=similarity)

            # Validation failed or no validator
            return None

        except EmbeddingError as e:
            # Embedding API failed - treat as cache miss
            print(f"\033[2m(cache: embedding unavailable)\033[0m")
            return None

    def store(
        self,
        command: str,
        explanation: str,
        user_request: str,
    ) -> str:
        """Store a new command in the cache.

        This should be called AFTER the LLM generates a command.

        Args:
            command: Shell command to cache.
            explanation: LLM's explanation (for display on cache hit).
            user_request: Original user request (embedding source).

        Returns:
            UUID key for the stored command.
        """
        try:
            client = get_embedding_client()
            embedding = client.get_embedding(user_request)

            key = str(uuid.uuid4())
            conn = self._get_conn()
            now = datetime.now()

            conn.execute(
                "INSERT OR REPLACE INTO commands "
                "(key, command, explanation, user_request, embedding, embedding_dim, "
                "created_at, last_used, use_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    key,
                    command,
                    explanation,
                    user_request,
                    self._embedding_to_bytes(embedding),
                    len(embedding),
                    now.isoformat(),
                    now.isoformat(),
                    1,
                )
            )
            conn.commit()
            return key

        except EmbeddingError:
            # Embedding failed - return a key anyway for remote execution
            return str(uuid.uuid4())

    def _update_usage(self, key: str):
        """Update usage statistics for a cached command."""
        conn = self._get_conn()
        now = datetime.now().isoformat()
        conn.execute(
            "UPDATE commands SET last_used = ?, use_count = use_count + 1 WHERE key = ?",
            (now, key)
        )
        conn.commit()

    def get_key_for_command(self, command: str) -> Optional[str]:
        """Get the cache key for a specific command if it exists."""
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT key FROM commands WHERE command = ?",
            (command,)
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def count(self) -> int:
        """Get total number of cached commands."""
        conn = self._get_conn()
        cursor = conn.execute("SELECT COUNT(*) FROM commands")
        return cursor.fetchone()[0]

    def cleanup_old(self, days: int = 30) -> int:
        """Remove entries not used in the specified number of days."""
        from datetime import timedelta

        conn = self._get_conn()
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        cursor = conn.execute(
            "DELETE FROM commands WHERE last_used < ?",
            (cutoff,)
        )
        conn.commit()
        return cursor.rowcount

    def close(self):
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None


# Module-level singleton
_command_cache: Optional[CommandCache] = None


def get_command_cache() -> CommandCache:
    """Get or create the command cache singleton."""
    global _command_cache
    if _command_cache is None:
        _command_cache = CommandCache()
    return _command_cache
