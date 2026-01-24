"""RAG (Retrieval-Augmented Generation) interface.

Provides interfaces for knowledge retrieval to augment LLM responses.
This enables voice agents to answer questions using domain-specific
knowledge from documents, FAQs, or other knowledge bases.

Example:
    >>> # Create a RAG-enabled voice agent
    >>> agent = (
    ...     VoiceAgent.builder()
    ...     .asr("whisper")
    ...     .llm("ollama")
    ...     .tts("kokoro")
    ...     .rag("faiss", documents=my_docs)
    ...     .build()
    ... )
    >>>
    >>> # Agent now uses retrieved context for responses
    >>> response = await agent.ainvoke(audio_bytes)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional


@dataclass
class Document:
    """A document for RAG retrieval.

    Attributes:
        content: The text content of the document.
        metadata: Optional metadata (source, title, etc.).
        id: Optional unique identifier.
        embedding: Optional pre-computed embedding vector.

    Example:
        >>> doc = Document(
        ...     content="Voice Pipeline is a framework for building voice agents.",
        ...     metadata={"source": "docs/intro.md", "title": "Introduction"},
        ... )
    """

    content: str
    """The text content of the document."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Optional metadata about the document."""

    id: Optional[str] = None
    """Optional unique identifier."""

    embedding: Optional[list[float]] = None
    """Optional pre-computed embedding vector."""

    def __repr__(self) -> str:
        preview = self.content[:50] + "..." if len(self.content) > 50 else self.content
        return f"Document(content='{preview}', id={self.id})"


@dataclass
class RetrievalResult:
    """Result from a retrieval query.

    Attributes:
        document: The retrieved document.
        score: Relevance score (higher = more relevant).
        rank: Position in results (1-indexed).

    Example:
        >>> result = RetrievalResult(
        ...     document=doc,
        ...     score=0.95,
        ...     rank=1,
        ... )
    """

    document: Document
    """The retrieved document."""

    score: float
    """Relevance score (higher = more relevant)."""

    rank: int = 0
    """Position in results (1-indexed)."""

    def __repr__(self) -> str:
        return f"RetrievalResult(score={self.score:.3f}, rank={self.rank})"


class EmbeddingInterface(ABC):
    """Interface for text embedding providers.

    Embeddings convert text into dense vectors that capture
    semantic meaning, enabling similarity search.

    Example:
        >>> class OpenAIEmbedding(EmbeddingInterface):
        ...     async def embed(self, text: str) -> list[float]:
        ...         # Call OpenAI API
        ...         return [0.1, 0.2, ...]
        ...
        ...     async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        ...         # Batch embedding for efficiency
        ...         return [[0.1, ...], [0.2, ...]]
    """

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Embed a single text.

        Args:
            text: Text to embed.

        Returns:
            Embedding vector.
        """
        pass

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts (more efficient).

        Args:
            texts: List of texts to embed.

        Returns:
            List of embedding vectors.
        """
        pass

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Embedding dimension."""
        pass


class VectorStoreInterface(ABC):
    """Interface for vector stores.

    Vector stores index document embeddings for efficient
    similarity search. Common implementations include FAISS,
    Chroma, Pinecone, and Weaviate.

    Example:
        >>> class FAISSVectorStore(VectorStoreInterface):
        ...     async def add_documents(self, documents: list[Document]):
        ...         # Index documents
        ...         pass
        ...
        ...     async def search(self, query_embedding, k=5):
        ...         # Find similar documents
        ...         return results
    """

    @abstractmethod
    async def add_documents(
        self,
        documents: list[Document],
        embeddings: Optional[list[list[float]]] = None,
    ) -> list[str]:
        """Add documents to the vector store.

        Args:
            documents: Documents to add.
            embeddings: Optional pre-computed embeddings.

        Returns:
            List of document IDs.
        """
        pass

    @abstractmethod
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
            filter: Optional metadata filter.

        Returns:
            List of retrieval results sorted by relevance.
        """
        pass

    @abstractmethod
    async def delete(self, ids: list[str]) -> None:
        """Delete documents by ID.

        Args:
            ids: Document IDs to delete.
        """
        pass

    @abstractmethod
    async def clear(self) -> None:
        """Clear all documents from the store."""
        pass

    @property
    @abstractmethod
    def count(self) -> int:
        """Number of documents in the store."""
        pass


