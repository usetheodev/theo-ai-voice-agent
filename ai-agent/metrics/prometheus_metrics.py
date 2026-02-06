"""
Definições de métricas Prometheus para AI Agent
"""

import time
import logging
from typing import Optional
from contextlib import contextmanager

from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    start_http_server,
)

logger = logging.getLogger("ai-agent.metrics")

# =============================================================================
# MÉTRICAS DE SESSÃO
# =============================================================================

SESSIONS_CREATED = Counter(
    'ai_agent_sessions_created_total',
    'Total de sessões de conversação criadas'
)

SESSIONS_ENDED = Counter(
    'ai_agent_sessions_ended_total',
    'Total de sessões encerradas',
    ['reason']  # hangup, timeout, error
)

ACTIVE_SESSIONS = Gauge(
    'ai_agent_active_sessions',
    'Número de sessões ativas no momento'
)

SESSION_DURATION = Histogram(
    'ai_agent_session_duration_seconds',
    'Duração das sessões em segundos',
    buckets=[5, 10, 30, 60, 120, 300, 600, 1800]
)

# =============================================================================
# MÉTRICAS DE PIPELINE
# =============================================================================

PIPELINE_LATENCY = Histogram(
    'ai_agent_pipeline_latency_seconds',
    'Latência total do pipeline (STT + LLM + TTS)',
    buckets=[0.5, 1.0, 2.0, 3.0, 5.0, 10.0, 15.0, 30.0]
)

STT_LATENCY = Histogram(
    'ai_agent_stt_latency_seconds',
    'Latência do componente STT (Speech-to-Text)',
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0]
)

LLM_LATENCY = Histogram(
    'ai_agent_llm_latency_seconds',
    'Latência do componente LLM',
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0]
)

TTS_LATENCY = Histogram(
    'ai_agent_tts_latency_seconds',
    'Latência do componente TTS (Text-to-Speech)',
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0]
)

# =============================================================================
# MÉTRICAS DE STREAMING BREAKDOWN
# =============================================================================

LLM_FIRST_TOKEN_LATENCY = Histogram(
    'ai_agent_llm_first_token_latency_seconds',
    'Latência até primeiro token do LLM',
    buckets=[0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 2.0]
)

TTS_FIRST_BYTE_LATENCY = Histogram(
    'ai_agent_tts_first_byte_latency_seconds',
    'Latência até primeiro byte de áudio do TTS',
    buckets=[0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0]
)

VOICE_TTFB_SECONDS = Histogram(
    'ai_agent_voice_ttfb_seconds',
    'Time to First Byte: audio.end recebido até primeiro chunk de áudio enviado',
    buckets=[0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0]
)

PIPELINE_ERRORS = Counter(
    'ai_agent_pipeline_errors_total',
    'Total de erros no pipeline',
    ['component']  # stt, llm, tts, pipeline
)

# =============================================================================
# MÉTRICAS DE BARGE-IN / RESPONSE INTERRUPTED
# =============================================================================

RESPONSE_INTERRUPTED_TOTAL = Counter(
    'ai_agent_response_interrupted_total',
    'Total de respostas interrompidas por barge-in'
)

RESPONSE_INTERRUPTED_PROGRESS = Histogram(
    'ai_agent_response_interrupted_progress',
    'Progresso da resposta quando interrompida (0.0-1.0)',
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
)

# =============================================================================
# MÉTRICAS DE CIRCUIT BREAKER
# =============================================================================

PROVIDER_CIRCUIT_BREAKER_STATE = Gauge(
    'ai_agent_provider_circuit_breaker_state',
    'Estado do circuit breaker (0=closed, 1=open, 2=half_open)',
    ['provider']  # stt, llm, tts
)

# =============================================================================
# MÉTRICAS DE BACKPRESSURE
# =============================================================================

AUDIO_FRAMES_DROPPED_BACKPRESSURE = Counter(
    'ai_agent_audio_frames_dropped_backpressure_total',
    'Total de frames de áudio descartados por backpressure'
)

# =============================================================================
# MÉTRICAS DE LATÊNCIA E2E
# =============================================================================

VOICE_TO_VOICE_LATENCY = Histogram(
    'ai_agent_voice_to_voice_latency_seconds',
    'Latência voice-to-voice E2E (audio_end → primeiro byte de resposta)',
    buckets=[0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0]
)

LATENCY_BUDGET_EXCEEDED = Counter(
    'ai_agent_latency_budget_exceeded_total',
    'Total de interações que excederam o budget de latência'
)

# =============================================================================
# MÉTRICAS DE WEBSOCKET
# =============================================================================

WEBSOCKET_CONNECTIONS = Gauge(
    'ai_agent_websocket_connections_active',
    'Número de conexões WebSocket ativas'
)

# =============================================================================
# MÉTRICAS DE ÁUDIO
# =============================================================================

AUDIO_BYTES_RECEIVED = Counter(
    'ai_agent_audio_bytes_received_total',
    'Total de bytes de áudio recebidos'
)

AUDIO_BYTES_SENT = Counter(
    'ai_agent_audio_bytes_sent_total',
    'Total de bytes de áudio enviados'
)

# =============================================================================
# MÉTRICAS DO AUDIO SESSION PROTOCOL (ASP)
# =============================================================================

ASP_HANDSHAKE_DURATION = Histogram(
    'ai_agent_asp_handshake_duration_seconds',
    'Duração do handshake ASP (capabilities → session.started)',
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0]
)

