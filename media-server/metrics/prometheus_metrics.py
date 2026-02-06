"""
Definições de métricas Prometheus para Media Server
"""

import logging
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    Enum,
    start_http_server,
)

import time

logger = logging.getLogger("media-server.metrics")

# =============================================================================
# MÉTRICAS DE REGISTRO SIP
# =============================================================================

SIP_REGISTRATION_STATUS = Enum(
    'media_server_sip_registration_status',
    'Status atual do registro SIP',
    states=['unregistered', 'registering', 'registered', 'failed']
)

SIP_REGISTRATION_SUCCESS = Counter(
    'media_server_sip_registration_success_total',
    'Total de registros SIP bem-sucedidos'
)

SIP_REGISTRATION_FAILURES = Counter(
    'media_server_sip_registration_failures_total',
    'Total de falhas de registro SIP',
    ['error_code']
)

# =============================================================================
# MÉTRICAS DE CHAMADAS
# =============================================================================

CALLS_INCOMING = Counter(
    'media_server_calls_incoming_total',
    'Total de chamadas recebidas'
)

CALLS_ANSWERED = Counter(
    'media_server_calls_answered_total',
    'Total de chamadas atendidas'
)

CALLS_REJECTED = Counter(
    'media_server_calls_rejected_total',
    'Total de chamadas rejeitadas',
    ['reason']  # busy, unavailable, error
)

CALLS_ACTIVE = Gauge(
    'media_server_calls_active',
    'Número de chamadas ativas no momento'
)

CALL_DURATION = Histogram(
    'media_server_call_duration_seconds',
    'Duração das chamadas em segundos',
    buckets=[5, 10, 30, 60, 120, 300, 600, 1800, 3600]
)

# =============================================================================
# MÉTRICAS DE WEBSOCKET
# =============================================================================

WEBSOCKET_STATUS = Enum(
    'media_server_websocket_connection_status',
    'Status da conexão WebSocket com AI Agent',
    states=['disconnected', 'connecting', 'connected', 'reconnecting']
)

WEBSOCKET_RECONNECTIONS = Counter(
    'media_server_websocket_reconnections_total',
    'Total de reconexões WebSocket'
)

# =============================================================================
# MÉTRICAS DE RTP
# =============================================================================

RTP_BYTES_RECEIVED = Counter(
    'media_server_rtp_bytes_received_total',
    'Total de bytes RTP recebidos'
)

RTP_BYTES_TRANSMITTED = Counter(
    'media_server_rtp_bytes_transmitted_total',
    'Total de bytes RTP transmitidos'
)

# =============================================================================
# MÉTRICAS DE STREAMING E BARGE-IN
# =============================================================================

BARGE_IN_TOTAL = Counter(
    'media_server_barge_in_total',
    'Total de vezes que o usuário interrompeu a IA (barge-in)'
)

STREAMING_LATENCY = Histogram(
    'media_server_streaming_latency_ms',
    'Latência do streaming de áudio em milissegundos',
    buckets=[20, 50, 100, 200, 300, 500, 1000, 2000]
)

VAD_DETECTION_LATENCY = Histogram(
    'media_server_vad_detection_latency_ms',
    'Latência da detecção de fim de fala (VAD) em milissegundos',
    buckets=[100, 200, 300, 400, 500, 750, 1000]
)

# =============================================================================
# MÉTRICAS VAD DETALHADAS
# =============================================================================

VAD_UTTERANCE_DURATION_MS = Histogram(
    'media_server_vad_utterance_duration_ms',
    'Duração das utterances detectadas pelo VAD em ms',
    buckets=[100, 250, 500, 1000, 2000, 3000, 5000, 10000, 30000]
)

VAD_EVENTS_TOTAL = Counter(
    'media_server_vad_events_total',
    'Total de eventos VAD',
    ['event_type']  # speech_start, speech_end, too_short
)

# =============================================================================
# MÉTRICAS DE LATÊNCIA E2E
# =============================================================================

E2E_LATENCY_SECONDS = Histogram(
    'media_server_e2e_latency_seconds',
    'Latência end-to-end: VAD speech_end até primeiro áudio no playback',
    buckets=[0.2, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0]
)

