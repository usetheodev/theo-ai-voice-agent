"""
Embedding Provider - Gera embeddings de texto usando sentence-transformers

Usa o modelo intfloat/multilingual-e5-small (384 dims) por padrao.
"""

import logging
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import List, Optional

from .config import EMBEDDING_CONFIG, EMBEDDING_DIMS

logger = logging.getLogger("ai-transcribe.embeddings")


@dataclass
class EmbeddingResult:
    """Resultado da geracao de embedding."""
    embedding: List[float]
    model_name: str
    latency_ms: float
    dimensions: int = EMBEDDING_DIMS


class EmbeddingProvider:
    """
    Provider de embeddings usando sentence-transformers.

    Carrega o modelo no startup e usa ThreadPoolExecutor para
    nao bloquear o event loop.

    Example:
        provider = EmbeddingProvider()
        await provider.connect()

        result = await provider.embed("Ola, como posso ajudar?")
        print(f"Embedding: {len(result.embedding)} dims, {result.latency_ms}ms")
    """

    def __init__(self, config: Optional[dict] = None):
        self._config = config or EMBEDDING_CONFIG
        self._model = None
        self._model_name = self._config["model"]
        self._device = self._config["device"]
        self._connected = False
        self._executor: Optional[ThreadPoolExecutor] = None

    @property
    def is_connected(self) -> bool:
        """Verifica se esta conectado (modelo carregado)."""
        return self._connected

    @property
    def is_enabled(self) -> bool:
        """Verifica se embedding esta habilitado."""
        return self._config.get("enabled", True)

    @property
    def model_name(self) -> str:
        """Retorna nome do modelo."""
        return self._model_name

    @property
    def dimensions(self) -> int:
        """Retorna dimensoes do embedding."""
        return EMBEDDING_DIMS

    async def connect(self) -> bool:
        """
        Carrega o modelo de embeddings.

        Returns:
            True se carregou com sucesso
        """
        if not self.is_enabled:
            logger.info("Embedding provider desabilitado")
            return False

        if self._connected:
            return True

        try:
            logger.info(f"Carregando modelo de embeddings: {self._model_name}")
            start_time = time.perf_counter()

            # Carrega modelo em thread separada para nao bloquear
            self._executor = ThreadPoolExecutor(
                max_workers=self._config.get("executor_workers", 2),
                thread_name_prefix="embedding-"
            )

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(self._executor, self._load_model)

            load_time = (time.perf_counter() - start_time) * 1000
            logger.info(
                f"Modelo de embeddings carregado: {self._model_name} "
                f"(device={self._device}, dims={EMBEDDING_DIMS}, {load_time:.0f}ms)"
            )

            # Warmup com texto de teste
            await self._warmup()

            self._connected = True
            return True

        except Exception as e:
            logger.error(f"Falha ao carregar modelo de embeddings: {e}")
            self._connected = False
            return False

    def _load_model(self):
        """Carrega o modelo (executado em thread separada)."""
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(
            self._model_name,
            device=self._device,
        )

    async def _warmup(self):
        """Aquece o modelo com uma inferencia de teste."""
        try:
            logger.debug("Aquecendo modelo de embeddings...")
            start = time.perf_counter()

            # Texto de teste em portugues
            # Usa metodo interno diretamente (nao verifica _connected)
            test_text = "Ola, como posso ajudar voce hoje?"
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                self._executor,
                self._generate_embedding,
                test_text
            )

            warmup_time = (time.perf_counter() - start) * 1000
            logger.debug(f"Warmup concluido em {warmup_time:.0f}ms")

        except Exception as e:
            logger.warning(f"Erro no warmup de embeddings: {e}")

    async def disconnect(self) -> None:
        """Libera recursos do provider."""
        if self._executor:
            self._executor.shutdown(wait=False)
            self._executor = None

        self._model = None
        self._connected = False
        logger.info("Embedding provider desconectado")

    async def embed(self, text: str) -> EmbeddingResult:
        """
        Gera embedding para um texto.

        Args:
            text: Texto para gerar embedding

        Returns:
            EmbeddingResult com embedding e metadados

        Raises:
            RuntimeError: Se o modelo nao estiver carregado
            ValueError: Se o texto estiver vazio
        """
        if not self._connected:
            raise RuntimeError("Embedding provider nao conectado")

        if not text or not text.strip():
            raise ValueError("Texto vazio")

        start_time = time.perf_counter()

        try:
            # Executa em thread para nao bloquear event loop
            loop = asyncio.get_event_loop()
            embedding = await loop.run_in_executor(
                self._executor,
                self._generate_embedding,
                text
            )

            latency_ms = (time.perf_counter() - start_time) * 1000

            return EmbeddingResult(
                embedding=embedding,
                model_name=self._model_name,
                latency_ms=latency_ms,
                dimensions=len(embedding),
            )

        except Exception as e:
            logger.error(f"Erro ao gerar embedding: {e}")
            raise

    def _generate_embedding(self, text: str) -> List[float]:
        """Gera embedding (executado em thread separada)."""
        # Prefixo para modelo E5 (melhora qualidade)
        # Para queries: "query: texto"
        # Para documentos: "passage: texto"
        prefixed_text = f"passage: {text}"

        embedding = self._model.encode(
            prefixed_text,
            normalize_embeddings=self._config.get("normalize", True),
            show_progress_bar=False,
        )

        return embedding.tolist()

    async def embed_batch(self, texts: List[str]) -> List[EmbeddingResult]:
        """
        Gera embeddings para multiplos textos em batch.

        Args:
            texts: Lista de textos

        Returns:
            Lista de EmbeddingResult
        """
        if not self._connected:
            raise RuntimeError("Embedding provider nao conectado")

        if not texts:
            return []

        start_time = time.perf_counter()

        try:
            loop = asyncio.get_event_loop()
            embeddings = await loop.run_in_executor(
                self._executor,
                self._generate_batch,
                texts
            )

            total_latency_ms = (time.perf_counter() - start_time) * 1000
            per_text_latency = total_latency_ms / len(texts)

            results = []
            for embedding in embeddings:
                results.append(EmbeddingResult(
                    embedding=embedding,
                    model_name=self._model_name,
                    latency_ms=per_text_latency,
                    dimensions=len(embedding),
                ))

            logger.debug(
                f"Batch embedding: {len(texts)} textos em {total_latency_ms:.0f}ms "
                f"({per_text_latency:.1f}ms/texto)"
            )

            return results

        except Exception as e:
            logger.error(f"Erro no batch embedding: {e}")
            raise

    def _generate_batch(self, texts: List[str]) -> List[List[float]]:
        """Gera embeddings em batch (executado em thread separada)."""
        # Adiciona prefixo para E5
        prefixed_texts = [f"passage: {text}" for text in texts]

        batch_size = self._config.get("batch_size", 8)

        embeddings = self._model.encode(
            prefixed_texts,
            normalize_embeddings=self._config.get("normalize", True),
            show_progress_bar=False,
            batch_size=batch_size,
        )

        return [emb.tolist() for emb in embeddings]

    async def embed_query(self, query: str) -> EmbeddingResult:
        """
        Gera embedding para uma query de busca.

        Usa prefixo "query:" em vez de "passage:" para melhor
        performance em busca semantica.

        Args:
            query: Query de busca

        Returns:
            EmbeddingResult
        """
        if not self._connected:
            raise RuntimeError("Embedding provider nao conectado")

        if not query or not query.strip():
            raise ValueError("Query vazia")

        start_time = time.perf_counter()

        try:
            loop = asyncio.get_event_loop()
            embedding = await loop.run_in_executor(
                self._executor,
                self._generate_query_embedding,
                query
            )

            latency_ms = (time.perf_counter() - start_time) * 1000

            return EmbeddingResult(
                embedding=embedding,
                model_name=self._model_name,
                latency_ms=latency_ms,
                dimensions=len(embedding),
            )

        except Exception as e:
            logger.error(f"Erro ao gerar embedding de query: {e}")
            raise

    def _generate_query_embedding(self, query: str) -> List[float]:
        """Gera embedding de query (executado em thread separada)."""
        # Prefixo "query:" para buscas
        prefixed_query = f"query: {query}"

        embedding = self._model.encode(
            prefixed_query,
            normalize_embeddings=self._config.get("normalize", True),
            show_progress_bar=False,
        )

        return embedding.tolist()
