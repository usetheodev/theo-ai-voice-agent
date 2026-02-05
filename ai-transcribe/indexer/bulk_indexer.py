"""
Bulk Indexer - Indexacao em batch para maior eficiencia
"""

import asyncio
import logging
import time
from typing import List, Optional
from dataclasses import dataclass, field

from config import ES_CONFIG
from indexer.elasticsearch_client import ElasticsearchClient
from indexer.document_builder import TranscriptionDocument

logger = logging.getLogger("ai-transcribe.bulk_indexer")


@dataclass
class BulkIndexerMetrics:
    """Metricas do BulkIndexer."""
    documents_queued: int = 0
    documents_indexed: int = 0
    documents_failed: int = 0
    batches_sent: int = 0
    total_latency_ms: float = 0.0

    @property
    def avg_latency_ms(self) -> float:
        """Latencia media por batch."""
        if self.batches_sent == 0:
            return 0.0
        return self.total_latency_ms / self.batches_sent

    def to_dict(self) -> dict:
        """Exporta metricas como dicionario."""
        return {
            "documents_queued": self.documents_queued,
            "documents_indexed": self.documents_indexed,
            "documents_failed": self.documents_failed,
            "batches_sent": self.batches_sent,
            "avg_latency_ms": self.avg_latency_ms,
        }


class BulkIndexer:
    """
    Indexador em batch para maior eficiencia.

    Acumula documentos e envia em batches para o Elasticsearch.
    Reduz overhead de conexao e aumenta throughput.

    Features:
    - Flush automatico quando batch atinge tamanho maximo
    - Flush periodico para evitar dados stale
    - Metricas de performance

    Example:
        indexer = BulkIndexer(es_client)
        await indexer.start()

        # Adiciona documentos (nao bloqueia)
        await indexer.add(doc1)
        await indexer.add(doc2)

        # Flush manual se necessario
        await indexer.flush()

        await indexer.stop()
    """

    def __init__(
        self,
        es_client: ElasticsearchClient,
        batch_size: Optional[int] = None,
        flush_interval_ms: Optional[int] = None,
    ):
        self._client = es_client
        self._batch_size = batch_size or ES_CONFIG["bulk_size"]
        self._flush_interval_ms = flush_interval_ms or ES_CONFIG["flush_interval_ms"]

        self._queue: List[TranscriptionDocument] = []
        self._lock = asyncio.Lock()
        self._flush_task: Optional[asyncio.Task] = None
        self._running = False

        self.metrics = BulkIndexerMetrics()

        logger.info(
            f"BulkIndexer criado: batch_size={self._batch_size}, "
            f"flush_interval={self._flush_interval_ms}ms"
        )

    async def start(self) -> None:
        """Inicia o indexador e a task de flush periodico."""
        if self._running:
            return

        self._running = True
        self._flush_task = asyncio.create_task(
            self._periodic_flush_loop(),
            name="bulk_indexer_flush"
        )
        logger.info("BulkIndexer iniciado")

    async def stop(self) -> None:
        """Para o indexador e faz flush final."""
        self._running = False

        # Cancela task de flush periodico
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

        # Flush final
        await self.flush()
        logger.info(
            f"BulkIndexer parado: "
            f"indexed={self.metrics.documents_indexed}, "
            f"failed={self.metrics.documents_failed}"
        )

    async def add(self, document: TranscriptionDocument) -> None:
        """
        Adiciona documento a fila.

        Args:
            document: Documento de transcricao
        """
        async with self._lock:
            self._queue.append(document)
            self.metrics.documents_queued += 1

        # Flush se atingiu tamanho maximo
        if len(self._queue) >= self._batch_size:
            await self.flush()

    async def flush(self) -> int:
        """
        Envia todos os documentos da fila para o Elasticsearch.

        Returns:
            Numero de documentos indexados
        """
        async with self._lock:
            if not self._queue:
                return 0

            # Copia e limpa fila
            documents = self._queue.copy()
            self._queue.clear()

        if not documents:
            return 0

        start_time = time.perf_counter()

        # Converte para dicionarios
        docs_dict = [doc.to_dict() for doc in documents]

        # Envia para Elasticsearch
        success_count = await self._client.bulk_index(docs_dict)

        latency_ms = (time.perf_counter() - start_time) * 1000

        # Atualiza metricas
        self.metrics.documents_indexed += success_count
        self.metrics.documents_failed += len(documents) - success_count
        self.metrics.batches_sent += 1
        self.metrics.total_latency_ms += latency_ms

        logger.debug(
            f"Batch indexado: {success_count}/{len(documents)} docs em {latency_ms:.1f}ms"
        )

        return success_count

    async def _periodic_flush_loop(self) -> None:
        """Loop de flush periodico."""
        flush_interval_s = self._flush_interval_ms / 1000.0

        while self._running:
            try:
                await asyncio.sleep(flush_interval_s)

                if self._queue:
                    await self.flush()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Erro no flush periodico: {e}")

    @property
    def queue_size(self) -> int:
        """Tamanho atual da fila."""
        return len(self._queue)

    @property
    def is_running(self) -> bool:
        """Verifica se esta rodando."""
        return self._running
