"""Tests for FAISS Vector Store provider.

Tests cover:
- Configuration
- Document addition
- Search functionality
- Delete and clear
- Save and load
- Different index types
"""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from voice_pipeline.interfaces.rag import Document, RetrievalResult


# =============================================================================
# Skip if FAISS not installed
# =============================================================================


faiss = pytest.importorskip("faiss", reason="faiss-cpu not installed")


from voice_pipeline.providers.vectorstore.faiss import (
    FAISSVectorStore,
    FAISSVectorStoreConfig,
)


# =============================================================================
# Configuration Tests
# =============================================================================


class TestFAISSVectorStoreConfig:
    """Tests for FAISSVectorStoreConfig."""

    def test_default_values(self):
        """Test default configuration values."""
        config = FAISSVectorStoreConfig()

        assert config.dimension == 384
        assert config.index_type == "flat"
        assert config.metric == "cosine"
        assert config.normalize is True

    def test_custom_values(self):
        """Test custom configuration values."""
        config = FAISSVectorStoreConfig(
            dimension=768,
            index_type="ivf",
            nlist=200,
            metric="l2",
        )

        assert config.dimension == 768
        assert config.index_type == "ivf"
        assert config.nlist == 200
        assert config.metric == "l2"


# =============================================================================
# Initialization Tests
# =============================================================================


class TestFAISSVectorStoreInit:
    """Tests for FAISSVectorStore initialization."""

    def test_default_initialization(self):
        """Test default initialization."""
        store = FAISSVectorStore()

        assert store._config.dimension == 384
        assert store.count == 0

    def test_initialization_with_config(self):
        """Test initialization with config."""
        config = FAISSVectorStoreConfig(dimension=512)
        store = FAISSVectorStore(config=config)

        assert store._config.dimension == 512

    def test_initialization_with_shortcuts(self):
        """Test initialization with shortcuts."""
        store = FAISSVectorStore(
            dimension=256,
            index_type="hnsw",
            metric="l2",
        )

        assert store._config.dimension == 256
        assert store._config.index_type == "hnsw"
        assert store._config.metric == "l2"

    def test_repr(self):
        """Test string representation."""
        store = FAISSVectorStore(dimension=384)
        repr_str = repr(store)

        assert "FAISSVectorStore" in repr_str
        assert "384" in repr_str
        assert "flat" in repr_str


# =============================================================================
# Document Addition Tests
# =============================================================================


class TestFAISSAddDocuments:
    """Tests for adding documents."""

    @pytest.mark.asyncio
    async def test_add_single_document(self):
        """Test adding a single document."""
        store = FAISSVectorStore(dimension=4)
        docs = [Document(content="Test document")]
        embeddings = [[0.1, 0.2, 0.3, 0.4]]

        ids = await store.add_documents(docs, embeddings=embeddings)

        assert len(ids) == 1
        assert store.count == 1

    @pytest.mark.asyncio
    async def test_add_multiple_documents(self):
        """Test adding multiple documents."""
        store = FAISSVectorStore(dimension=4)
        docs = [
            Document(content="Doc 1"),
            Document(content="Doc 2"),
            Document(content="Doc 3"),
        ]
        embeddings = [
            [0.1, 0.2, 0.3, 0.4],
            [0.5, 0.6, 0.7, 0.8],
            [0.9, 0.1, 0.2, 0.3],
        ]

        ids = await store.add_documents(docs, embeddings=embeddings)

        assert len(ids) == 3
        assert store.count == 3

    @pytest.mark.asyncio
    async def test_add_document_with_custom_id(self):
        """Test adding document with custom ID."""
        store = FAISSVectorStore(dimension=4)
        docs = [Document(content="Test", id="custom-id")]
        embeddings = [[0.1, 0.2, 0.3, 0.4]]

        ids = await store.add_documents(docs, embeddings=embeddings)

        assert ids[0] == "custom-id"

    @pytest.mark.asyncio
    async def test_add_document_requires_embeddings(self):
        """Test that embeddings are required."""
        store = FAISSVectorStore(dimension=4)
        docs = [Document(content="Test")]

        with pytest.raises(ValueError, match="Embeddings must be provided"):
            await store.add_documents(docs)


# =============================================================================
# Search Tests
# =============================================================================


