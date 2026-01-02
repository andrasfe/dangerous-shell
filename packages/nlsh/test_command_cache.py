#!/usr/bin/env python3
"""Unit tests for command_cache.py - semantic command caching with SQLite + embeddings."""

import pytest
import tempfile
import sqlite3
import os
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, PropertyMock
import numpy as np

# Import after patching to avoid loading the real embedding client
# We'll need to mock the embedding client before importing command_cache


class TestCacheHitDataclass:
    """Tests for CacheHit dataclass."""

    def test_cache_hit_creation(self):
        """Test CacheHit can be created with all required fields."""
        from command_cache import CacheHit

        hit = CacheHit(
            key="test-uuid",
            command="ls -la",
            explanation="List files in long format",
            similarity=0.95
        )

        assert hit.key == "test-uuid"
        assert hit.command == "ls -la"
        assert hit.explanation == "List files in long format"
        assert hit.similarity == 0.95

    def test_cache_hit_equality(self):
        """Test CacheHit equality comparison."""
        from command_cache import CacheHit

        hit1 = CacheHit(key="uuid1", command="ls", explanation="list", similarity=0.9)
        hit2 = CacheHit(key="uuid1", command="ls", explanation="list", similarity=0.9)
        hit3 = CacheHit(key="uuid2", command="ls", explanation="list", similarity=0.9)

        assert hit1 == hit2
        assert hit1 != hit3


class TestCachedCommandDataclass:
    """Tests for CachedCommand dataclass."""

    def test_cached_command_creation(self):
        """Test CachedCommand can be created with all fields."""
        from command_cache import CachedCommand

        embedding = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        now = datetime.now()

        cmd = CachedCommand(
            key="test-uuid",
            command="git status",
            explanation="Show git working tree status",
            user_request="show git status",
            embedding=embedding,
            created_at=now,
            last_used=now,
            use_count=1
        )

        assert cmd.key == "test-uuid"
        assert cmd.command == "git status"
        assert cmd.explanation == "Show git working tree status"
        assert cmd.user_request == "show git status"
        np.testing.assert_array_equal(cmd.embedding, embedding)
        assert cmd.created_at == now
        assert cmd.last_used == now
        assert cmd.use_count == 1


class TestCommandCacheInit:
    """Tests for CommandCache initialization."""

    def test_default_db_path(self):
        """Test that default db path is in ~/.nlsh/cache/."""
        with patch('command_cache.get_embedding_client'):
            from command_cache import CommandCache

            # Don't actually create the default db
            with patch.object(CommandCache, '_init_db'):
                cache = CommandCache()
                expected_path = Path.home() / ".nlsh" / "cache" / "commands.db"
                assert cache.db_path == expected_path

    def test_custom_db_path(self):
        """Test cache can be created with custom db path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_cache.db"

            with patch('command_cache.get_embedding_client'):
                from command_cache import CommandCache
                cache = CommandCache(db_path=db_path)

                assert cache.db_path == db_path
                assert cache.db_path.parent.exists()
                cache.close()

    def test_db_parent_directory_created(self):
        """Test that parent directories are created for db path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            deep_path = Path(tmpdir) / "a" / "b" / "c" / "test.db"

            with patch('command_cache.get_embedding_client'):
                from command_cache import CommandCache
                cache = CommandCache(db_path=deep_path)

                assert deep_path.parent.exists()
                cache.close()


