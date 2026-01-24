"""Vector store providers for RAG.

Provides vector stores for efficient similarity search.
"""

from .faiss import (
    FAISSVectorStore,
    FAISSVectorStoreConfig,
)

__all__ = [
    "FAISSVectorStore",
    "FAISSVectorStoreConfig",
]