BARGE_IN_RESPONSE_PROGRESS = Histogram(
    'media_server_barge_in_response_progress',
    'Progresso da resposta quando barge-in ocorreu (0-1)',
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
)

# =============================================================================
# METRICAS MEDIA FORK
# =============================================================================

MEDIA_FORK_BUFFER_SIZE_BYTES = Gauge(
    'media_server_fork_buffer_size_bytes',
    'Tamanho atual do buffer de fork em bytes'
)

MEDIA_FORK_BUFFER_SIZE_MS = Gauge(
    'media_server_fork_buffer_size_ms',
    'Tamanho atual do buffer de fork em milissegundos'
)

MEDIA_FORK_BUFFER_FILL_RATIO = Gauge(
    'media_server_fork_buffer_fill_ratio',
    'Taxa de preenchimento do buffer (0-1)'
)

MEDIA_FORK_FRAMES_RECEIVED = Counter(
    'media_server_fork_frames_received_total',
    'Total de frames recebidos no fork'
)

MEDIA_FORK_FRAMES_DROPPED = Counter(
    'media_server_fork_frames_dropped_total',
    'Total de frames descartados por overflow'
)

MEDIA_FORK_OVERFLOW_EVENTS = Counter(
    'media_server_fork_overflow_events_total',
    'Total de eventos de overflow do buffer'
)

MEDIA_FORK_CONSUMER_LAG_MS = Histogram(
    'media_server_fork_consumer_lag_ms',
    'Lag do consumer (tempo entre captura e envio)',
    buckets=[10, 20, 50, 100, 200, 300, 500, 1000]
)

MEDIA_FORK_CONSUMER_ERRORS = Counter(
    'media_server_fork_consumer_errors_total',
    'Total de erros no consumer do fork',
    ['error_type']  # send_failed, timeout, connection_lost
)

MEDIA_FORK_AI_AGENT_AVAILABLE = Gauge(
    'media_server_fork_ai_agent_available',
    'Indica se AI Agent esta disponivel (1=sim, 0=nao)'
)

MEDIA_FORK_FALLBACK_ACTIVE = Gauge(
    'media_server_fork_fallback_active',
    'Indica se fallback mode esta ativo (1=sim, 0=nao)'
)


# =============================================================================
# MÉTRICAS RTP QUALITY
# =============================================================================

RTP_JITTER_MS = Histogram(
    'media_server_rtp_jitter_ms',
    'Jitter RTP em milissegundos (variação do inter-arrival time)',
    ['direction'],  # inbound, outbound
    buckets=[1, 2, 5, 10, 20, 30, 50, 100, 200]
)

RTP_PACKETS_TOTAL = Counter(
    'media_server_rtp_packets_total',
    'Total de pacotes RTP',
    ['direction', 'status']  # direction: inbound/outbound, status: received/lost
)

RTP_PACKET_LOSS_RATIO = Gauge(
    'media_server_rtp_packet_loss_ratio',
    'Taxa de perda de pacotes RTP (0-1)',
    ['direction']  # inbound, outbound
)

# =============================================================================
# MÉTRICAS RTCP / QoS
# =============================================================================

RTCP_JITTER_MS = Gauge(
    'media_server_rtcp_jitter_ms',
    'Jitter RTCP reportado em milissegundos',
    ['direction']  # rx, tx
)

RTCP_PACKET_LOSS_TOTAL = Gauge(
    'media_server_rtcp_packet_loss_total',
    'Total acumulado de pacotes perdidos (RTCP)',
    ['direction']  # rx, tx
)

RTCP_RTT_MS = Gauge(
    'media_server_rtcp_rtt_ms',
    'Round-trip time RTCP em milissegundos'
)

CALL_MOS_SCORE = Gauge(
    'media_server_call_mos_score',
    'MOS score estimado da chamada atual (1.0-4.5)'
)

MOS_SCORE_DISTRIBUTION = Histogram(
    'media_server_mos_score_distribution',
    'Distribuição dos MOS scores estimados',
    buckets=[1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5]
)

