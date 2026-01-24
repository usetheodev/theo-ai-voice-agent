"""SentenceTransformer embedding provider.

Provides local text embeddings using sentence-transformers models.
These models run entirely on the local machine, making them ideal
for privacy-sensitive applications.

Example:
    >>> from voice_pipeline.providers.embedding import SentenceTransformerEmbedding
    >>>
    >>> # Create embedding with default model
    >>> embedding = SentenceTransformerEmbedding()
    >>>
    >>> # Embed text
    >>> vector = await embedding.embed("Hello world")
    >>> print(len(vector))  # 384 for default model
    >>>
    >>> # Batch embedding (more efficient)
    >>> vectors = await embedding.embed_batch(["Hello", "World"])
"""

import asyncio
from dataclasses import dataclass, field
from typing import Optional

from voice_pipeline.interfaces.rag import EmbeddingInterface


@dataclass
class SentenceTransformerEmbeddingConfig:
    """Configuration for SentenceTransformer embedding.

    Attributes:
        model_name: Name of the sentence-transformers model.
            Popular choices:
            - "all-MiniLM-L6-v2" (default): Fast, 384 dimensions
            - "all-mpnet-base-v2": Better quality, 768 dimensions
            - "paraphrase-multilingual-MiniLM-L12-v2": Multilingual
        device: Device to run model on ("cpu", "cuda", "mps").
            Auto-detected if None.
        normalize_embeddings: Whether to L2-normalize embeddings.
        batch_size: Batch size for embedding.
        show_progress_bar: Show progress bar during embedding.

    Example:
        >>> config = SentenceTransformerEmbeddingConfig(
        ...     model_name="all-mpnet-base-v2",
        ...     device="cuda",
        ... )
    """

    model_name: str = "all-MiniLM-L6-v2"
    """Name of the sentence-transformers model."""

    device: Optional[str] = None
    """Device to run model on (auto-detected if None)."""

    normalize_embeddings: bool = True
    """Whether to L2-normalize embeddings."""

    batch_size: int = 32
    """Batch size for embedding."""

    show_progress_bar: bool = False
    """Show progress bar during embedding."""


class SentenceTransformerEmbedding(EmbeddingInterface):
    """Embedding provider using sentence-transformers.

    Uses sentence-transformers library for local text embedding.
    Models run entirely on the local machine.

    Example:
        >>> embedding = SentenceTransformerEmbedding()
        >>>
        >>> # Single embedding
        >>> vector = await embedding.embed("Voice Pipeline is great!")
        >>>
        >>> # Batch embedding (more efficient)
        >>> vectors = await embedding.embed_batch([
        ...     "First document",
        ...     "Second document",
        ... ])
    """

    def __init__(
        self,
        config: Optional[SentenceTransformerEmbeddingConfig] = None,
        *,
        model_name: Optional[str] = None,
        device: Optional[str] = None,
        normalize_embeddings: Optional[bool] = None,
    ):
        """Initialize SentenceTransformer embedding.

        Args:
            config: Configuration object (optional).
            model_name: Model name shortcut (overrides config).
            device: Device shortcut (overrides config).
            normalize_embeddings: Normalize shortcut (overrides config).
        """
        self._config = config or SentenceTransformerEmbeddingConfig()

        # Apply shortcuts
        if model_name is not None:
            self._config.model_name = model_name
        if device is not None:
            self._config.device = device
        if normalize_embeddings is not None:
            self._config.normalize_embeddings = normalize_embeddings

        self._model = None
        self._dimension: Optional[int] = None
        self._lock = asyncio.Lock()

    def _ensure_model(self):
        """Lazily load the model."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as e:
                raise ImportError(
                    "sentence-transformers is required for SentenceTransformerEmbedding. "
                    "Install it with: pip install sentence-transformers"
                ) from e

            self._model = SentenceTransformer(
                self._config.model_name,
                device=self._config.device,
            )
            self._dimension = self._model.get_sentence_embedding_dimension()

    async def embed(self, text: str) -> list[float]:
        """Embed a single text.

        Args:
            text: Text to embed.

        Returns:
            Embedding vector as list of floats.
        """
        async with self._lock:
            # Run in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._embed_sync, text)

    def _embed_sync(self, text: str) -> list[float]:
        """Synchronous embedding."""
        self._ensure_model()
        embedding = self._model.encode(
            text,
            normalize_embeddings=self._config.normalize_embeddings,
            show_progress_bar=False,
        )
        return embedding.tolist()

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts (more efficient).

        Uses batching for better GPU utilization.

        Args:
            texts: List of texts to embed.

        Returns:
            List of embedding vectors.
        """
        async with self._lock:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._embed_batch_sync, texts)

    def _embed_batch_sync(self, texts: list[str]) -> list[list[float]]:
        """Synchronous batch embedding."""
        self._ensure_model()
        embeddings = self._model.encode(
            texts,
            normalize_embeddings=self._config.normalize_embeddings,
            batch_size=self._config.batch_size,
            show_progress_bar=self._config.show_progress_bar,
        )
        return [emb.tolist() for emb in embeddings]

    @property
    def dimension(self) -> int:
        """Embedding dimension.

        Returns the dimensionality of the embeddings produced by this model.
        """
        self._ensure_model()
        return self._dimension

    @property
    def model_name(self) -> str:
        """Model name."""
        return self._config.model_name

    def __repr__(self) -> str:
        return (
            f"SentenceTransformerEmbedding("
            f"model='{self._config.model_name}', "
            f"device={self._config.device}"
            f")"
        )
