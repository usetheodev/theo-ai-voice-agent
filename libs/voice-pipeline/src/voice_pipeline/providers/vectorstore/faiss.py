"""FAISS Vector Store provider.

Provides local vector storage and similarity search using FAISS
(Facebook AI Similarity Search).

FAISS is highly optimized for:
- Fast similarity search on CPU and GPU
- Memory-efficient storage
- Billion-scale indexes

Example:
    >>> from voice_pipeline.providers.vectorstore import FAISSVectorStore
    >>> from voice_pipeline.providers.embedding import SentenceTransformerEmbedding
    >>> from voice_pipeline.interfaces.rag import Document, SimpleRAG
    >>>
    >>> # Create components
    >>> embedding = SentenceTransformerEmbedding()
    >>> store = FAISSVectorStore(dimension=embedding.dimension)
    >>>
    >>> # Create RAG
    >>> rag = SimpleRAG(store, embedding)
    >>>
    >>> # Add documents
    >>> await rag.add_documents([
    ...     Document("Voice Pipeline is a framework for voice agents."),
    ...     Document("It supports streaming ASR with Deepgram."),
    ... ])
    >>>
    >>> # Search
    >>> results = await rag.retrieve("What is Voice Pipeline?")
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np
from numpy.typing import NDArray

from voice_pipeline.interfaces.rag import (
    Document,
    RetrievalResult,
    VectorStoreInterface,
)


@dataclass
class FAISSVectorStoreConfig:
    """Configuration for FAISS vector store.

    Attributes:
        dimension: Embedding dimension (required).
        index_type: FAISS index type:
            - "flat": Exact search (default, best for <10K docs)
            - "ivf": Inverted file index (faster for >10K docs)
            - "hnsw": Hierarchical navigable small world (good balance)
        nlist: Number of clusters for IVF index.
        nprobe: Number of clusters to search for IVF.
        metric: Distance metric ("l2" or "cosine").
        normalize: Whether to normalize vectors before indexing.

    Example:
        >>> config = FAISSVectorStoreConfig(
        ...     dimension=384,
        ...     index_type="ivf",
        ...     nlist=100,
        ... )
    """

    dimension: int = 384
    """Embedding dimension."""

    index_type: str = "flat"
    """FAISS index type: 'flat', 'ivf', or 'hnsw'."""

    nlist: int = 100
    """Number of clusters for IVF index."""

    nprobe: int = 10
    """Number of clusters to search for IVF."""

    m: int = 32
    """HNSW M parameter (connections per node)."""

    ef_construction: int = 200
    """HNSW ef_construction parameter."""

    ef_search: int = 50
    """HNSW ef_search parameter."""

    metric: str = "cosine"
    """Distance metric: 'l2' or 'cosine'."""

    normalize: bool = True
    """Whether to normalize vectors before indexing."""


class FAISSVectorStore(VectorStoreInterface):
    """FAISS-based vector store for similarity search.

    Uses Facebook AI Similarity Search (FAISS) for efficient
    vector similarity search. Runs entirely locally.

    Example:
        >>> store = FAISSVectorStore(dimension=384)
        >>>
        >>> # Add documents with embeddings
        >>> docs = [Document(content="Hello world", id="doc1")]
        >>> embeddings = [[0.1, 0.2, ...]]  # 384-dim vectors
        >>> await store.add_documents(docs, embeddings)
        >>>
        >>> # Search
        >>> query_embedding = [0.15, 0.25, ...]
        >>> results = await store.search(query_embedding, k=5)
    """

    def __init__(
        self,
        config: Optional[FAISSVectorStoreConfig] = None,
        *,
        dimension: Optional[int] = None,
        index_type: Optional[str] = None,
        metric: Optional[str] = None,
    ):
        """Initialize FAISS vector store.

        Args:
            config: Configuration object (optional).
            dimension: Embedding dimension shortcut.
            index_type: Index type shortcut.
            metric: Distance metric shortcut.
        """
        self._config = config or FAISSVectorStoreConfig()

        # Apply shortcuts
        if dimension is not None:
            self._config.dimension = dimension
        if index_type is not None:
            self._config.index_type = index_type
        if metric is not None:
            self._config.metric = metric

        # Storage
        self._documents: dict[str, Document] = {}
        self._id_to_idx: dict[str, int] = {}
        self._idx_to_id: dict[int, str] = {}
        self._next_idx = 0

        # FAISS index (lazy loaded)
        self._index = None
        self._lock = asyncio.Lock()

    def _ensure_index(self):
        """Lazily create FAISS index."""
        if self._index is not None:
            return

        try:
            import faiss
        except ImportError as e:
            raise ImportError(
                "faiss-cpu is required for FAISSVectorStore. "
                "Install it with: pip install faiss-cpu"
            ) from e

        dim = self._config.dimension
        index_type = self._config.index_type.lower()

        # Create base index
        if self._config.metric == "cosine":
            # For cosine similarity, use inner product with normalized vectors
            if index_type == "flat":
                self._index = faiss.IndexFlatIP(dim)
            elif index_type == "ivf":
                quantizer = faiss.IndexFlatIP(dim)
                self._index = faiss.IndexIVFFlat(
                    quantizer, dim, self._config.nlist, faiss.METRIC_INNER_PRODUCT
                )
            elif index_type == "hnsw":
                self._index = faiss.IndexHNSWFlat(dim, self._config.m, faiss.METRIC_INNER_PRODUCT)
                self._index.hnsw.efConstruction = self._config.ef_construction
                self._index.hnsw.efSearch = self._config.ef_search
            else:
                raise ValueError(f"Unknown index type: {index_type}")
        else:  # L2
            if index_type == "flat":
                self._index = faiss.IndexFlatL2(dim)
            elif index_type == "ivf":
                quantizer = faiss.IndexFlatL2(dim)
                self._index = faiss.IndexIVFFlat(
                    quantizer, dim, self._config.nlist, faiss.METRIC_L2
                )
            elif index_type == "hnsw":
                self._index = faiss.IndexHNSWFlat(dim, self._config.m)
                self._index.hnsw.efConstruction = self._config.ef_construction
                self._index.hnsw.efSearch = self._config.ef_search
            else:
                raise ValueError(f"Unknown index type: {index_type}")

    def _normalize_vectors(self, vectors: NDArray[np.float32]) -> NDArray[np.float32]:
        """L2 normalize vectors."""
        if not self._config.normalize:
            return vectors
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)  # Avoid division by zero
        return vectors / norms

    async def add_documents(
        self,
        documents: list[Document],
        embeddings: Optional[list[list[float]]] = None,
    ) -> list[str]:
        """Add documents to the vector store.

        Args:
            documents: Documents to add.
            embeddings: Pre-computed embeddings (required).

        Returns:
            List of document IDs.

        Raises:
            ValueError: If embeddings are not provided.
        """
        if embeddings is None:
            raise ValueError(
                "Embeddings must be provided. Use SimpleRAG for automatic embedding."
            )

        async with self._lock:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None, self._add_documents_sync, documents, embeddings
            )

    def _add_documents_sync(
        self,
        documents: list[Document],
        embeddings: list[list[float]],
    ) -> list[str]:
        """Synchronous document addition."""
        self._ensure_index()

        ids = []
        vectors = []

        for doc, emb in zip(documents, embeddings):
            # Generate ID if not provided
            doc_id = doc.id or str(uuid.uuid4())

            # Store document
            self._documents[doc_id] = doc
            self._id_to_idx[doc_id] = self._next_idx
            self._idx_to_id[self._next_idx] = doc_id
            self._next_idx += 1

            ids.append(doc_id)
            vectors.append(emb)

        # Convert to numpy and normalize
        vectors_np = np.array(vectors, dtype=np.float32)
        vectors_np = self._normalize_vectors(vectors_np)

        # Train IVF index if needed
        if hasattr(self._index, 'is_trained') and not self._index.is_trained:
            self._index.train(vectors_np)

        # Add to index
        self._index.add(vectors_np)

        return ids

    async def search(
        self,
        query_embedding: list[float],
        k: int = 5,
        filter: Optional[dict[str, Any]] = None,
    ) -> list[RetrievalResult]:
        """Search for similar documents.

        Args:
            query_embedding: Query embedding vector.
            k: Number of results to return.
            filter: Optional metadata filter (not yet implemented).

        Returns:
            List of retrieval results sorted by relevance.
        """
        async with self._lock:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None, self._search_sync, query_embedding, k, filter
            )

    def _search_sync(
        self,
        query_embedding: list[float],
        k: int,
        filter: Optional[dict[str, Any]],
    ) -> list[RetrievalResult]:
        """Synchronous search."""
        self._ensure_index()

        if self._index.ntotal == 0:
            return []

        # Prepare query
        query = np.array([query_embedding], dtype=np.float32)
        query = self._normalize_vectors(query)

        # Set nprobe for IVF
        if hasattr(self._index, 'nprobe'):
            self._index.nprobe = self._config.nprobe

        # Search
        k = min(k, self._index.ntotal)
        distances, indices = self._index.search(query, k)

        # Convert to results
        results = []
        for rank, (idx, distance) in enumerate(zip(indices[0], distances[0]), 1):
            if idx < 0:  # FAISS returns -1 for missing results
                continue

            doc_id = self._idx_to_id.get(int(idx))
            if doc_id is None:
                continue

            doc = self._documents.get(doc_id)
            if doc is None:
                continue

            # Apply filter if provided
            if filter is not None:
                if not self._matches_filter(doc, filter):
                    continue

            # Convert distance to score
            # For inner product (cosine), higher is better
            # For L2, lower is better
            if self._config.metric == "cosine":
                score = float(distance)  # Already similarity score
            else:
                score = 1.0 / (1.0 + float(distance))  # Convert L2 to similarity

            results.append(RetrievalResult(
                document=doc,
                score=score,
                rank=rank,
            ))

        return results

    def _matches_filter(self, doc: Document, filter: dict[str, Any]) -> bool:
        """Check if document matches filter."""
        for key, value in filter.items():
            if doc.metadata.get(key) != value:
                return False
        return True

    async def delete(self, ids: list[str]) -> None:
        """Delete documents by ID.

        Note: FAISS doesn't support efficient deletion. This marks
        documents as deleted but doesn't free index memory.
        For full cleanup, rebuild the index.

        Args:
            ids: Document IDs to delete.
        """
        async with self._lock:
            for doc_id in ids:
                self._documents.pop(doc_id, None)
                idx = self._id_to_idx.pop(doc_id, None)
                if idx is not None:
                    self._idx_to_id.pop(idx, None)

    async def clear(self) -> None:
        """Clear all documents from the store."""
        async with self._lock:
            self._documents.clear()
            self._id_to_idx.clear()
            self._idx_to_id.clear()
            self._next_idx = 0
            self._index = None  # Reset index

    @property
    def count(self) -> int:
        """Number of documents in the store."""
        return len(self._documents)

    async def save(self, path: str | Path) -> None:
        """Save the vector store to disk.

        Args:
            path: Directory to save to.
        """
        import json

        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)

        async with self._lock:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._save_sync, path)

    def _save_sync(self, path: Path) -> None:
        """Synchronous save."""
        import faiss
        import pickle

        # Save FAISS index
        if self._index is not None:
            faiss.write_index(self._index, str(path / "index.faiss"))

        # Save metadata
        metadata = {
            "documents": {
                doc_id: {
                    "content": doc.content,
                    "metadata": doc.metadata,
                    "id": doc.id,
                }
                for doc_id, doc in self._documents.items()
            },
            "id_to_idx": self._id_to_idx,
            "idx_to_id": {str(k): v for k, v in self._idx_to_id.items()},
            "next_idx": self._next_idx,
            "config": {
                "dimension": self._config.dimension,
                "index_type": self._config.index_type,
                "metric": self._config.metric,
                "normalize": self._config.normalize,
            },
        }

        with open(path / "metadata.json", "w") as f:
            import json
            json.dump(metadata, f)

    @classmethod
    async def load(cls, path: str | Path) -> "FAISSVectorStore":
        """Load a vector store from disk.

        Args:
            path: Directory to load from.

        Returns:
            Loaded vector store.
        """
        path = Path(path)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, cls._load_sync, path)

    @classmethod
    def _load_sync(cls, path: Path) -> "FAISSVectorStore":
        """Synchronous load."""
        import faiss
        import json

        # Load metadata
        with open(path / "metadata.json") as f:
            metadata = json.load(f)

        # Create config
        config_data = metadata["config"]
        config = FAISSVectorStoreConfig(
            dimension=config_data["dimension"],
            index_type=config_data["index_type"],
            metric=config_data["metric"],
            normalize=config_data["normalize"],
        )

        # Create store
        store = cls(config=config)

        # Load FAISS index
        index_path = path / "index.faiss"
        if index_path.exists():
            store._index = faiss.read_index(str(index_path))

        # Load documents
        for doc_id, doc_data in metadata["documents"].items():
            store._documents[doc_id] = Document(
                content=doc_data["content"],
                metadata=doc_data["metadata"],
                id=doc_data["id"],
            )

        store._id_to_idx = metadata["id_to_idx"]
        store._idx_to_id = {int(k): v for k, v in metadata["idx_to_id"].items()}
        store._next_idx = metadata["next_idx"]

        return store

    def __repr__(self) -> str:
        return (
            f"FAISSVectorStore("
            f"dimension={self._config.dimension}, "
            f"index_type='{self._config.index_type}', "
            f"count={self.count}"
            f")"
        )