class TestFAISSSearch:
    """Tests for search functionality."""

    @pytest.mark.asyncio
    async def test_search_returns_results(self):
        """Test that search returns results."""
        store = FAISSVectorStore(dimension=4)
        docs = [
            Document(content="Voice Pipeline is great"),
            Document(content="FAISS is fast"),
        ]
        embeddings = [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
        ]
        await store.add_documents(docs, embeddings=embeddings)

        # Query similar to first document
        results = await store.search([0.9, 0.1, 0.0, 0.0], k=2)

        assert len(results) == 2
        assert all(isinstance(r, RetrievalResult) for r in results)

    @pytest.mark.asyncio
    async def test_search_returns_most_similar_first(self):
        """Test that most similar results come first."""
        store = FAISSVectorStore(dimension=4)
        docs = [
            Document(content="Similar", id="similar"),
            Document(content="Different", id="different"),
        ]
        embeddings = [
            [1.0, 0.0, 0.0, 0.0],  # Similar to query
            [0.0, 0.0, 0.0, 1.0],  # Different from query
        ]
        await store.add_documents(docs, embeddings=embeddings)

        results = await store.search([1.0, 0.0, 0.0, 0.0], k=2)

        assert results[0].document.id == "similar"

    @pytest.mark.asyncio
    async def test_search_respects_k(self):
        """Test that search respects k parameter."""
        store = FAISSVectorStore(dimension=4)
        docs = [Document(content=f"Doc {i}") for i in range(10)]
        embeddings = [[0.1 * i, 0.2, 0.3, 0.4] for i in range(10)]
        await store.add_documents(docs, embeddings=embeddings)

        results = await store.search([0.5, 0.2, 0.3, 0.4], k=3)

        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_search_empty_store(self):
        """Test searching empty store."""
        store = FAISSVectorStore(dimension=4)

        results = await store.search([0.1, 0.2, 0.3, 0.4], k=5)

        assert results == []

    @pytest.mark.asyncio
    async def test_search_with_metadata_filter(self):
        """Test search with metadata filter."""
        store = FAISSVectorStore(dimension=4)
        docs = [
            Document(content="Doc 1", metadata={"type": "article"}),
            Document(content="Doc 2", metadata={"type": "book"}),
        ]
        embeddings = [
            [1.0, 0.0, 0.0, 0.0],
            [0.9, 0.1, 0.0, 0.0],
        ]
        await store.add_documents(docs, embeddings=embeddings)

        results = await store.search(
            [1.0, 0.0, 0.0, 0.0],
            k=5,
            filter={"type": "book"},
        )

        assert len(results) == 1
        assert results[0].document.metadata["type"] == "book"


# =============================================================================
# Delete and Clear Tests
# =============================================================================


class TestFAISSDelete:
    """Tests for delete and clear operations."""

    @pytest.mark.asyncio
    async def test_delete_document(self):
        """Test deleting a document."""
        store = FAISSVectorStore(dimension=4)
        docs = [Document(content="Test", id="to-delete")]
        embeddings = [[0.1, 0.2, 0.3, 0.4]]
        await store.add_documents(docs, embeddings=embeddings)

        await store.delete(["to-delete"])

        assert store.count == 0

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self):
        """Test deleting nonexistent document (should not error)."""
        store = FAISSVectorStore(dimension=4)

        await store.delete(["nonexistent"])  # Should not raise

    @pytest.mark.asyncio
    async def test_clear(self):
        """Test clearing all documents."""
        store = FAISSVectorStore(dimension=4)
        docs = [Document(content=f"Doc {i}") for i in range(5)]
        embeddings = [[0.1, 0.2, 0.3, 0.4] for _ in range(5)]
        await store.add_documents(docs, embeddings=embeddings)

        await store.clear()

        assert store.count == 0


# =============================================================================
# Persistence Tests
# =============================================================================


class TestFAISSPersistence:
    """Tests for save/load functionality."""

    @pytest.mark.asyncio
    async def test_save_and_load(self):
        """Test saving and loading store."""
        store = FAISSVectorStore(dimension=4)
        docs = [
            Document(content="Test doc", metadata={"key": "value"}, id="doc1"),
        ]
        embeddings = [[0.1, 0.2, 0.3, 0.4]]
        await store.add_documents(docs, embeddings=embeddings)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "store"

            # Save
            await store.save(path)

            # Load
            loaded = await FAISSVectorStore.load(path)

            assert loaded.count == 1
            assert "doc1" in loaded._documents

    @pytest.mark.asyncio
    async def test_loaded_store_searchable(self):
        """Test that loaded store is searchable."""
        store = FAISSVectorStore(dimension=4)
        docs = [Document(content="Searchable", id="search-me")]
        embeddings = [[1.0, 0.0, 0.0, 0.0]]
        await store.add_documents(docs, embeddings=embeddings)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "store"
            await store.save(path)
            loaded = await FAISSVectorStore.load(path)

            results = await loaded.search([1.0, 0.0, 0.0, 0.0], k=1)

            assert len(results) == 1
            assert results[0].document.id == "search-me"


# =============================================================================
# Index Type Tests
# =============================================================================