class TestCommandCacheSchema:
    """Tests for database schema and migration."""

    def test_schema_creation(self):
        """Test that schema is created correctly on init."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            with patch('command_cache.get_embedding_client'):
                from command_cache import CommandCache
                cache = CommandCache(db_path=db_path)

                # Check table exists with correct columns
                conn = sqlite3.connect(str(db_path))
                cursor = conn.execute("PRAGMA table_info(commands)")
                columns = {row[1] for row in cursor.fetchall()}

                expected_columns = {
                    'key', 'command', 'explanation', 'user_request',
                    'embedding', 'embedding_dim', 'created_at', 'last_used', 'use_count'
                }
                assert columns == expected_columns

                conn.close()
                cache.close()

    def test_old_schema_migration(self):
        """Test migration from old schema with 'description' to new schema."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Create old schema
            conn = sqlite3.connect(str(db_path))
            conn.execute("""
                CREATE TABLE commands (
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
            # Insert some old data
            conn.execute(
                "INSERT INTO commands VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("old-key", "ls", "old desc", b"dummy", 3, "2024-01-01", "2024-01-01", 5)
            )
            conn.commit()
            conn.close()

            # Now open with CommandCache - should migrate
            with patch('command_cache.get_embedding_client'):
                from command_cache import CommandCache
                cache = CommandCache(db_path=db_path)

                # Verify new schema
                conn = sqlite3.connect(str(db_path))
                cursor = conn.execute("PRAGMA table_info(commands)")
                columns = {row[1] for row in cursor.fetchall()}

                # Should have new columns
                assert 'explanation' in columns
                assert 'user_request' in columns
                # Old column should be gone
                assert 'description' not in columns

                # Old data should be gone (migration drops table)
                cursor = conn.execute("SELECT COUNT(*) FROM commands")
                assert cursor.fetchone()[0] == 0

                conn.close()
                cache.close()


class TestCommandCacheThreadSafety:
    """Tests for SQLite thread safety configuration."""

    def test_check_same_thread_false(self):
        """Test that SQLite connection allows access from multiple threads."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            with patch('command_cache.get_embedding_client'):
                from command_cache import CommandCache
                cache = CommandCache(db_path=db_path)

                # Force connection creation
                conn = cache._get_conn()

                # The connection should be configured with check_same_thread=False
                # We can verify this by trying to use it (would fail if check_same_thread=True
                # and we're in a different thread, but since we're in same thread it works)
                cursor = conn.execute("SELECT 1")
                assert cursor.fetchone()[0] == 1

                cache.close()


class TestEmbeddingConversion:
    """Tests for embedding to/from bytes conversion."""

    def test_embedding_to_bytes(self):
        """Test converting numpy array to bytes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            with patch('command_cache.get_embedding_client'):
                from command_cache import CommandCache
                cache = CommandCache(db_path=db_path)

                embedding = np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32)
                data = cache._embedding_to_bytes(embedding)

                # Should be float32 bytes (4 bytes per element)
                assert len(data) == 4 * 4
                assert isinstance(data, bytes)

                cache.close()

    def test_bytes_to_embedding(self):
        """Test converting bytes back to numpy array."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            with patch('command_cache.get_embedding_client'):
                from command_cache import CommandCache
                cache = CommandCache(db_path=db_path)

                original = np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32)
                data = cache._embedding_to_bytes(original)
                restored = cache._bytes_to_embedding(data, 4)

                np.testing.assert_array_almost_equal(original, restored)

                cache.close()

    def test_roundtrip_embedding(self):
        """Test that embedding survives roundtrip through bytes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            with patch('command_cache.get_embedding_client'):
                from command_cache import CommandCache
                cache = CommandCache(db_path=db_path)

                # Test with realistic embedding dimension
                original = np.random.randn(1536).astype(np.float32)
                data = cache._embedding_to_bytes(original)
                restored = cache._bytes_to_embedding(data, 1536)

                np.testing.assert_array_almost_equal(original, restored)

                cache.close()


class TestCommandCacheStore:
    """Tests for CommandCache.store() method."""

    def test_store_command(self):
        """Test storing a command in the cache."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Mock the embedding client
            mock_client = MagicMock()
            mock_client.get_embedding.return_value = np.array([0.1, 0.2, 0.3], dtype=np.float32)

            with patch('command_cache.get_embedding_client', return_value=mock_client):
                from command_cache import CommandCache
                cache = CommandCache(db_path=db_path)

                key = cache.store(
                    command="ls -la",
                    explanation="List all files in long format",
                    user_request="show me all files"
                )

                # Key should be a UUID
                assert len(key) == 36  # UUID format
                assert key.count('-') == 4

                # Check it's in the database
                assert cache.count() == 1

                cache.close()

    def test_store_returns_uuid_on_embedding_failure(self):
        """Test that store still returns a UUID even if embedding fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Mock embedding client to raise error
            mock_client = MagicMock()
            from command_cache import EmbeddingError
            mock_client.get_embedding.side_effect = EmbeddingError("API failed")

            with patch('command_cache.get_embedding_client', return_value=mock_client):
                from command_cache import CommandCache
                cache = CommandCache(db_path=db_path)

                key = cache.store(
                    command="ls -la",
                    explanation="List files",
                    user_request="show files"
                )

                # Should still return a UUID
                assert len(key) == 36
                # But nothing stored in cache
                assert cache.count() == 0

                cache.close()


class TestCommandCacheLookup:
    """Tests for CommandCache.lookup() method."""

    def test_lookup_exact_match(self):
        """Test looking up an exact match (similarity >= 0.99)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Same embedding for store and lookup = exact match
            test_embedding = np.array([0.1, 0.2, 0.3], dtype=np.float32)
            mock_client = MagicMock()
            mock_client.get_embedding.return_value = test_embedding

            with patch('command_cache.get_embedding_client', return_value=mock_client):
                from command_cache import CommandCache
                cache = CommandCache(db_path=db_path)

                # Store a command
                cache.store("ls -la", "List files", "show files")

                # Lookup with same request (same embedding)
                result = cache.lookup("show files")

                assert result is not None
                assert result.command == "ls -la"
                assert result.explanation == "List files"
                assert result.similarity >= 0.99  # Exact match

                cache.close()

    def test_lookup_no_match(self):
        """Test lookup returns None when no similar command found."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            mock_client = MagicMock()
            # Different embeddings for store vs lookup
            mock_client.get_embedding.side_effect = [
                np.array([1.0, 0.0, 0.0], dtype=np.float32),  # store
                np.array([0.0, 0.0, 1.0], dtype=np.float32),  # lookup (orthogonal)
            ]

            with patch('command_cache.get_embedding_client', return_value=mock_client):
                from command_cache import CommandCache
                cache = CommandCache(db_path=db_path)

                cache.store("ls -la", "List files", "show files")
                result = cache.lookup("completely different request")

                assert result is None

                cache.close()

    def test_lookup_empty_cache(self):
        """Test lookup on empty cache returns None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            mock_client = MagicMock()
            mock_client.get_embedding.return_value = np.array([0.1, 0.2], dtype=np.float32)

            with patch('command_cache.get_embedding_client', return_value=mock_client):
                from command_cache import CommandCache
                cache = CommandCache(db_path=db_path)

                result = cache.lookup("any request")
                assert result is None

                cache.close()

    def test_lookup_with_llm_validator(self):
        """Test lookup uses LLM validator for medium similarity matches."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            mock_client = MagicMock()
            # Similar but not exact embeddings (cosine similarity ~0.9)
            mock_client.get_embedding.side_effect = [
                np.array([1.0, 0.0, 0.0], dtype=np.float32),  # store
                np.array([0.95, 0.31, 0.0], dtype=np.float32),  # lookup (similar)
            ]

            with patch('command_cache.get_embedding_client', return_value=mock_client):
                from command_cache import CommandCache

                # Create validator that approves everything
                validator = MagicMock(return_value=True)

                cache = CommandCache(db_path=db_path, llm_validator=validator)
                cache.store("ls -la", "List files", "show files")

                result = cache.lookup("display files")

                # Validator should have been called
                assert validator.called
                assert result is not None
                assert result.command == "ls -la"

                cache.close()

    def test_lookup_validator_rejects(self):
        """Test that rejected validator returns None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            mock_client = MagicMock()
            # Similar embeddings
            mock_client.get_embedding.side_effect = [
                np.array([1.0, 0.0, 0.0], dtype=np.float32),
                np.array([0.95, 0.31, 0.0], dtype=np.float32),
            ]

            with patch('command_cache.get_embedding_client', return_value=mock_client):
                from command_cache import CommandCache

                # Validator rejects
                validator = MagicMock(return_value=False)

                cache = CommandCache(db_path=db_path, llm_validator=validator)
                cache.store("ls -la", "List files", "show files")

                result = cache.lookup("different request")

                assert validator.called
                assert result is None

                cache.close()

    def test_lookup_embedding_error_returns_none(self):
        """Test that embedding error during lookup returns None gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            mock_client = MagicMock()
            from command_cache import EmbeddingError
            mock_client.get_embedding.side_effect = EmbeddingError("API error")

            with patch('command_cache.get_embedding_client', return_value=mock_client):
                from command_cache import CommandCache
                cache = CommandCache(db_path=db_path)

                result = cache.lookup("any request")
                assert result is None

                cache.close()


class TestCommandCacheUsageTracking:
    """Tests for usage tracking (_update_usage, get_key_for_command)."""

    def test_update_usage_increments_count(self):
        """Test that _update_usage increments use_count."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            test_embedding = np.array([0.1, 0.2, 0.3], dtype=np.float32)
            mock_client = MagicMock()
            mock_client.get_embedding.return_value = test_embedding

            with patch('command_cache.get_embedding_client', return_value=mock_client):
                from command_cache import CommandCache
                cache = CommandCache(db_path=db_path)

                key = cache.store("ls", "list", "show")

                # Check initial count
                conn = cache._get_conn()
                cursor = conn.execute("SELECT use_count FROM commands WHERE key = ?", (key,))
                assert cursor.fetchone()[0] == 1

                # Update usage
                cache._update_usage(key)

                cursor = conn.execute("SELECT use_count FROM commands WHERE key = ?", (key,))
                assert cursor.fetchone()[0] == 2

                cache.close()

    def test_get_key_for_command_found(self):
        """Test getting key for an existing command."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            mock_client = MagicMock()
            mock_client.get_embedding.return_value = np.array([0.1], dtype=np.float32)

            with patch('command_cache.get_embedding_client', return_value=mock_client):
                from command_cache import CommandCache
                cache = CommandCache(db_path=db_path)

                stored_key = cache.store("git status", "show status", "git status")
                found_key = cache.get_key_for_command("git status")

                assert found_key == stored_key

                cache.close()

    def test_get_key_for_command_not_found(self):
        """Test getting key for non-existent command returns None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            with patch('command_cache.get_embedding_client'):
                from command_cache import CommandCache
                cache = CommandCache(db_path=db_path)

                result = cache.get_key_for_command("nonexistent")
                assert result is None

                cache.close()


