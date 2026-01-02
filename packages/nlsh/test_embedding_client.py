#!/usr/bin/env python3
"""Unit tests for embedding_client.py - OpenRouter embedding API client."""

import pytest
import numpy as np
from unittest.mock import MagicMock, patch, PropertyMock
import requests


class TestEmbeddingError:
    """Tests for EmbeddingError exception class."""

    def test_embedding_error_creation(self):
        """Test EmbeddingError can be raised with message."""
        from embedding_client import EmbeddingError

        with pytest.raises(EmbeddingError) as exc_info:
            raise EmbeddingError("Test error message")

        assert str(exc_info.value) == "Test error message"

    def test_embedding_error_is_exception(self):
        """Test EmbeddingError is a proper Exception subclass."""
        from embedding_client import EmbeddingError

        assert issubclass(EmbeddingError, Exception)


class TestEmbeddingClientInit:
    """Tests for EmbeddingClient initialization."""

    def test_init_with_explicit_api_key(self):
        """Test initialization with explicit API key."""
        from embedding_client import EmbeddingClient

        client = EmbeddingClient(api_key="test-key-123")

        assert client.api_key == "test-key-123"

    def test_init_with_explicit_model(self):
        """Test initialization with explicit model."""
        from embedding_client import EmbeddingClient

        client = EmbeddingClient(api_key="key", model="custom/model")

        assert client.model == "custom/model"

    def test_init_with_custom_base_url(self):
        """Test initialization with custom base URL."""
        from embedding_client import EmbeddingClient

        client = EmbeddingClient(api_key="key", base_url="http://localhost:8000")

        assert client.base_url == "http://localhost:8000"

    def test_init_without_api_key_raises(self):
        """Test initialization without API key raises ValueError."""
        from embedding_client import EmbeddingClient

        # Patch the env var to ensure it's not set
        with patch.dict('os.environ', {'OPENROUTER_API_KEY': ''}, clear=False):
            with patch('embedding_client.OPENROUTER_API_KEY', None):
                with pytest.raises(ValueError) as exc_info:
                    EmbeddingClient(api_key=None)

                assert "API key not provided" in str(exc_info.value)

    def test_init_uses_env_var_api_key(self):
        """Test initialization uses OPENROUTER_API_KEY env var."""
        with patch('embedding_client.OPENROUTER_API_KEY', 'env-key-456'):
            from embedding_client import EmbeddingClient

            # Re-import to pick up patched value
            import embedding_client
            embedding_client.OPENROUTER_API_KEY = 'env-key-456'

            client = EmbeddingClient()
            assert client.api_key == 'env-key-456'

    def test_init_uses_default_model(self):
        """Test initialization uses default embedding model."""
        from embedding_client import EmbeddingClient, EMBEDDING_MODEL

        client = EmbeddingClient(api_key="key")

        assert client.model == EMBEDDING_MODEL


