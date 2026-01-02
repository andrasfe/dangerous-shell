"""Semantic command cache for nlsh.

Stores command embeddings locally and provides semantic search
to find similar cached commands. Works with the remote command store
to enable cache-based command execution.
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
    description: str
    embedding: np.ndarray
    created_at: datetime
    last_used: datetime
    use_count: int = 1


@dataclass
class CacheSearchResult:
    """Result of a cache search."""
    cached: CachedCommand
    similarity: float


class CommandCache:
    """SQLite-backed semantic command cache.

    Stores commands with their embeddings for semantic search.
    Uses cosine similarity to find similar cached commands.
    """

    # Similarity thresholds
    EXACT_MATCH_THRESHOLD = 0.99  # Above this, no LLM validation needed
    SIMILARITY_THRESHOLD = 0.85   # Below this, create new entry

    def __init__(
        self,
        db_path: Path | str | None = None,
        llm_validator: Optional[Callable[[str, str, str], bool]] = None
    ):
        """Initialize the command cache.

        Args:
            db_path: Path to SQLite database. Defaults to ~/.nlsh/cache/commands.db
            llm_validator: Function(natural_request, cached_command, cached_description) -> bool
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
                description TEXT NOT NULL,
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
            validator: Function(natural_request, cached_command, cached_description) -> bool
        """
        self._llm_validator = validator

    def search(self, embedding: np.ndarray, threshold: float | None = None) -> Optional[CacheSearchResult]:
        """Search for similar cached commands.

        Args:
            embedding: Query embedding vector.
            threshold: Minimum similarity threshold. Defaults to SIMILARITY_THRESHOLD.

        Returns:
            Best matching result above threshold, or None.
        """
        if threshold is None:
            threshold = self.SIMILARITY_THRESHOLD

        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT key, command, description, embedding, embedding_dim, "
            "created_at, last_used, use_count FROM commands"
        )

        best_match: Optional[CacheSearchResult] = None
        best_similarity = threshold

        for row in cursor:
            cached_embedding = self._bytes_to_embedding(row[3], row[4])
            similarity = cosine_similarity(embedding, cached_embedding)

            if similarity > best_similarity:
                cached = CachedCommand(
                    key=row[0],
                    command=row[1],
                    description=row[2],
                    embedding=cached_embedding,
                    created_at=datetime.fromisoformat(row[5]),
                    last_used=datetime.fromisoformat(row[6]),
                    use_count=row[7],
                )
                best_match = CacheSearchResult(cached=cached, similarity=similarity)
                best_similarity = similarity

        return best_match

    def store(
        self,
        key: str,
        command: str,
        description: str,
        embedding: np.ndarray
    ) -> CachedCommand:
        """Store a new command in the cache.

        Args:
            key: UUID key.
            command: Shell command.
            description: Natural language description.
            embedding: Embedding vector.

        Returns:
            The stored CachedCommand.
        """
        conn = self._get_conn()
        now = datetime.now()

        conn.execute(
            "INSERT OR REPLACE INTO commands "
            "(key, command, description, embedding, embedding_dim, created_at, last_used, use_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                key,
                command,
                description,
                self._embedding_to_bytes(embedding),
                len(embedding),
                now.isoformat(),
                now.isoformat(),
                1,
            )
        )
        conn.commit()

        return CachedCommand(
            key=key,
            command=command,
            description=description,
            embedding=embedding,
            created_at=now,
            last_used=now,
            use_count=1,
        )

    def update_usage(self, key: str):
        """Update usage statistics for a cached command."""
        conn = self._get_conn()
        now = datetime.now().isoformat()
        conn.execute(
            "UPDATE commands SET last_used = ?, use_count = use_count + 1 WHERE key = ?",
            (now, key)
        )
        conn.commit()

    def get_or_create_key(
        self,
        command: str,
        description: str,
        natural_request: str,
    ) -> tuple[str, bool]:
        """Get existing cache key or create a new one.

        This is the main entry point for the cache. It:
        1. Embeds the description
        2. Searches for similar cached commands
        3. For exact matches (>0.99): returns cached key
        4. For similar matches (0.85-0.99): validates with LLM
        5. For misses (<0.85) or failed validation: creates new entry

        Args:
            command: The shell command to cache.
            description: Natural language description (from LLM explanation).
            natural_request: Original user request (for LLM validation).

        Returns:
            Tuple of (key, is_cached) where:
            - key: UUID for this command
            - is_cached: True if this was a cache hit (key already exists on remote)
        """
        try:
            # Get embedding for description
            client = get_embedding_client()
            embedding = client.get_embedding(description)

            # Search cache
            result = self.search(embedding)

            if result:
                # Check if exact match
                if result.similarity >= self.EXACT_MATCH_THRESHOLD:
                    self.update_usage(result.cached.key)
                    return result.cached.key, True

                # Similar but not exact - validate with LLM
                if self._llm_validator:
                    is_valid = self._llm_validator(
                        natural_request,
                        result.cached.command,
                        result.cached.description
                    )
                    if is_valid:
                        self.update_usage(result.cached.key)
                        return result.cached.key, True
                    # LLM said cached command is not appropriate - fall through to create new

            # No match or validation failed - create new entry
            key = str(uuid.uuid4())
            self.store(key, command, description, embedding)
            return key, False

        except EmbeddingError as e:
            # Embedding API failed - create new key without caching
            print(f"\033[1;33mWarning: Cache unavailable ({e})\033[0m")
            return str(uuid.uuid4()), False

    def count(self) -> int:
        """Get total number of cached commands."""
        conn = self._get_conn()
        cursor = conn.execute("SELECT COUNT(*) FROM commands")
        return cursor.fetchone()[0]

    def cleanup_old(self, days: int = 30) -> int:
        """Remove entries not used in the specified number of days.

        Args:
            days: Number of days of inactivity before cleanup.

        Returns:
            Number of entries removed.
        """
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
