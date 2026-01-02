"""OpenRouter embedding client for semantic command caching."""

import os
from typing import Optional

import requests
import numpy as np
from dotenv import load_dotenv

load_dotenv()

# Configuration
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
EMBEDDING_MODEL = os.getenv("OPENROUTER_EMBEDDING_MODEL", "openai/text-embedding-3-small")


class EmbeddingError(Exception):
    """Error getting embeddings from API."""
    pass


class EmbeddingClient:
    """Client for getting text embeddings via OpenRouter API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str = "https://openrouter.ai/api/v1"
    ):
        """Initialize embedding client.

        Args:
            api_key: OpenRouter API key. Defaults to OPENROUTER_API_KEY env var.
            model: Embedding model to use. Defaults to OPENROUTER_EMBEDDING_MODEL env var.
            base_url: API base URL.
        """
        self.api_key = api_key or OPENROUTER_API_KEY
        self.model = model or EMBEDDING_MODEL
        self.base_url = base_url

        if not self.api_key:
            raise ValueError("OpenRouter API key not provided and OPENROUTER_API_KEY not set")

    def get_embedding(self, text: str) -> np.ndarray:
        """Get embedding vector for text.

        Args:
            text: Text to embed.

        Returns:
            Numpy array of embedding values (float32).

        Raises:
            EmbeddingError: If API call fails.
        """
        try:
            response = requests.post(
                f"{self.base_url}/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "input": text,
                },
                timeout=30,
            )
            response.raise_for_status()

            data = response.json()
            embedding = data["data"][0]["embedding"]
            return np.array(embedding, dtype=np.float32)

        except requests.exceptions.RequestException as e:
            raise EmbeddingError(f"API request failed: {e}")
        except (KeyError, IndexError) as e:
            raise EmbeddingError(f"Invalid API response: {e}")

    def get_embeddings_batch(self, texts: list[str]) -> list[np.ndarray]:
        """Get embeddings for multiple texts in one request.

        Args:
            texts: List of texts to embed.

        Returns:
            List of numpy arrays, one per input text.

        Raises:
            EmbeddingError: If API call fails.
        """
        if not texts:
            return []

        try:
            response = requests.post(
                f"{self.base_url}/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "input": texts,
                },
                timeout=60,
            )
            response.raise_for_status()

            data = response.json()
            embeddings = []
            for item in sorted(data["data"], key=lambda x: x["index"]):
                embeddings.append(np.array(item["embedding"], dtype=np.float32))
            return embeddings

        except requests.exceptions.RequestException as e:
            raise EmbeddingError(f"API request failed: {e}")
        except (KeyError, IndexError) as e:
            raise EmbeddingError(f"Invalid API response: {e}")


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors.

    Args:
        a: First embedding vector.
        b: Second embedding vector.

    Returns:
        Cosine similarity in range [-1, 1].
    """
    dot_product = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return float(dot_product / (norm_a * norm_b))


# Module-level singleton
_embedding_client: Optional[EmbeddingClient] = None


def get_embedding_client() -> EmbeddingClient:
    """Get or create the embedding client singleton."""
    global _embedding_client
    if _embedding_client is None:
        _embedding_client = EmbeddingClient()
    return _embedding_client
