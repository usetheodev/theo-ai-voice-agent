"""
Embeddings module - Geracao de embeddings de texto
"""

from .embedding_provider import EmbeddingProvider, EmbeddingResult
from .config import EMBEDDING_CONFIG, ENRICHMENT_CONFIG, EMBEDDING_DIMS

__all__ = [
    "EmbeddingProvider",
    "EmbeddingResult",
    "EMBEDDING_CONFIG",
    "ENRICHMENT_CONFIG",
    "EMBEDDING_DIMS",
]