ASP_HANDSHAKE_SUCCESS = Counter(
    'ai_agent_asp_handshake_success_total',
    'Total de handshakes ASP bem-sucedidos',
    ['status']  # accepted, accepted_with_changes
)

ASP_HANDSHAKE_FAILURE = Counter(
    'ai_agent_asp_handshake_failure_total',
    'Total de falhas no handshake ASP',
    ['error_category']  # protocol, audio, vad, session
)

ASP_SESSION_MODE = Gauge(
    'ai_agent_asp_session_mode',
    'Modo da sessão (1=ASP, 0=legado)',
    ['session_id']
)

ASP_NEGOTIATION_ADJUSTMENTS = Counter(
    'ai_agent_asp_negotiation_adjustments_total',
    'Total de ajustes feitos durante negociação ASP',
    ['field']  # vad.threshold, vad.silence_threshold_ms, audio.sample_rate, etc.
)

ASP_CONFIG_VALUES = Gauge(
    'ai_agent_asp_config_value',
    'Valores de configuração ASP ativos',
    ['session_id', 'config_key']  # vad_silence_threshold_ms, vad_min_speech_ms, etc.
)

# =============================================================================
# HELPERS
# =============================================================================

def start_metrics_server(port: int = 9090):
    """Inicia servidor HTTP para expor métricas"""
    try:
        start_http_server(port)
        logger.info(f" Metrics server iniciado na porta {port}")
    except Exception as e:
        logger.error(f"Erro ao iniciar metrics server: {e}")


def track_session_start():
    """Registra início de sessão"""
    SESSIONS_CREATED.inc()
    ACTIVE_SESSIONS.inc()


def track_session_end(reason: str, duration_seconds: float):
    """Registra fim de sessão"""
    SESSIONS_ENDED.labels(reason=reason).inc()
    ACTIVE_SESSIONS.dec()
    SESSION_DURATION.observe(duration_seconds)


@contextmanager
def track_pipeline_latency():
    """Context manager para medir latência do pipeline"""
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        PIPELINE_LATENCY.observe(elapsed)


@contextmanager
def track_component_latency(component: str):
    """Context manager para medir latência de componente"""
    metrics_map = {
        'stt': STT_LATENCY,
        'llm': LLM_LATENCY,
        'tts': TTS_LATENCY,
    }
    metric = metrics_map.get(component)
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        if metric:
            metric.observe(elapsed)


def track_pipeline_error(component: str):
    """Registra erro no pipeline"""
    PIPELINE_ERRORS.labels(component=component).inc()


def track_websocket_connect():
    """Registra nova conexão WebSocket"""
    WEBSOCKET_CONNECTIONS.inc()


def track_websocket_disconnect():
    """Registra desconexão WebSocket"""
    WEBSOCKET_CONNECTIONS.dec()


def track_audio_received(bytes_count: int):
    """Registra bytes de áudio recebidos"""
    AUDIO_BYTES_RECEIVED.inc(bytes_count)


def track_audio_sent(bytes_count: int):
    """Registra bytes de áudio enviados"""
    AUDIO_BYTES_SENT.inc(bytes_count)


# =============================================================================
# HELPERS ASP
# =============================================================================

def track_asp_handshake_success(status: str, duration_seconds: float):
    """
    Registra handshake ASP bem-sucedido.

    Args:
        status: 'accepted' ou 'accepted_with_changes'
        duration_seconds: Duração do handshake
    """
    ASP_HANDSHAKE_SUCCESS.labels(status=status).inc()
    ASP_HANDSHAKE_DURATION.observe(duration_seconds)


def track_asp_handshake_failure(error_category: str):
    """
    Registra falha no handshake ASP.

    Args:
        error_category: 'protocol', 'audio', 'vad', 'session'
    """
    ASP_HANDSHAKE_FAILURE.labels(error_category=error_category).inc()


def track_asp_session_mode(session_id: str, is_asp: bool):
    """
    Registra modo da sessão.

    Args:
        session_id: ID da sessão
        is_asp: True se modo ASP, False se legado
    """
    ASP_SESSION_MODE.labels(session_id=session_id[:8]).set(1 if is_asp else 0)


def track_asp_negotiation_adjustment(field: str):
    """
    Registra ajuste feito durante negociação.

    Args:
        field: Campo ajustado (ex: 'vad.threshold')
    """
    ASP_NEGOTIATION_ADJUSTMENTS.labels(field=field).inc()


def track_asp_config_value(session_id: str, config_key: str, value: float):
    """
    Registra valor de configuração ASP ativo.

    Args:
        session_id: ID da sessão
        config_key: Chave da configuração (ex: 'vad_silence_threshold_ms')
        value: Valor numérico
    """
    ASP_CONFIG_VALUES.labels(
        session_id=session_id[:8],
        config_key=config_key
    ).set(value)


def clear_asp_session_metrics(session_id: str):
    """
    Limpa métricas de uma sessão ASP encerrada.

    Args:
        session_id: ID da sessão
    """
    # Remove labels da sessão
    try:
        ASP_SESSION_MODE.remove(session_id[:8])
    except KeyError:
        pass

    # Remove config values da sessão
    for key in ['vad_silence_threshold_ms', 'vad_min_speech_ms', 'vad_threshold',
                'audio_sample_rate']:
        try:
            ASP_CONFIG_VALUES.remove(session_id[:8], key)
        except KeyError:
            pass
