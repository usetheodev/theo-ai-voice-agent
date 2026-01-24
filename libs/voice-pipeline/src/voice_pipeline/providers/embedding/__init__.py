"""Embedding providers for RAG.

Provides text embedding models for semantic search.
"""

from .sentence_transformers import (
    SentenceTransformerEmbedding,
    SentenceTransformerEmbeddingConfig,
)

__all__ = [
    "SentenceTransformerEmbedding",
    "SentenceTransformerEmbeddingConfig",
]