class TestEmbeddingClientGetEmbedding:
    """Tests for EmbeddingClient.get_embedding() method."""

    def test_get_embedding_success(self):
        """Test successful embedding retrieval."""
        from embedding_client import EmbeddingClient

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"embedding": [0.1, 0.2, 0.3, 0.4, 0.5]}
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch('requests.post', return_value=mock_response) as mock_post:
            client = EmbeddingClient(api_key="test-key")
            result = client.get_embedding("test text")

            # Check the result
            assert isinstance(result, np.ndarray)
            assert result.dtype == np.float32
            np.testing.assert_array_almost_equal(result, [0.1, 0.2, 0.3, 0.4, 0.5])

            # Check the API call
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert "embeddings" in call_args[0][0]
            assert call_args[1]['json']['input'] == "test text"
            assert call_args[1]['json']['model'] == client.model

    def test_get_embedding_request_exception(self):
        """Test get_embedding raises EmbeddingError on request failure."""
        from embedding_client import EmbeddingClient, EmbeddingError

        with patch('requests.post') as mock_post:
            mock_post.side_effect = requests.exceptions.RequestException("Connection failed")

            client = EmbeddingClient(api_key="test-key")

            with pytest.raises(EmbeddingError) as exc_info:
                client.get_embedding("test text")

            assert "API request failed" in str(exc_info.value)

    def test_get_embedding_timeout(self):
        """Test get_embedding raises EmbeddingError on timeout."""
        from embedding_client import EmbeddingClient, EmbeddingError

        with patch('requests.post') as mock_post:
            mock_post.side_effect = requests.exceptions.Timeout("Request timed out")

            client = EmbeddingClient(api_key="test-key")

            with pytest.raises(EmbeddingError) as exc_info:
                client.get_embedding("test text")

            assert "API request failed" in str(exc_info.value)

    def test_get_embedding_invalid_response_format(self):
        """Test get_embedding raises EmbeddingError on malformed response."""
        from embedding_client import EmbeddingClient, EmbeddingError

        mock_response = MagicMock()
        mock_response.json.return_value = {"unexpected": "format"}
        mock_response.raise_for_status = MagicMock()

        with patch('requests.post', return_value=mock_response):
            client = EmbeddingClient(api_key="test-key")

            with pytest.raises(EmbeddingError) as exc_info:
                client.get_embedding("test text")

            assert "Invalid API response" in str(exc_info.value)

    def test_get_embedding_empty_data(self):
        """Test get_embedding raises EmbeddingError when data array is empty."""
        from embedding_client import EmbeddingClient, EmbeddingError

        mock_response = MagicMock()
        mock_response.json.return_value = {"data": []}
        mock_response.raise_for_status = MagicMock()

        with patch('requests.post', return_value=mock_response):
            client = EmbeddingClient(api_key="test-key")

            with pytest.raises(EmbeddingError) as exc_info:
                client.get_embedding("test text")

            assert "Invalid API response" in str(exc_info.value)

    def test_get_embedding_http_error(self):
        """Test get_embedding raises EmbeddingError on HTTP error status."""
        from embedding_client import EmbeddingClient, EmbeddingError

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("401 Unauthorized")

        with patch('requests.post', return_value=mock_response):
            client = EmbeddingClient(api_key="test-key")

            with pytest.raises(EmbeddingError) as exc_info:
                client.get_embedding("test text")

            assert "API request failed" in str(exc_info.value)

    def test_get_embedding_includes_auth_header(self):
        """Test that API request includes authorization header."""
        from embedding_client import EmbeddingClient

        mock_response = MagicMock()
        mock_response.json.return_value = {"data": [{"embedding": [0.1]}]}
        mock_response.raise_for_status = MagicMock()

        with patch('requests.post', return_value=mock_response) as mock_post:
            client = EmbeddingClient(api_key="my-secret-key")
            client.get_embedding("test")

            call_kwargs = mock_post.call_args[1]
            assert call_kwargs['headers']['Authorization'] == 'Bearer my-secret-key'

    def test_get_embedding_uses_correct_timeout(self):
        """Test that API request uses 30 second timeout."""
        from embedding_client import EmbeddingClient

        mock_response = MagicMock()
        mock_response.json.return_value = {"data": [{"embedding": [0.1]}]}
        mock_response.raise_for_status = MagicMock()

        with patch('requests.post', return_value=mock_response) as mock_post:
            client = EmbeddingClient(api_key="key")
            client.get_embedding("test")

            call_kwargs = mock_post.call_args[1]
            assert call_kwargs['timeout'] == 30


