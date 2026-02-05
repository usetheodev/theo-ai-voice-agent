"""
Metricas Prometheus para AI Transcribe
"""

import logging
from threading import Thread
from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    start_http_server,
)

logger = logging.getLogger("ai-transcribe.metrics")

# =============================================================================
# WEBSOCKET METRICS
# =============================================================================

WEBSOCKET_CONNECTIONS = Counter(
    "ai_transcribe_websocket_connections_total",
    "Total de conexoes WebSocket",
    ["event"]  # connect, disconnect
)

ACTIVE_SESSIONS = Gauge(
    "ai_transcribe_active_sessions",
    "Numero de sessoes ativas"
)

# =============================================================================
# AUDIO METRICS
# =============================================================================

AUDIO_BYTES_RECEIVED = Counter(
    "ai_transcribe_audio_bytes_received_total",
    "Total de bytes de audio recebidos"
)

AUDIO_FRAMES_RECEIVED = Counter(
    "ai_transcribe_audio_frames_received_total",
    "Total de frames de audio recebidos"
)

# =============================================================================
# TRANSCRIPTION METRICS
# =============================================================================

TRANSCRIPTION_LATENCY = Histogram(
    "ai_transcribe_transcription_latency_seconds",
    "Latencia da transcricao STT",
    buckets=[0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0]
)

TRANSCRIPTION_DURATION = Histogram(
    "ai_transcribe_audio_duration_seconds",
    "Duracao do audio transcrito",
    buckets=[0.5, 1.0, 2.0, 3.0, 5.0, 10.0, 15.0, 30.0]
)

WORDS_TRANSCRIBED = Counter(
    "ai_transcribe_words_transcribed_total",
    "Total de palavras transcritas"
)

TRANSCRIPTIONS_TOTAL = Counter(
    "ai_transcribe_transcriptions_total",
    "Total de transcricoes realizadas",
    ["status"]  # success, empty, error
)

# =============================================================================
# ELASTICSEARCH METRICS
# =============================================================================

ES_INDEX_LATENCY = Histogram(
    "ai_transcribe_es_index_latency_seconds",
    "Latencia de indexacao no Elasticsearch",
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0]
)

ES_DOCUMENTS_INDEXED = Counter(
    "ai_transcribe_es_documents_indexed_total",
    "Total de documentos indexados no Elasticsearch",
    ["status"]  # success, failed
)

ES_CONNECTION_STATUS = Gauge(
    "ai_transcribe_es_connection_status",
    "Status da conexao com Elasticsearch (1=conectado, 0=desconectado)"
)

ES_BULK_SIZE = Histogram(
    "ai_transcribe_es_bulk_size",
    "Tamanho dos batches de bulk index",
    buckets=[1, 5, 10, 25, 50, 100]
)

# =============================================================================
# EMBEDDING METRICS
# =============================================================================

EMBEDDING_LATENCY = Histogram(
    "ai_transcribe_embedding_latency_seconds",
    "Latencia da geracao de embeddings",
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5]
)

EMBEDDING_TOTAL = Counter(
    "ai_transcribe_embeddings_total",
    "Total de embeddings gerados",
    ["status"]  # success, error, skipped
)

SEMANTIC_SEARCH_LATENCY = Histogram(
    "ai_transcribe_semantic_search_latency_seconds",
    "Latencia de buscas semanticas",
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0]
)

SEMANTIC_SEARCH_TOTAL = Counter(
    "ai_transcribe_semantic_search_total",
    "Total de buscas semanticas",
    ["status"]  # success, error
)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def track_websocket_connect():
    """Registra nova conexao WebSocket."""
    WEBSOCKET_CONNECTIONS.labels(event="connect").inc()


def track_websocket_disconnect():
    """Registra desconexao WebSocket."""
    WEBSOCKET_CONNECTIONS.labels(event="disconnect").inc()


def track_audio_received(num_bytes: int):
    """Registra audio recebido."""
    AUDIO_BYTES_RECEIVED.inc(num_bytes)
    AUDIO_FRAMES_RECEIVED.inc()


def track_transcription(
    latency_seconds: float,
    audio_duration_seconds: float,
    word_count: int,
    status: str = "success"
):
    """
    Registra transcricao realizada.

    Args:
        latency_seconds: Latencia da transcricao
        audio_duration_seconds: Duracao do audio
        word_count: Numero de palavras transcritas
        status: success, empty, error
    """
    TRANSCRIPTION_LATENCY.observe(latency_seconds)
    TRANSCRIPTION_DURATION.observe(audio_duration_seconds)
    WORDS_TRANSCRIBED.inc(word_count)
    TRANSCRIPTIONS_TOTAL.labels(status=status).inc()


def track_es_index(latency_seconds: float, success: bool, batch_size: int = 1):
    """
    Registra indexacao no Elasticsearch.

    Args:
        latency_seconds: Latencia da indexacao
        success: Se indexou com sucesso
        batch_size: Tamanho do batch
    """
    ES_INDEX_LATENCY.observe(latency_seconds)
    ES_BULK_SIZE.observe(batch_size)

    if success:
        ES_DOCUMENTS_INDEXED.labels(status="success").inc(batch_size)
    else:
        ES_DOCUMENTS_INDEXED.labels(status="failed").inc(batch_size)


def track_es_connection_status(connected: bool):
    """Atualiza status de conexao com Elasticsearch."""
    ES_CONNECTION_STATUS.set(1 if connected else 0)


def track_embedding(latency_seconds: float, status: str = "success"):
    """
    Registra geracao de embedding.

    Args:
        latency_seconds: Latencia da geracao
        status: success, error, skipped
    """
    if latency_seconds > 0:
        EMBEDDING_LATENCY.observe(latency_seconds)
    EMBEDDING_TOTAL.labels(status=status).inc()


def track_semantic_search(latency_seconds: float, status: str = "success"):
    """
    Registra busca semantica.

    Args:
        latency_seconds: Latencia da busca
        status: success, error
    """
    SEMANTIC_SEARCH_LATENCY.observe(latency_seconds)
    SEMANTIC_SEARCH_TOTAL.labels(status=status).inc()


def start_metrics_server(port: int):
    """
    Inicia servidor HTTP para metricas Prometheus.

    Args:
        port: Porta do servidor
    """
    def _start():
        start_http_server(port)
        logger.info(f"Servidor de metricas iniciado na porta {port}")

    thread = Thread(target=_start, daemon=True)
    thread.start()
