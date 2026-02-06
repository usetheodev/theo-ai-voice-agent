"""
Configuracao do AI Transcribe

Todas as configuracoes sao carregadas de variaveis de ambiente.
Veja .env.example para documentacao detalhada de cada variavel.
"""

import os
import sys
from dotenv import load_dotenv

# Adiciona shared ao path para imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
from shared_config import parse_bool, parse_list

load_dotenv()


# =============================================================================
# WEBSOCKET SERVER
# =============================================================================

WS_CONFIG = {
    "host": os.getenv("WS_HOST", "0.0.0.0"),
    "port": int(os.getenv("WS_PORT", "8766")),
    "max_connections": int(os.getenv("WS_MAX_CONNECTIONS", "100")),
    "ping_interval": int(os.getenv("WS_PING_INTERVAL", "30")),
    "ping_timeout": int(os.getenv("WS_PING_TIMEOUT", "10")),
    "close_timeout": int(os.getenv("WS_CLOSE_TIMEOUT", "5")),
    "max_message_size": int(os.getenv("WS_MAX_MESSAGE_SIZE", str(10 * 1024 * 1024))),
}


# =============================================================================
# ELASTICSEARCH
# =============================================================================

ES_CONFIG = {
    "hosts": parse_list(os.getenv("ES_HOSTS", "http://elasticsearch:9200"), ["http://elasticsearch:9200"]),
    "index_prefix": os.getenv("ES_INDEX_PREFIX", "voice-transcriptions"),
    "bulk_size": int(os.getenv("ES_BULK_SIZE", "50")),
    "flush_interval_ms": int(os.getenv("ES_FLUSH_INTERVAL_MS", "1000")),
    "max_retries": int(os.getenv("ES_MAX_RETRIES", "3")),
    "retry_on_timeout": parse_bool(os.getenv("ES_RETRY_ON_TIMEOUT", "true"), True),
    "request_timeout": int(os.getenv("ES_REQUEST_TIMEOUT", "30")),
}


# =============================================================================
# CONFIGURACOES DE AUDIO
# =============================================================================

AUDIO_CONFIG = {
    "sample_rate": int(os.getenv("AUDIO_SAMPLE_RATE", "8000")),
    "channels": int(os.getenv("AUDIO_CHANNELS", "1")),
    "sample_width": int(os.getenv("AUDIO_SAMPLE_WIDTH", "2")),
    "frame_duration_ms": int(os.getenv("AUDIO_FRAME_DURATION_MS", "20")),
    "max_buffer_seconds": int(os.getenv("AUDIO_MAX_BUFFER_SECONDS", "60")),
}


# =============================================================================
# LOGGING
# =============================================================================

LOG_CONFIG = {
    "level": os.getenv("LOG_LEVEL", "INFO"),
}


# =============================================================================
# METRICAS PROMETHEUS
# =============================================================================

METRICS_CONFIG = {
    "port": int(os.getenv("METRICS_PORT", "9093")),
    "enabled": parse_bool(os.getenv("METRICS_ENABLED", "true"), True),
}


# =============================================================================
# ASR/STT (Automatic Speech Recognition)
# =============================================================================

STT_CONFIG = {
    "provider": os.getenv("STT_PROVIDER", "faster-whisper"),
    "model": os.getenv("STT_MODEL", "tiny"),
    "language": os.getenv("STT_LANGUAGE", "pt"),
    "compute_type": os.getenv("STT_COMPUTE_TYPE", "int8"),
    "device": os.getenv("STT_DEVICE", "cpu"),
    "beam_size": int(os.getenv("STT_BEAM_SIZE", "1")),
    "vad_filter": parse_bool(os.getenv("STT_VAD_FILTER", "false"), False),
    "cpu_threads": int(os.getenv("STT_CPU_THREADS", "0")),
    "num_workers": int(os.getenv("STT_NUM_WORKERS", "1")),
    "executor_workers": int(os.getenv("STT_EXECUTOR_WORKERS", "2")),
}


# =============================================================================
# SESSOES
# =============================================================================

SESSION_CONFIG = {
    "max_idle_seconds": int(os.getenv("SESSION_MAX_IDLE_SECONDS", "300")),
    "cleanup_interval": int(os.getenv("SESSION_CLEANUP_INTERVAL", "60")),
}


# =============================================================================
# EMBEDDINGS
# =============================================================================

EMBEDDING_CONFIG = {
    "enabled": parse_bool(os.getenv("EMBEDDING_ENABLED", "true"), True),
    "model": os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-small"),
    "device": os.getenv("EMBEDDING_DEVICE", "cpu"),
    "batch_size": int(os.getenv("EMBEDDING_BATCH_SIZE", "8")),
    "executor_workers": int(os.getenv("EMBEDDING_EXECUTOR_WORKERS", "2")),
    "normalize": parse_bool(os.getenv("EMBEDDING_NORMALIZE", "true"), True),
}


# =============================================================================
# ENRICHMENT (Opcional - para futuro)
# =============================================================================

ENRICHMENT_CONFIG = {
    "enabled": parse_bool(os.getenv("ENRICHMENT_ENABLED", "false"), False),
    "sentiment_enabled": parse_bool(os.getenv("SENTIMENT_ENABLED", "true"), True),
    "topics_enabled": parse_bool(os.getenv("TOPICS_ENABLED", "false"), False),
    "intent_enabled": parse_bool(os.getenv("INTENT_ENABLED", "false"), False),
}


# =============================================================================
# HTTP API (Busca Semantica)
# =============================================================================

HTTP_API_CONFIG = {
    "enabled": parse_bool(os.getenv("HTTP_API_ENABLED", "true"), True),
    "host": os.getenv("HTTP_API_HOST", "0.0.0.0"),
    "port": int(os.getenv("HTTP_API_PORT", "8767")),
    "default_results": int(os.getenv("HTTP_API_DEFAULT_RESULTS", "10")),
    "max_results": int(os.getenv("HTTP_API_MAX_RESULTS", "100")),
}