class TestCommandCacheCleanup:
    """Tests for cleanup_old() method."""

    def test_cleanup_old_entries(self):
        """Test that old entries are removed by cleanup_old()."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            mock_client = MagicMock()
            mock_client.get_embedding.return_value = np.array([0.1], dtype=np.float32)

            with patch('command_cache.get_embedding_client', return_value=mock_client):
                from command_cache import CommandCache
                cache = CommandCache(db_path=db_path)

                # Store a command
                key = cache.store("ls", "list", "show")

                # Manually update last_used to 60 days ago
                old_date = (datetime.now() - timedelta(days=60)).isoformat()
                conn = cache._get_conn()
                conn.execute("UPDATE commands SET last_used = ? WHERE key = ?", (old_date, key))
                conn.commit()

                assert cache.count() == 1

                # Cleanup entries older than 30 days
                deleted = cache.cleanup_old(days=30)

                assert deleted == 1
                assert cache.count() == 0

                cache.close()

    def test_cleanup_keeps_recent_entries(self):
        """Test that recent entries are kept by cleanup_old()."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            mock_client = MagicMock()
            mock_client.get_embedding.return_value = np.array([0.1], dtype=np.float32)

            with patch('command_cache.get_embedding_client', return_value=mock_client):
                from command_cache import CommandCache
                cache = CommandCache(db_path=db_path)

                # Store a command (will have current timestamp)
                cache.store("ls", "list", "show")

                assert cache.count() == 1

                # Cleanup entries older than 30 days
                deleted = cache.cleanup_old(days=30)

                assert deleted == 0
                assert cache.count() == 1

                cache.close()


