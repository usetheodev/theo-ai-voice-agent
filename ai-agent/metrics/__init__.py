"""
Módulo de métricas Prometheus para AI Agent
"""

from metrics.prometheus_metrics import (
    # Sessões
    SESSIONS_CREATED,
    SESSIONS_ENDED,
    ACTIVE_SESSIONS,
    SESSION_DURATION,
    # Pipeline
    PIPELINE_LATENCY,
    STT_LATENCY,
    LLM_LATENCY,
    TTS_LATENCY,
    PIPELINE_ERRORS,
    # Streaming Breakdown
    LLM_FIRST_TOKEN_LATENCY,
    TTS_FIRST_BYTE_LATENCY,
    VOICE_TTFB_SECONDS,
    # Circuit Breaker
    PROVIDER_CIRCUIT_BREAKER_STATE,
    # Backpressure
    AUDIO_FRAMES_DROPPED_BACKPRESSURE,
    # Latência E2E
    VOICE_TO_VOICE_LATENCY,
    LATENCY_BUDGET_EXCEEDED,
    # WebSocket
    WEBSOCKET_CONNECTIONS,
    # Áudio
    AUDIO_BYTES_RECEIVED,
    AUDIO_BYTES_SENT,
    # ASP (Audio Session Protocol)
    ASP_HANDSHAKE_DURATION,
    ASP_HANDSHAKE_SUCCESS,
    ASP_HANDSHAKE_FAILURE,
    ASP_SESSION_MODE,
    ASP_NEGOTIATION_ADJUSTMENTS,
    ASP_CONFIG_VALUES,
    # Helpers
    start_metrics_server,
    track_session_start,
    track_session_end,
    track_pipeline_latency,
    track_component_latency,
    track_pipeline_error,
    track_websocket_connect,
    track_websocket_disconnect,
    track_audio_received,
    track_audio_sent,
    # ASP Helpers
    track_asp_handshake_success,
    track_asp_handshake_failure,
    track_asp_session_mode,
    track_asp_negotiation_adjustment,
    track_asp_config_value,
    clear_asp_session_metrics,
)

__all__ = [
    'SESSIONS_CREATED',
    'SESSIONS_ENDED',
    'ACTIVE_SESSIONS',
    'SESSION_DURATION',
    'PIPELINE_LATENCY',
    'STT_LATENCY',
    'LLM_LATENCY',
    'TTS_LATENCY',
    'PIPELINE_ERRORS',
    'LLM_FIRST_TOKEN_LATENCY',
    'TTS_FIRST_BYTE_LATENCY',
    'VOICE_TTFB_SECONDS',
    'PROVIDER_CIRCUIT_BREAKER_STATE',
    'AUDIO_FRAMES_DROPPED_BACKPRESSURE',
    'VOICE_TO_VOICE_LATENCY',
    'LATENCY_BUDGET_EXCEEDED',
    'WEBSOCKET_CONNECTIONS',
    'AUDIO_BYTES_RECEIVED',
    'AUDIO_BYTES_SENT',
    # ASP
    'ASP_HANDSHAKE_DURATION',
    'ASP_HANDSHAKE_SUCCESS',
    'ASP_HANDSHAKE_FAILURE',
    'ASP_SESSION_MODE',
    'ASP_NEGOTIATION_ADJUSTMENTS',
    'ASP_CONFIG_VALUES',
    # Helpers
    'start_metrics_server',
    'track_session_start',
    'track_session_end',
    'track_pipeline_latency',
    'track_component_latency',
    'track_pipeline_error',
    'track_websocket_connect',
    'track_websocket_disconnect',
    'track_audio_received',
    'track_audio_sent',
    # ASP Helpers
    'track_asp_handshake_success',
    'track_asp_handshake_failure',
    'track_asp_session_mode',
    'track_asp_negotiation_adjustment',
    'track_asp_config_value',
    'clear_asp_session_metrics',
]