# =============================================================================
# MÉTRICAS PLC (Packet Loss Concealment)
# =============================================================================

PLC_EVENTS_TOTAL = Counter(
    'media_server_plc_events_total',
    'Total de eventos de PLC (concealment)',
    ['direction']  # playback, capture
)

PLC_DURATION_MS = Histogram(
    'media_server_plc_duration_ms',
    'Duração dos eventos de PLC em milissegundos',
    buckets=[20, 40, 60, 80, 100, 200, 500]
)

# =============================================================================
# MÉTRICAS ECHO GUARD
# =============================================================================

ECHO_GUARD_COOLDOWN_MS = Gauge(
    'media_server_echo_guard_cooldown_ms',
    'Cooldown adaptativo atual do EchoGuard em ms'
)

ECHO_DETECTED_TOTAL = Counter(
    'media_server_echo_detected_total',
    'Total de eventos de eco detectados pelo EchoGuard'
)

# =============================================================================
# HELPERS
# =============================================================================

def start_metrics_server(port: int = 9091):
    """Inicia servidor HTTP para expor métricas"""
    try:
        start_http_server(port)
        logger.info(f" Metrics server iniciado na porta {port}")
    except Exception as e:
        logger.error(f"Erro ao iniciar metrics server: {e}")


def track_sip_registration(success: bool, error_code: int = None):
    """Registra resultado de registro SIP"""
    if success:
        SIP_REGISTRATION_STATUS.state('registered')
        SIP_REGISTRATION_SUCCESS.inc()
    else:
        SIP_REGISTRATION_STATUS.state('failed')
        SIP_REGISTRATION_FAILURES.labels(error_code=str(error_code or 'unknown')).inc()


def track_incoming_call():
    """Registra chamada recebida"""
    CALLS_INCOMING.inc()


def track_call_answered():
    """Registra chamada atendida"""
    CALLS_ANSWERED.inc()
    CALLS_ACTIVE.inc()


def track_call_rejected(reason: str):
    """Registra chamada rejeitada"""
    CALLS_REJECTED.labels(reason=reason).inc()


def track_call_ended(duration_seconds: float):
    """Registra fim de chamada"""
    CALLS_ACTIVE.dec()
    CALL_DURATION.observe(duration_seconds)


def track_websocket_connected():
    """Registra conexão WebSocket estabelecida"""
    WEBSOCKET_STATUS.state('connected')


def track_websocket_disconnected():
    """Registra desconexão WebSocket"""
    WEBSOCKET_STATUS.state('disconnected')


def track_websocket_reconnection():
    """Registra tentativa de reconexão WebSocket"""
    WEBSOCKET_STATUS.state('reconnecting')
    WEBSOCKET_RECONNECTIONS.inc()


def track_rtp_received(bytes_count: int):
    """Registra bytes RTP recebidos"""
    RTP_BYTES_RECEIVED.inc(bytes_count)


def track_rtp_transmitted(bytes_count: int):
    """Registra bytes RTP transmitidos"""
    RTP_BYTES_TRANSMITTED.inc(bytes_count)


def track_barge_in():
    """Registra evento de barge-in (usuário interrompeu a IA)"""
    BARGE_IN_TOTAL.inc()


def track_streaming_latency(latency_ms: float):
    """Registra latência do streaming de áudio"""
    STREAMING_LATENCY.observe(latency_ms)


def track_vad_latency(latency_ms: float):
    """Registra latência da detecção VAD"""
    VAD_DETECTION_LATENCY.observe(latency_ms)


def track_vad_event(event_type: str):
    """Registra evento VAD (speech_start, speech_end, too_short)"""
    VAD_EVENTS_TOTAL.labels(event_type=event_type).inc()


def track_vad_utterance_duration(duration_ms: float):
    """Registra duração de uma utterance em ms"""
    VAD_UTTERANCE_DURATION_MS.observe(duration_ms)


def track_e2e_latency(latency_seconds: float):
    """Registra latência end-to-end (speech_end até primeiro áudio)"""
    E2E_LATENCY_SECONDS.observe(latency_seconds)