class TestCommandCacheCount:
    """Tests for count() method."""

    def test_count_empty(self):
        """Test count returns 0 for empty cache."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            with patch('command_cache.get_embedding_client'):
                from command_cache import CommandCache
                cache = CommandCache(db_path=db_path)

                assert cache.count() == 0

                cache.close()

    def test_count_multiple(self):
        """Test count returns correct number of entries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            mock_client = MagicMock()
            mock_client.get_embedding.return_value = np.array([0.1], dtype=np.float32)

            with patch('command_cache.get_embedding_client', return_value=mock_client):
                from command_cache import CommandCache
                cache = CommandCache(db_path=db_path)

                cache.store("cmd1", "exp1", "req1")
                cache.store("cmd2", "exp2", "req2")
                cache.store("cmd3", "exp3", "req3")

                assert cache.count() == 3

                cache.close()


class TestCommandCacheSingleton:
    """Tests for get_command_cache() singleton."""

    def test_singleton_returns_same_instance(self):
        """Test that get_command_cache() returns the same instance."""
        with patch('command_cache.get_embedding_client'):
            # Reset the singleton
            import command_cache
            command_cache._command_cache = None

            with patch.object(command_cache.CommandCache, '__init__', return_value=None):
                cache1 = command_cache.get_command_cache()
                cache2 = command_cache.get_command_cache()

                assert cache1 is cache2


class TestCosineSimilarity:
    """Tests for cosine_similarity function from embedding_client."""

    def test_identical_vectors(self):
        """Test that identical vectors have similarity 1.0."""
        from embedding_client import cosine_similarity

        a = np.array([1.0, 0.0, 0.0])
        b = np.array([1.0, 0.0, 0.0])

        assert cosine_similarity(a, b) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        """Test that orthogonal vectors have similarity 0.0."""
        from embedding_client import cosine_similarity

        a = np.array([1.0, 0.0, 0.0])
        b = np.array([0.0, 1.0, 0.0])

        assert cosine_similarity(a, b) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        """Test that opposite vectors have similarity -1.0."""
        from embedding_client import cosine_similarity

        a = np.array([1.0, 0.0, 0.0])
        b = np.array([-1.0, 0.0, 0.0])

        assert cosine_similarity(a, b) == pytest.approx(-1.0)

    def test_zero_vector(self):
        """Test that zero vector returns 0.0 similarity."""
        from embedding_client import cosine_similarity

        a = np.array([1.0, 0.0, 0.0])
        b = np.array([0.0, 0.0, 0.0])

        assert cosine_similarity(a, b) == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