class TestEmbeddingClientGetEmbeddingsBatch:
    """Tests for EmbeddingClient.get_embeddings_batch() method."""

    def test_get_embeddings_batch_success(self):
        """Test successful batch embedding retrieval."""
        from embedding_client import EmbeddingClient

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"index": 0, "embedding": [0.1, 0.2]},
                {"index": 1, "embedding": [0.3, 0.4]},
                {"index": 2, "embedding": [0.5, 0.6]},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch('requests.post', return_value=mock_response):
            client = EmbeddingClient(api_key="test-key")
            results = client.get_embeddings_batch(["text1", "text2", "text3"])

            assert len(results) == 3
            np.testing.assert_array_almost_equal(results[0], [0.1, 0.2])
            np.testing.assert_array_almost_equal(results[1], [0.3, 0.4])
            np.testing.assert_array_almost_equal(results[2], [0.5, 0.6])

    def test_get_embeddings_batch_empty_input(self):
        """Test batch embedding with empty input returns empty list."""
        from embedding_client import EmbeddingClient

        client = EmbeddingClient(api_key="test-key")
        results = client.get_embeddings_batch([])

        assert results == []

    def test_get_embeddings_batch_preserves_order(self):
        """Test that batch results are returned in input order."""
        from embedding_client import EmbeddingClient

        mock_response = MagicMock()
        # Return in different order than requested (API might not preserve order)
        mock_response.json.return_value = {
            "data": [
                {"index": 2, "embedding": [0.5, 0.6]},  # third
                {"index": 0, "embedding": [0.1, 0.2]},  # first
                {"index": 1, "embedding": [0.3, 0.4]},  # second
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch('requests.post', return_value=mock_response):
            client = EmbeddingClient(api_key="test-key")
            results = client.get_embeddings_batch(["first", "second", "third"])

            # Should be reordered by index
            assert len(results) == 3
            np.testing.assert_array_almost_equal(results[0], [0.1, 0.2])  # index 0
            np.testing.assert_array_almost_equal(results[1], [0.3, 0.4])  # index 1
            np.testing.assert_array_almost_equal(results[2], [0.5, 0.6])  # index 2

    def test_get_embeddings_batch_request_error(self):
        """Test batch embedding raises EmbeddingError on request failure."""
        from embedding_client import EmbeddingClient, EmbeddingError

        with patch('requests.post') as mock_post:
            mock_post.side_effect = requests.exceptions.RequestException("Network error")

            client = EmbeddingClient(api_key="test-key")

            with pytest.raises(EmbeddingError) as exc_info:
                client.get_embeddings_batch(["text1", "text2"])

            assert "API request failed" in str(exc_info.value)

    def test_get_embeddings_batch_invalid_response(self):
        """Test batch embedding raises EmbeddingError on malformed response."""
        from embedding_client import EmbeddingClient, EmbeddingError

        mock_response = MagicMock()
        mock_response.json.return_value = {"wrong": "format"}
        mock_response.raise_for_status = MagicMock()

        with patch('requests.post', return_value=mock_response):
            client = EmbeddingClient(api_key="test-key")

            with pytest.raises(EmbeddingError) as exc_info:
                client.get_embeddings_batch(["text"])

            assert "Invalid API response" in str(exc_info.value)

    def test_get_embeddings_batch_uses_longer_timeout(self):
        """Test that batch request uses 60 second timeout."""
        from embedding_client import EmbeddingClient

        mock_response = MagicMock()
        mock_response.json.return_value = {"data": [{"index": 0, "embedding": [0.1]}]}
        mock_response.raise_for_status = MagicMock()

        with patch('requests.post', return_value=mock_response) as mock_post:
            client = EmbeddingClient(api_key="key")
            client.get_embeddings_batch(["test"])

            call_kwargs = mock_post.call_args[1]
            assert call_kwargs['timeout'] == 60


class TestCosineSimilarity:
    """Tests for cosine_similarity() function."""

    def test_identical_vectors_similarity_one(self):
        """Test that identical normalized vectors have similarity 1.0."""
        from embedding_client import cosine_similarity

        vec = np.array([0.6, 0.8, 0.0])
        similarity = cosine_similarity(vec, vec)

        assert similarity == pytest.approx(1.0)

    def test_orthogonal_vectors_similarity_zero(self):
        """Test that orthogonal vectors have similarity 0.0."""
        from embedding_client import cosine_similarity

        a = np.array([1.0, 0.0, 0.0])
        b = np.array([0.0, 1.0, 0.0])

        similarity = cosine_similarity(a, b)

        assert similarity == pytest.approx(0.0)

    def test_opposite_vectors_similarity_negative_one(self):
        """Test that opposite vectors have similarity -1.0."""
        from embedding_client import cosine_similarity

        a = np.array([1.0, 0.0])
        b = np.array([-1.0, 0.0])

        similarity = cosine_similarity(a, b)

        assert similarity == pytest.approx(-1.0)

    def test_zero_vector_a_returns_zero(self):
        """Test that zero vector as first argument returns 0.0."""
        from embedding_client import cosine_similarity

        a = np.array([0.0, 0.0, 0.0])
        b = np.array([1.0, 2.0, 3.0])

        similarity = cosine_similarity(a, b)

        assert similarity == 0.0

    def test_zero_vector_b_returns_zero(self):
        """Test that zero vector as second argument returns 0.0."""
        from embedding_client import cosine_similarity

        a = np.array([1.0, 2.0, 3.0])
        b = np.array([0.0, 0.0, 0.0])

        similarity = cosine_similarity(a, b)

        assert similarity == 0.0

    def test_similarity_is_normalized(self):
        """Test that similarity is independent of vector magnitude."""
        from embedding_client import cosine_similarity

        a = np.array([1.0, 1.0])
        b = np.array([2.0, 2.0])  # Same direction, different magnitude

        similarity = cosine_similarity(a, b)

        assert similarity == pytest.approx(1.0)

    def test_partial_similarity(self):
        """Test cosine similarity for vectors at an angle."""
        from embedding_client import cosine_similarity

        # 45 degree angle has cosine of sqrt(2)/2 ~ 0.707
        a = np.array([1.0, 0.0])
        b = np.array([1.0, 1.0])

        similarity = cosine_similarity(a, b)

        expected = np.sqrt(2) / 2  # ~0.707
        assert similarity == pytest.approx(expected, rel=1e-5)

    def test_returns_float(self):
        """Test that similarity returns a Python float."""
        from embedding_client import cosine_similarity

        a = np.array([1.0, 0.0])
        b = np.array([0.0, 1.0])

        result = cosine_similarity(a, b)

        assert isinstance(result, float)


class TestGetEmbeddingClientSingleton:
    """Tests for get_embedding_client() singleton function."""

    def test_returns_embedding_client_instance(self):
        """Test that get_embedding_client returns EmbeddingClient instance."""
        with patch('embedding_client.OPENROUTER_API_KEY', 'test-key'):
            import embedding_client
            embedding_client.OPENROUTER_API_KEY = 'test-key'
            embedding_client._embedding_client = None  # Reset singleton

            client = embedding_client.get_embedding_client()

            assert isinstance(client, embedding_client.EmbeddingClient)

    def test_returns_same_instance(self):
        """Test that get_embedding_client returns the same instance on multiple calls."""
        with patch('embedding_client.OPENROUTER_API_KEY', 'test-key'):
            import embedding_client
            embedding_client.OPENROUTER_API_KEY = 'test-key'
            embedding_client._embedding_client = None  # Reset singleton

            client1 = embedding_client.get_embedding_client()
            client2 = embedding_client.get_embedding_client()

            assert client1 is client2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
