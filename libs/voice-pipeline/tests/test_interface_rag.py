"""Tests for RAG (Retrieval-Augmented Generation) interface.

Tests cover:
- Document dataclass
- RetrievalResult dataclass
- EmbeddingInterface
- VectorStoreInterface
- RAGInterface
- SimpleRAG implementation
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from voice_pipeline.interfaces.rag import (
    Document,
    RetrievalResult,
    EmbeddingInterface,
    VectorStoreInterface,
    RAGInterface,
    SimpleRAG,
)


# =============================================================================
# Document Tests
# =============================================================================


class TestDocument:
    """Tests for Document dataclass."""

    def test_create_simple_document(self):
        """Test creating a simple document."""
        doc = Document(content="Hello world")

        assert doc.content == "Hello world"
        assert doc.metadata == {}
        assert doc.id is None
        assert doc.embedding is None

    def test_create_document_with_metadata(self):
        """Test creating a document with metadata."""
        doc = Document(
            content="Voice Pipeline is a framework.",
            metadata={"source": "docs/intro.md", "title": "Introduction"},
        )

        assert doc.content == "Voice Pipeline is a framework."
        assert doc.metadata["source"] == "docs/intro.md"
        assert doc.metadata["title"] == "Introduction"

    def test_create_document_with_id(self):
        """Test creating a document with ID."""
        doc = Document(
            content="Test content",
            id="doc-123",
        )

        assert doc.id == "doc-123"

    def test_create_document_with_embedding(self):
        """Test creating a document with pre-computed embedding."""
        embedding = [0.1, 0.2, 0.3, 0.4]
        doc = Document(
            content="Test content",
            embedding=embedding,
        )

        assert doc.embedding == [0.1, 0.2, 0.3, 0.4]

    def test_document_repr_short_content(self):
        """Test document repr with short content."""
        doc = Document(content="Short text")
        repr_str = repr(doc)

        assert "Document" in repr_str
        assert "Short text" in repr_str

    def test_document_repr_long_content(self):
        """Test document repr truncates long content."""
        long_content = "A" * 100
        doc = Document(content=long_content)
        repr_str = repr(doc)

        assert "..." in repr_str
        assert len(repr_str) < 100  # Truncated


# =============================================================================
# RetrievalResult Tests
# =============================================================================


class TestRetrievalResult:
    """Tests for RetrievalResult dataclass."""

    def test_create_retrieval_result(self):
        """Test creating a retrieval result."""
        doc = Document(content="Test content")
        result = RetrievalResult(
            document=doc,
            score=0.95,
            rank=1,
        )

        assert result.document == doc
        assert result.score == 0.95
        assert result.rank == 1

    def test_retrieval_result_default_rank(self):
        """Test default rank is 0."""
        doc = Document(content="Test")
        result = RetrievalResult(document=doc, score=0.8)

        assert result.rank == 0

    def test_retrieval_result_repr(self):
        """Test retrieval result repr."""
        doc = Document(content="Test")
        result = RetrievalResult(document=doc, score=0.95, rank=1)
        repr_str = repr(result)

        assert "RetrievalResult" in repr_str
        assert "0.95" in repr_str
        assert "rank=1" in repr_str


# =============================================================================
# EmbeddingInterface Tests
# =============================================================================


class MockEmbedding(EmbeddingInterface):
    """Mock embedding for testing."""

    def __init__(self, dim: int = 384):
        self._dim = dim

    async def embed(self, text: str) -> list[float]:
        # Simple hash-based mock embedding
        return [float(hash(text) % 100) / 100.0] * self._dim

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed(text) for text in texts]

    @property
    def dimension(self) -> int:
        return self._dim


class TestEmbeddingInterface:
    """Tests for EmbeddingInterface."""

    @pytest.mark.asyncio
    async def test_embed_single_text(self):
        """Test embedding a single text."""
        embedding = MockEmbedding(dim=4)
        result = await embedding.embed("Hello world")

        assert isinstance(result, list)
        assert len(result) == 4
        assert all(isinstance(v, float) for v in result)

    @pytest.mark.asyncio
    async def test_embed_batch(self):
        """Test batch embedding."""
        embedding = MockEmbedding(dim=4)
        texts = ["Hello", "World", "Test"]
        results = await embedding.embed_batch(texts)

        assert len(results) == 3
        assert all(len(r) == 4 for r in results)

    def test_dimension_property(self):
        """Test dimension property."""
        embedding = MockEmbedding(dim=768)
        assert embedding.dimension == 768


# =============================================================================
# VectorStoreInterface Tests
# =============================================================================


class MockVectorStore(VectorStoreInterface):
    """Mock vector store for testing."""

    def __init__(self):
        self._documents: dict[str, Document] = {}
        self._embeddings: dict[str, list[float]] = {}
        self._next_id = 0

    async def add_documents(
        self,
        documents: list[Document],
        embeddings: list[list[float]] | None = None,
    ) -> list[str]:
        ids = []
        for i, doc in enumerate(documents):
            doc_id = doc.id or f"doc-{self._next_id}"
            self._next_id += 1
            self._documents[doc_id] = doc
            if embeddings:
                self._embeddings[doc_id] = embeddings[i]
            ids.append(doc_id)
        return ids

    async def search(
        self,
        query_embedding: list[float],
        k: int = 5,
        filter: dict | None = None,
    ) -> list[RetrievalResult]:
        # Return all documents with mock scores
        results = []
        for i, (doc_id, doc) in enumerate(list(self._documents.items())[:k]):
            results.append(RetrievalResult(
                document=doc,
                score=1.0 - (i * 0.1),
                rank=i + 1,
            ))
        return results

    async def delete(self, ids: list[str]) -> None:
        for doc_id in ids:
            self._documents.pop(doc_id, None)
            self._embeddings.pop(doc_id, None)

    async def clear(self) -> None:
        self._documents.clear()
        self._embeddings.clear()

    @property
    def count(self) -> int:
        return len(self._documents)


class TestVectorStoreInterface:
    """Tests for VectorStoreInterface."""

    @pytest.mark.asyncio
    async def test_add_documents(self):
        """Test adding documents."""
        store = MockVectorStore()
        docs = [
            Document(content="Doc 1"),
            Document(content="Doc 2"),
        ]

        ids = await store.add_documents(docs)

        assert len(ids) == 2
        assert store.count == 2

    @pytest.mark.asyncio
    async def test_add_documents_with_embeddings(self):
        """Test adding documents with embeddings."""
        store = MockVectorStore()
        docs = [Document(content="Doc 1")]
        embeddings = [[0.1, 0.2, 0.3]]

        ids = await store.add_documents(docs, embeddings=embeddings)

        assert len(ids) == 1
        assert store._embeddings[ids[0]] == [0.1, 0.2, 0.3]

    @pytest.mark.asyncio
    async def test_search(self):
        """Test searching documents."""
        store = MockVectorStore()
        docs = [
            Document(content="Doc 1"),
            Document(content="Doc 2"),
            Document(content="Doc 3"),
        ]
        await store.add_documents(docs)

        results = await store.search([0.1, 0.2], k=2)

        assert len(results) == 2
        assert all(isinstance(r, RetrievalResult) for r in results)

    @pytest.mark.asyncio
    async def test_delete(self):
        """Test deleting documents."""
        store = MockVectorStore()
        docs = [Document(content="Doc 1"), Document(content="Doc 2")]
        ids = await store.add_documents(docs)

        await store.delete([ids[0]])

        assert store.count == 1

    @pytest.mark.asyncio
    async def test_clear(self):
        """Test clearing all documents."""
        store = MockVectorStore()
        docs = [Document(content="Doc 1"), Document(content="Doc 2")]
        await store.add_documents(docs)

        await store.clear()

        assert store.count == 0

    def test_count_property(self):
        """Test count property."""
        store = MockVectorStore()
        assert store.count == 0


# =============================================================================
# RAGInterface Tests
# =============================================================================


class TestRAGInterface:
    """Tests for RAGInterface."""

    def test_build_rag_prompt(self):
        """Test building RAG prompt."""
        # Create a concrete implementation for testing
        store = MockVectorStore()
        embedding = MockEmbedding()
        rag = SimpleRAG(store, embedding)

        context = "[1] Voice Pipeline is a framework.\n(Source: docs/intro.md)"
        prompt = rag.build_rag_prompt(
            query="What is Voice Pipeline?",
            context=context,
        )

        assert "Voice Pipeline is a framework" in prompt
        assert "What is Voice Pipeline?" in prompt
        assert "Context:" in prompt

    def test_build_rag_prompt_with_system_prompt(self):
        """Test building RAG prompt with system prompt."""
        store = MockVectorStore()
        embedding = MockEmbedding()
        rag = SimpleRAG(store, embedding)

        context = "Some context"
        prompt = rag.build_rag_prompt(
            query="Question?",
            context=context,
            system_prompt="You are a helpful assistant.\n\n",
        )

        assert "You are a helpful assistant." in prompt
        assert "Some context" in prompt


# =============================================================================
# SimpleRAG Tests
# =============================================================================


class TestSimpleRAG:
    """Tests for SimpleRAG implementation."""

    @pytest.mark.asyncio
    async def test_add_documents(self):
        """Test adding documents to SimpleRAG."""
        store = MockVectorStore()
        embedding = MockEmbedding(dim=4)
        rag = SimpleRAG(store, embedding)

        docs = [
            Document(content="Doc 1"),
            Document(content="Doc 2"),
        ]
        ids = await rag.add_documents(docs)

        assert len(ids) == 2
        assert rag.count == 2

    @pytest.mark.asyncio
    async def test_retrieve(self):
        """Test retrieving documents."""
        store = MockVectorStore()
        embedding = MockEmbedding(dim=4)
        rag = SimpleRAG(store, embedding)

        docs = [
            Document(content="Voice Pipeline helps build voice agents."),
            Document(content="It supports streaming ASR."),
        ]
        await rag.add_documents(docs)

        results = await rag.retrieve("What is Voice Pipeline?", k=2)

        assert len(results) == 2
        assert all(isinstance(r, RetrievalResult) for r in results)

    @pytest.mark.asyncio
    async def test_query_returns_formatted_context(self):
        """Test query returns formatted context."""
        store = MockVectorStore()
        embedding = MockEmbedding(dim=4)
        rag = SimpleRAG(store, embedding)

        docs = [
            Document(
                content="Voice Pipeline is a framework.",
                metadata={"source": "docs/intro.md"},
            ),
        ]
        await rag.add_documents(docs)

        context, results = await rag.query("What is Voice Pipeline?")

        assert "[1]" in context
        assert "Voice Pipeline is a framework." in context
        assert "(Source: docs/intro.md)" in context
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_query_with_unknown_source(self):
        """Test query with document without source metadata."""
        store = MockVectorStore()
        embedding = MockEmbedding(dim=4)
        rag = SimpleRAG(store, embedding)

        docs = [Document(content="No source document.")]
        await rag.add_documents(docs)

        context, results = await rag.query("Question?")

        assert "(Source: unknown)" in context

    def test_count_property(self):
        """Test count property delegates to vector store."""
        store = MockVectorStore()
        embedding = MockEmbedding()
        rag = SimpleRAG(store, embedding)

        assert rag.count == 0


# =============================================================================
# Import Tests
# =============================================================================


class TestRAGImports:
    """Tests for RAG imports from interfaces module."""

    def test_import_from_interfaces(self):
        """Test importing RAG types from interfaces."""
        from voice_pipeline.interfaces import (
            Document,
            RetrievalResult,
            EmbeddingInterface,
            VectorStoreInterface,
            RAGInterface,
            SimpleRAG,
        )

        assert Document is not None
        assert RetrievalResult is not None
        assert EmbeddingInterface is not None
        assert VectorStoreInterface is not None
        assert RAGInterface is not None
        assert SimpleRAG is not None

    def test_document_in_all(self):
        """Test Document is in __all__."""
        from voice_pipeline.interfaces import __all__

        assert "Document" in __all__
        assert "RetrievalResult" in __all__
        assert "RAGInterface" in __all__


# =============================================================================
# Edge Cases
# =============================================================================


class TestRAGEdgeCases:
    """Tests for edge cases."""

    def test_document_with_empty_content(self):
        """Test document with empty content."""
        doc = Document(content="")
        assert doc.content == ""

    def test_document_with_special_characters(self):
        """Test document with special characters."""
        doc = Document(content="Olá, como você está? 你好！")
        assert doc.content == "Olá, como você está? 你好！"

    @pytest.mark.asyncio
    async def test_retrieve_from_empty_store(self):
        """Test retrieving from empty store."""
        store = MockVectorStore()
        embedding = MockEmbedding()
        rag = SimpleRAG(store, embedding)

        results = await rag.retrieve("Query", k=5)

        assert results == []

    @pytest.mark.asyncio
    async def test_query_empty_store(self):
        """Test query on empty store."""
        store = MockVectorStore()
        embedding = MockEmbedding()
        rag = SimpleRAG(store, embedding)

        context, results = await rag.query("Query")

        assert context == ""
        assert results == []
