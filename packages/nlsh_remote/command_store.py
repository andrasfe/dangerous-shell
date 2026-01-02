"""Persistent key-value store for cached commands on the remote server."""

import sqlite3
from pathlib import Path
from typing import Optional
from datetime import datetime


class CommandStore:
    """SQLite-backed key-value store for command caching.

    Stores UUID -> command mappings for the semantic command cache.
    The remote server uses this to look up commands by key without
    needing to receive the full command text on cache hits.
    """

    def __init__(self, db_path: Path | str | None = None):
        """Initialize the command store.

        Args:
            db_path: Path to SQLite database. Defaults to ~/.nlsh/command_store.db
        """
        if db_path is None:
            db_path = Path.home() / ".nlsh" / "command_store.db"
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _init_db(self):
        """Initialize the database schema."""
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS commands (
                key TEXT PRIMARY KEY,
                command TEXT NOT NULL,
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

    def get(self, key: str) -> Optional[str]:
        """Look up a command by key.

        Args:
            key: UUID key

        Returns:
            Command string if found, None otherwise.
        """
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT command FROM commands WHERE key = ?",
            (key,)
        )
        row = cursor.fetchone()

        if row:
            # Update usage statistics
            now = datetime.now().isoformat()
            conn.execute(
                "UPDATE commands SET last_used = ?, use_count = use_count + 1 WHERE key = ?",
                (now, key)
            )
            conn.commit()
            return row[0]

        return None

    def put(self, key: str, command: str) -> bool:
        """Store a command with the given key.

        Args:
            key: UUID key
            command: Command string to store

        Returns:
            True if stored successfully, False if key already exists with different command.
        """
        conn = self._get_conn()
        now = datetime.now().isoformat()

        # Check if key exists
        cursor = conn.execute(
            "SELECT command FROM commands WHERE key = ?",
            (key,)
        )
        existing = cursor.fetchone()

        if existing:
            if existing[0] == command:
                # Same command, just update stats
                conn.execute(
                    "UPDATE commands SET last_used = ?, use_count = use_count + 1 WHERE key = ?",
                    (now, key)
                )
                conn.commit()
                return True
            else:
                # Key exists with different command - this shouldn't happen with UUIDs
                return False

        # Insert new entry
        conn.execute(
            "INSERT INTO commands (key, command, created_at, last_used, use_count) VALUES (?, ?, ?, ?, ?)",
            (key, command, now, now, 1)
        )
        conn.commit()
        return True

    def delete(self, key: str) -> bool:
        """Delete a command by key.

        Args:
            key: UUID key

        Returns:
            True if deleted, False if key not found.
        """
        conn = self._get_conn()
        cursor = conn.execute("DELETE FROM commands WHERE key = ?", (key,))
        conn.commit()
        return cursor.rowcount > 0

    def count(self) -> int:
        """Get total number of cached commands."""
        conn = self._get_conn()
        cursor = conn.execute("SELECT COUNT(*) FROM commands")
        return cursor.fetchone()[0]

    def cleanup_old(self, days: int = 30) -> int:
        """Remove entries not used in the specified number of days.

        Args:
            days: Number of days of inactivity before cleanup

        Returns:
            Number of entries removed.
        """
        conn = self._get_conn()
        cutoff = datetime.now()
        # Simple approach: compare ISO strings (works for our purposes)
        from datetime import timedelta
        cutoff_str = (cutoff - timedelta(days=days)).isoformat()

        cursor = conn.execute(
            "DELETE FROM commands WHERE last_used < ?",
            (cutoff_str,)
        )
        conn.commit()
        return cursor.rowcount

    def close(self):
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None


# Module-level singleton
_command_store: Optional[CommandStore] = None


def get_command_store() -> CommandStore:
    """Get or create the command store singleton."""
    global _command_store
    if _command_store is None:
        _command_store = CommandStore()
    return _command_store
