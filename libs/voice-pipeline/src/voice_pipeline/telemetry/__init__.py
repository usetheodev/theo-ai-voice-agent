"""
OpenTelemetry instrumentation for Voice Pipeline.

Provides semantic conventions, metrics instruments, and simplified
setup for distributed tracing and Prometheus-compatible metrics.

Example:
    from voice_pipeline.telemetry import setup_telemetry, VoicePipelineMetrics

    providers = setup_telemetry(
        service_name="my-voice-app",
        otlp_endpoint="http://localhost:4317",
    )

    metrics = VoicePipelineMetrics(
        meter_provider=providers["meter_provider"]
    )
"""

from voice_pipeline.telemetry.conventions import (
    GEN_AI_REQUEST_MODEL,
    GEN_AI_REQUEST_TEMPERATURE,
    GEN_AI_SYSTEM,
    GEN_AI_USAGE_OUTPUT_TOKENS,
    METRIC_ASR_DURATION,
    METRIC_LLM_DURATION,
    METRIC_LLM_TOKENS_GENERATED,
    METRIC_LLM_TTFT,
    METRIC_PIPELINE_ACTIVE_SESSIONS,
    METRIC_PIPELINE_BARGE_IN_TOTAL,
    METRIC_PIPELINE_E2E_LATENCY,
    METRIC_PIPELINE_ERRORS_TOTAL,
    METRIC_PIPELINE_TURNS_TOTAL,
    METRIC_TTS_AUDIO_BYTES_TOTAL,
    METRIC_TTS_DURATION,
    METRIC_TTS_TTFA,
    VOICE_ASR_CONFIDENCE,
    VOICE_ASR_INPUT_BYTES,
    VOICE_ASR_IS_STREAMING,
    VOICE_ASR_LANGUAGE,
    VOICE_LLM_RESPONSE_LENGTH,
    VOICE_LLM_TOKEN_COUNT,
    VOICE_LLM_TTFT_MS,
    VOICE_PIPELINE_BARGE_IN,
    VOICE_PIPELINE_E2E_LATENCY_MS,
    VOICE_PIPELINE_NAME,
    VOICE_PROVIDER_NAME,
    VOICE_SESSION_ID,
    VOICE_TTS_AUDIO_BYTES,
    VOICE_TTS_CHUNK_COUNT,
    VOICE_TTS_SAMPLE_RATE,
    VOICE_TTS_TTFA_MS,
    VOICE_TTS_VOICE,
    VOICE_TURN_NUMBER,
    VOICE_VAD_CONFIDENCE,
    VOICE_VAD_SPEECH_DURATION_MS,
)
from voice_pipeline.telemetry.metrics import (
    OTEL_METRICS_AVAILABLE,
    VoicePipelineMetrics,
)
from voice_pipeline.telemetry.setup import setup_telemetry

try:
    from voice_pipeline.telemetry.setup import OTEL_SDK_AVAILABLE
except ImportError:
    OTEL_SDK_AVAILABLE = False

__all__ = [
    # Setup
    "setup_telemetry",
    # Metrics
    "VoicePipelineMetrics",
    # Availability flags
    "OTEL_METRICS_AVAILABLE",
    "OTEL_SDK_AVAILABLE",
    # GenAI conventions
    "GEN_AI_SYSTEM",
    "GEN_AI_REQUEST_MODEL",
    "GEN_AI_REQUEST_TEMPERATURE",
    "GEN_AI_USAGE_OUTPUT_TOKENS",
    # Voice session conventions
    "VOICE_SESSION_ID",
    "VOICE_TURN_NUMBER",
    "VOICE_PIPELINE_NAME",
    "VOICE_PROVIDER_NAME",
    # Voice ASR conventions
    "VOICE_ASR_LANGUAGE",
    "VOICE_ASR_CONFIDENCE",
    "VOICE_ASR_INPUT_BYTES",
    "VOICE_ASR_IS_STREAMING",
    # Voice LLM conventions
    "VOICE_LLM_TOKEN_COUNT",
    "VOICE_LLM_TTFT_MS",
    "VOICE_LLM_RESPONSE_LENGTH",
    # Voice TTS conventions
    "VOICE_TTS_VOICE",
    "VOICE_TTS_TTFA_MS",
    "VOICE_TTS_AUDIO_BYTES",
    "VOICE_TTS_CHUNK_COUNT",
    "VOICE_TTS_SAMPLE_RATE",
    # Voice VAD conventions
    "VOICE_VAD_CONFIDENCE",
    "VOICE_VAD_SPEECH_DURATION_MS",
    # Voice Pipeline conventions
    "VOICE_PIPELINE_E2E_LATENCY_MS",
    "VOICE_PIPELINE_BARGE_IN",
    # Metric instrument names
    "METRIC_ASR_DURATION",
    "METRIC_LLM_TTFT",
    "METRIC_LLM_DURATION",
    "METRIC_TTS_TTFA",
    "METRIC_TTS_DURATION",
    "METRIC_PIPELINE_E2E_LATENCY",
    "METRIC_LLM_TOKENS_GENERATED",
    "METRIC_TTS_AUDIO_BYTES_TOTAL",
    "METRIC_PIPELINE_BARGE_IN_TOTAL",
    "METRIC_PIPELINE_ERRORS_TOTAL",
    "METRIC_PIPELINE_TURNS_TOTAL",
    "METRIC_PIPELINE_ACTIVE_SESSIONS",
]
