#!/usr/bin/env python3
"""
AI Transcribe - Transcricao em Tempo Real com Elasticsearch

Servico que recebe audio via WebSocket (ASP Protocol),
transcreve com Faster-Whisper e indexa no Elasticsearch.
"""

import sys
import signal
import logging
import asyncio

# Adiciona shared ao path
sys.path.insert(0, "/app/shared")
sys.path.insert(0, "./shared")

from config import LOG_CONFIG, METRICS_CONFIG, ES_CONFIG, EMBEDDING_CONFIG, HTTP_API_CONFIG
from server.websocket import TranscribeServer
from server.http_api import SearchAPIServer
from transcriber.stt_provider import STTProvider
from indexer.elasticsearch_client import ElasticsearchClient
from indexer.bulk_indexer import BulkIndexer
from embeddings import EmbeddingProvider
from metrics import start_metrics_server, track_es_connection_status

# Logging
logging.basicConfig(
    level=getattr(logging, LOG_CONFIG["level"]),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("ai-transcribe")


class AITranscribe:
    """
    AI Transcribe - Main Application

    Orquestra os componentes:
    - STT Provider (Faster-Whisper)
    - Embedding Provider (sentence-transformers)
    - Elasticsearch Client
    - Bulk Indexer
    - WebSocket Server
    - HTTP API Server (Busca Semantica)
    """

    def __init__(self):
        self.stt: STTProvider = None
        self.embedding_provider: EmbeddingProvider = None
        self.es_client: ElasticsearchClient = None
        self.bulk_indexer: BulkIndexer = None
        self.server: TranscribeServer = None
        self.http_api: SearchAPIServer = None
        self._shutdown_event = asyncio.Event()

    async def start(self):
        """Inicia o AI Transcribe."""
        logger.info("=" * 60)
        logger.info(" AI TRANSCRIBE - Transcricao em Tempo Real")
        logger.info("=" * 60)

        # Inicia servidor de metricas
        if METRICS_CONFIG.get("enabled", True):
            start_metrics_server(METRICS_CONFIG["port"])
            logger.info(f"Metricas Prometheus em http://0.0.0.0:{METRICS_CONFIG['port']}/metrics")

        # Inicializa STT Provider
        logger.info("Inicializando STT Provider...")
        self.stt = STTProvider()
        await self.stt.connect()

        # Inicializa Embedding Provider (se habilitado)
        if EMBEDDING_CONFIG.get("enabled", True):
            logger.info("Inicializando Embedding Provider...")
            self.embedding_provider = EmbeddingProvider()
            embedding_connected = await self.embedding_provider.connect()
            if not embedding_connected:
                logger.warning("Embedding Provider indisponivel - continuando sem embeddings")
                self.embedding_provider = None
        else:
            logger.info("Embedding Provider desabilitado")
            self.embedding_provider = None

        # Conecta ao Elasticsearch
        logger.info("Conectando ao Elasticsearch...")
        self.es_client = ElasticsearchClient()
        es_connected = await self.es_client.connect()
        track_es_connection_status(es_connected)

        if not es_connected:
            logger.warning("Elasticsearch indisponivel - continuando sem indexacao")

        # Inicializa Bulk Indexer
        self.bulk_indexer = BulkIndexer(self.es_client)
        await self.bulk_indexer.start()

        # Inicializa servidor WebSocket
        self.server = TranscribeServer(
            stt_provider=self.stt,
            es_client=self.es_client,
            bulk_indexer=self.bulk_indexer,
            embedding_provider=self.embedding_provider,
        )
        await self.server.start()

        # Inicializa HTTP API (Busca Semantica)
        if HTTP_API_CONFIG.get("enabled", True):
            logger.info("Inicializando HTTP API (Busca Semantica)...")
            self.http_api = SearchAPIServer(
                es_client=self.es_client,
                embedding_provider=self.embedding_provider,
            )
            await self.http_api.start()

        self._log_status()

        # Aguarda shutdown
        await self._shutdown_event.wait()

    def _log_status(self):
        """Exibe status do servico."""
        from config import WS_CONFIG, STT_CONFIG

        logger.info("")
        logger.info(" Componentes:")
        logger.info(f"   STT Provider: {STT_CONFIG['provider']} ({STT_CONFIG['model']})")
        if self.embedding_provider:
            logger.info(f"   Embedding Provider: {EMBEDDING_CONFIG['model']}")
        else:
            logger.info("   Embedding Provider: desabilitado")
        logger.info(f"   Elasticsearch: {ES_CONFIG['hosts']}")
        logger.info(f"   WebSocket Server: ws://0.0.0.0:{WS_CONFIG['port']}")
        if self.http_api:
            logger.info(f"   HTTP API: http://0.0.0.0:{HTTP_API_CONFIG['port']}")
        logger.info("")
        logger.info(" Fluxo de dados:")
        if self.embedding_provider:
            logger.info("   Media Server -> WebSocket -> STT -> Embedding -> Elasticsearch")
        else:
            logger.info("   Media Server -> WebSocket -> STT -> Elasticsearch")
        logger.info("")
        if self.http_api:
            logger.info(" Busca Semantica:")
            logger.info(f"   curl 'http://localhost:{HTTP_API_CONFIG['port']}/api/search?q=texto'")
            logger.info("")
        logger.info(" Aguardando conexoes...")
        logger.info("=" * 60)

    async def stop(self):
        """Para o AI Transcribe."""
        logger.info("Parando AI Transcribe...")

        if self.http_api:
            await self.http_api.stop()

        if self.server:
            await self.server.stop()

        if self.bulk_indexer:
            await self.bulk_indexer.stop()

        if self.es_client:
            await self.es_client.disconnect()

        if self.embedding_provider:
            await self.embedding_provider.disconnect()

        if self.stt:
            await self.stt.disconnect()

        self._shutdown_event.set()
        logger.info("AI Transcribe parado")

    def trigger_shutdown(self):
        """Dispara shutdown (chamado de signal handler)."""
        loop = asyncio.get_event_loop()
        loop.call_soon_threadsafe(self._shutdown_event.set)


async def main():
    """Funcao principal."""
    app = AITranscribe()

    # Handler para shutdown graceful
    def signal_handler(_signum, _frame):
        logger.info("Recebido sinal de shutdown...")
        app.trigger_shutdown()

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        await app.start()
    except Exception as e:
        logger.error(f"Erro fatal: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        await app.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