class TestFAISSIndexTypes:
    """Tests for different index types."""

    @pytest.mark.asyncio
    async def test_flat_index(self):
        """Test flat index (exact search)."""
        store = FAISSVectorStore(dimension=4, index_type="flat")
        docs = [Document(content="Test")]
        embeddings = [[0.1, 0.2, 0.3, 0.4]]
        await store.add_documents(docs, embeddings=embeddings)

        results = await store.search([0.1, 0.2, 0.3, 0.4], k=1)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_hnsw_index(self):
        """Test HNSW index."""
        store = FAISSVectorStore(dimension=4, index_type="hnsw")
        docs = [Document(content=f"Doc {i}") for i in range(10)]
        embeddings = [[0.1 * (i + 1), 0.2, 0.3, 0.4] for i in range(10)]
        await store.add_documents(docs, embeddings=embeddings)

        results = await store.search([0.5, 0.2, 0.3, 0.4], k=3)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_ivf_index_needs_training(self):
        """Test IVF index (requires training data)."""
        config = FAISSVectorStoreConfig(
            dimension=4,
            index_type="ivf",
            nlist=2,  # Small for testing
        )
        store = FAISSVectorStore(config=config)
        # Need enough data for training
        docs = [Document(content=f"Doc {i}") for i in range(10)]
        embeddings = [[0.1 * (i + 1), 0.2, 0.3, 0.4] for i in range(10)]
        await store.add_documents(docs, embeddings=embeddings)

        results = await store.search([0.5, 0.2, 0.3, 0.4], k=3)
        assert len(results) == 3


# =============================================================================
# Metric Tests
# =============================================================================


class TestFAISSMetrics:
    """Tests for different distance metrics."""

    @pytest.mark.asyncio
    async def test_cosine_metric(self):
        """Test cosine similarity metric."""
        store = FAISSVectorStore(dimension=4, metric="cosine")
        docs = [Document(content="Test")]
        embeddings = [[1.0, 0.0, 0.0, 0.0]]
        await store.add_documents(docs, embeddings=embeddings)

        results = await store.search([1.0, 0.0, 0.0, 0.0], k=1)
        assert len(results) == 1
        # Perfect match should have high score
        assert results[0].score > 0.9

    @pytest.mark.asyncio
    async def test_l2_metric(self):
        """Test L2 distance metric."""
        config = FAISSVectorStoreConfig(dimension=4, metric="l2", normalize=False)
        store = FAISSVectorStore(config=config)
        docs = [Document(content="Test")]
        embeddings = [[1.0, 0.0, 0.0, 0.0]]
        await store.add_documents(docs, embeddings=embeddings)

        results = await store.search([1.0, 0.0, 0.0, 0.0], k=1)
        assert len(results) == 1


# =============================================================================
# Edge Cases
# =============================================================================


class TestFAISSEdgeCases:
    """Tests for edge cases."""

    @pytest.mark.asyncio
    async def test_search_k_larger_than_count(self):
        """Test searching with k larger than document count."""
        store = FAISSVectorStore(dimension=4)
        docs = [Document(content="Only one")]
        embeddings = [[0.1, 0.2, 0.3, 0.4]]
        await store.add_documents(docs, embeddings=embeddings)

        results = await store.search([0.1, 0.2, 0.3, 0.4], k=100)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_zero_vector(self):
        """Test with zero vector (should handle normalization)."""
        store = FAISSVectorStore(dimension=4)
        docs = [Document(content="Zero")]
        embeddings = [[0.0, 0.0, 0.0, 0.0]]

        # Should not raise (normalization handles zero vectors)
        ids = await store.add_documents(docs, embeddings=embeddings)
        assert len(ids) == 1

    @pytest.mark.asyncio
    async def test_concurrent_operations(self):
        """Test concurrent add and search operations."""
        store = FAISSVectorStore(dimension=4)

        async def add_and_search(i: int):
            docs = [Document(content=f"Doc {i}")]
            embeddings = [[0.1 * (i + 1), 0.2, 0.3, 0.4]]
            await store.add_documents(docs, embeddings=embeddings)
            await store.search([0.1, 0.2, 0.3, 0.4], k=1)

        # Run concurrently
        await asyncio.gather(*[add_and_search(i) for i in range(5)])

        assert store.count == 5


# =============================================================================
# Import Tests
# =============================================================================


class TestFAISSImports:
    """Tests for imports."""

    def test_import_from_providers(self):
        """Test importing from providers module."""
        from voice_pipeline.providers.vectorstore import (
            FAISSVectorStore,
            FAISSVectorStoreConfig,
        )

        assert FAISSVectorStore is not None
        assert FAISSVectorStoreConfig is not None