class RAGInterface(ABC):
    """Interface for RAG (Retrieval-Augmented Generation).

    RAG combines retrieval with LLM generation to provide
    grounded, factual responses based on a knowledge base.

    The typical flow is:
    1. User asks a question
    2. Retrieve relevant documents
    3. Include documents as context in LLM prompt
    4. LLM generates response using the context

    Example:
        >>> class SimpleRAG(RAGInterface):
        ...     def __init__(self, vector_store, embedding, llm):
        ...         self.store = vector_store
        ...         self.embedding = embedding
        ...         self.llm = llm
        ...
        ...     async def retrieve(self, query: str, k: int = 5):
        ...         query_emb = await self.embedding.embed(query)
        ...         return await self.store.search(query_emb, k=k)
        ...
        ...     async def generate(self, query: str, context: list[Document]):
        ...         prompt = self._build_prompt(query, context)
        ...         return await self.llm.ainvoke(prompt)
    """

    @abstractmethod
    async def retrieve(
        self,
        query: str,
        k: int = 5,
        filter: Optional[dict[str, Any]] = None,
    ) -> list[RetrievalResult]:
        """Retrieve relevant documents for a query.

        Args:
            query: User query text.
            k: Number of documents to retrieve.
            filter: Optional metadata filter.

        Returns:
            List of retrieval results sorted by relevance.
        """
        pass

    @abstractmethod
    async def add_documents(self, documents: list[Document]) -> list[str]:
        """Add documents to the knowledge base.

        Args:
            documents: Documents to add.

        Returns:
            List of document IDs.
        """
        pass

    async def query(
        self,
        query: str,
        k: int = 5,
    ) -> tuple[str, list[RetrievalResult]]:
        """Retrieve and format context for LLM.

        This is a convenience method that retrieves documents
        and formats them as a context string.

        Args:
            query: User query text.
            k: Number of documents to retrieve.

        Returns:
            Tuple of (formatted context, retrieval results).
        """
        results = await self.retrieve(query, k=k)

        # Format as context
        context_parts = []
        for i, result in enumerate(results, 1):
            source = result.document.metadata.get("source", "unknown")
            context_parts.append(
                f"[{i}] {result.document.content}\n(Source: {source})"
            )

        context = "\n\n".join(context_parts)
        return context, results

    def build_rag_prompt(
        self,
        query: str,
        context: str,
        system_prompt: Optional[str] = None,
    ) -> str:
        """Build a RAG-augmented prompt for the LLM.

        Args:
            query: User query.
            context: Retrieved context.
            system_prompt: Optional additional system prompt.

        Returns:
            Formatted prompt with context.
        """
        base_prompt = system_prompt or ""

        rag_instruction = """
Use the following context to answer the user's question.
If the answer is not in the context, say so honestly.

Context:
{context}

User's question: {query}

Answer:"""

        return base_prompt + rag_instruction.format(
            context=context,
            query=query,
        )


class SimpleRAG(RAGInterface):
    """Simple RAG implementation using vector store and embedding.

    This is a basic RAG implementation suitable for many use cases.
    For more advanced features, consider using dedicated RAG frameworks.

    Example:
        >>> embedding = SentenceTransformerEmbedding()
        >>> vector_store = FAISSVectorStore(embedding.dimension)
        >>> rag = SimpleRAG(vector_store, embedding)
        >>>
        >>> # Add documents
        >>> await rag.add_documents([
        ...     Document("Voice Pipeline helps build voice agents."),
        ...     Document("It supports streaming ASR with Deepgram."),
        ... ])
        >>>
        >>> # Query
        >>> results = await rag.retrieve("What is Voice Pipeline?")
    """

    def __init__(
        self,
        vector_store: VectorStoreInterface,
        embedding: EmbeddingInterface,
    ):
        """Initialize SimpleRAG.

        Args:
            vector_store: Vector store for document indexing.
            embedding: Embedding provider for text vectorization.
        """
        self.vector_store = vector_store
        self.embedding = embedding

    async def retrieve(
        self,
        query: str,
        k: int = 5,
        filter: Optional[dict[str, Any]] = None,
    ) -> list[RetrievalResult]:
        """Retrieve relevant documents."""
        # Embed query
        query_embedding = await self.embedding.embed(query)

        # Search vector store
        results = await self.vector_store.search(
            query_embedding=query_embedding,
            k=k,
            filter=filter,
        )

        return results

    async def add_documents(self, documents: list[Document]) -> list[str]:
        """Add documents to the knowledge base."""
        # Embed documents
        texts = [doc.content for doc in documents]
        embeddings = await self.embedding.embed_batch(texts)

        # Add to vector store
        ids = await self.vector_store.add_documents(
            documents=documents,
            embeddings=embeddings,
        )

        return ids

    @property
    def count(self) -> int:
        """Number of documents in the store."""
        return self.vector_store.count
