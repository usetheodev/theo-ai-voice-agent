"""
Prometheus Metrics

Exposes metrics for monitoring
"""

from prometheus_client import Counter, Histogram, Gauge, start_http_server


# SIP Metrics
sip_invites_total = Counter('sip_invites_total', 'Total INVITE requests received')
sip_calls_active = Gauge('sip_calls_active', 'Number of active calls')
sip_calls_total = Counter('sip_calls_total', 'Total calls completed', ['status'])

# RTP Metrics
rtp_packets_received = Counter('rtp_packets_received_total', 'RTP packets received')
rtp_packets_sent = Counter('rtp_packets_sent_total', 'RTP packets sent')
rtp_jitter_ms = Histogram('rtp_jitter_ms', 'RTP jitter in milliseconds')

# AI Metrics
ai_asr_duration_seconds = Histogram('ai_asr_duration_seconds', 'ASR processing duration')
ai_llm_duration_seconds = Histogram('ai_llm_duration_seconds', 'LLM inference duration')
ai_tts_duration_seconds = Histogram('ai_tts_duration_seconds', 'TTS generation duration')


def start_metrics_server(port: int = 8000):
    """
    Start Prometheus metrics HTTP server

    Args:
        port: HTTP port for metrics endpoint
    """
    start_http_server(port)