def track_barge_in_progress(progress: float):
    """Registra progresso da resposta quando barge-in ocorreu (0-1)"""
    BARGE_IN_RESPONSE_PROGRESS.observe(progress)


def track_rtp_jitter(direction: str, jitter_ms: float):
    """Registra jitter RTP em ms"""
    RTP_JITTER_MS.labels(direction=direction).observe(jitter_ms)


def track_rtp_packet(direction: str, status: str, count: int = 1):
    """Registra pacotes RTP (received/lost)"""
    RTP_PACKETS_TOTAL.labels(direction=direction, status=status).inc(count)


def track_rtp_packet_loss_ratio(direction: str, ratio: float):
    """Atualiza taxa de perda de pacotes RTP"""
    RTP_PACKET_LOSS_RATIO.labels(direction=direction).set(ratio)


# =============================================================================
# MEDIA FORK HELPERS
# =============================================================================

def track_fork_buffer_size(size_bytes: int, size_ms: float, fill_ratio: float):
    """Atualiza metricas de tamanho do buffer de fork"""
    MEDIA_FORK_BUFFER_SIZE_BYTES.set(size_bytes)
    MEDIA_FORK_BUFFER_SIZE_MS.set(size_ms)
    MEDIA_FORK_BUFFER_FILL_RATIO.set(fill_ratio)


def track_fork_frame_received():
    """Registra frame recebido no fork"""
    MEDIA_FORK_FRAMES_RECEIVED.inc()


def track_fork_frame_dropped():
    """Registra frame descartado por overflow"""
    MEDIA_FORK_FRAMES_DROPPED.inc()


def track_fork_overflow():
    """Registra evento de overflow do buffer"""
    MEDIA_FORK_OVERFLOW_EVENTS.inc()


def track_fork_consumer_lag(lag_ms: float):
    """Registra lag do consumer em ms"""
    MEDIA_FORK_CONSUMER_LAG_MS.observe(lag_ms)


def track_fork_consumer_error(error_type: str):
    """Registra erro no consumer do fork"""
    MEDIA_FORK_CONSUMER_ERRORS.labels(error_type=error_type).inc()


def track_fork_ai_agent_available(available: bool):
    """Atualiza status de disponibilidade do AI Agent"""
    MEDIA_FORK_AI_AGENT_AVAILABLE.set(1 if available else 0)


def track_fork_fallback_active(active: bool):
    """Atualiza status do fallback mode"""
    MEDIA_FORK_FALLBACK_ACTIVE.set(1 if active else 0)


# =============================================================================
# RTCP / QoS HELPERS
# =============================================================================

def track_rtcp_jitter(direction: str, jitter_ms: float):
    """Atualiza jitter RTCP em ms"""
    RTCP_JITTER_MS.labels(direction=direction).set(jitter_ms)


def track_rtcp_packet_loss(direction: str, loss_count: int):
    """Atualiza total de pacotes perdidos RTCP"""
    RTCP_PACKET_LOSS_TOTAL.labels(direction=direction).set(loss_count)


def track_rtcp_rtt(rtt_ms: float):
    """Atualiza RTT RTCP em ms"""
    RTCP_RTT_MS.set(rtt_ms)


def track_mos_score(mos: float):
    """Registra MOS score estimado"""
    CALL_MOS_SCORE.set(mos)
    MOS_SCORE_DISTRIBUTION.observe(mos)


def track_plc_event(direction: str):
    """Registra evento de PLC"""
    PLC_EVENTS_TOTAL.labels(direction=direction).inc()


def track_plc_duration(duration_ms: float):
    """Registra duração de PLC em ms"""
    PLC_DURATION_MS.observe(duration_ms)


def track_echo_guard_cooldown(cooldown_ms: int):
    """Atualiza cooldown do EchoGuard"""
    ECHO_GUARD_COOLDOWN_MS.set(cooldown_ms)


def track_echo_detected():
    """Registra evento de eco detectado"""
    ECHO_DETECTED_TOTAL.inc()
