"""
OpenTelemetry Metrics instruments for Voice Pipeline.

Provides histogram and counter instruments for Prometheus-compatible
metrics export. Falls back gracefully when OTel is not installed.
"""

from typing import Any, Optional

from voice_pipeline.telemetry.conventions import (
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
)

try:
    from opentelemetry import metrics as otel_metrics

    OTEL_METRICS_AVAILABLE = True
except ImportError:
    OTEL_METRICS_AVAILABLE = False
    otel_metrics = None


class VoicePipelineMetrics:
    """
    OTel Metrics instruments for voice pipeline observability.

    Creates histograms for latency measurements and counters for
    event tracking, suitable for Prometheus export.

    Falls back to no-ops when OpenTelemetry is not installed.

    Example:
        from voice_pipeline.telemetry.metrics import VoicePipelineMetrics

        metrics = VoicePipelineMetrics(meter_provider=my_meter_provider)
        metrics.record_asr_duration(150.0, {"voice.provider.name": "deepgram"})
        metrics.record_llm_ttft(45.0)
        metrics.increment_turns()
    """

    def __init__(
        self,
        meter_provider: Optional[Any] = None,
        meter_name: str = "voice_pipeline",
        meter_version: str = "0.1.0",
    ):
        if not OTEL_METRICS_AVAILABLE:
            self._available = False
            return

        self._available = True

        if meter_provider:
            meter = meter_provider.get_meter(meter_name, meter_version)
        else:
            meter = otel_metrics.get_meter(meter_name, meter_version)

        # Histograms (latency in ms)
        self._asr_duration = meter.create_histogram(
            name=METRIC_ASR_DURATION,
            description="ASR processing duration in milliseconds",
            unit="ms",
        )
        self._llm_ttft = meter.create_histogram(
            name=METRIC_LLM_TTFT,
            description="Time to first LLM token in milliseconds",
            unit="ms",
        )
        self._llm_duration = meter.create_histogram(
            name=METRIC_LLM_DURATION,
            description="LLM total generation duration in milliseconds",
            unit="ms",
        )
        self._tts_ttfa = meter.create_histogram(
            name=METRIC_TTS_TTFA,
            description="Time to first TTS audio chunk in milliseconds",
            unit="ms",
        )
        self._tts_duration = meter.create_histogram(
            name=METRIC_TTS_DURATION,
            description="TTS total synthesis duration in milliseconds",
            unit="ms",
        )
        self._e2e_latency = meter.create_histogram(
            name=METRIC_PIPELINE_E2E_LATENCY,
            description="End-to-end pipeline latency in milliseconds",
            unit="ms",
        )

        # Counters
        self._llm_tokens = meter.create_counter(
            name=METRIC_LLM_TOKENS_GENERATED,
            description="Total LLM tokens generated",
            unit="tokens",
        )
        self._tts_audio_bytes = meter.create_counter(
            name=METRIC_TTS_AUDIO_BYTES_TOTAL,
            description="Total TTS audio bytes produced",
            unit="bytes",
        )
        self._barge_in_total = meter.create_counter(
            name=METRIC_PIPELINE_BARGE_IN_TOTAL,
            description="Total barge-in events",
        )
        self._errors_total = meter.create_counter(
            name=METRIC_PIPELINE_ERRORS_TOTAL,
            description="Total pipeline errors",
        )
        self._turns_total = meter.create_counter(
            name=METRIC_PIPELINE_TURNS_TOTAL,
            description="Total conversation turns",
        )

        # UpDownCounter (gauge-like)
        self._active_sessions = meter.create_up_down_counter(
            name=METRIC_PIPELINE_ACTIVE_SESSIONS,
            description="Currently active voice sessions",
        )

    # ==================== Histogram Recording ====================

    def record_asr_duration(
        self, duration_ms: float, attributes: Optional[dict[str, Any]] = None
    ) -> None:
        if self._available:
            self._asr_duration.record(duration_ms, attributes=attributes)

    def record_llm_ttft(
        self, ttft_ms: float, attributes: Optional[dict[str, Any]] = None
    ) -> None:
        if self._available:
            self._llm_ttft.record(ttft_ms, attributes=attributes)

    def record_llm_duration(
        self, duration_ms: float, attributes: Optional[dict[str, Any]] = None
    ) -> None:
        if self._available:
            self._llm_duration.record(duration_ms, attributes=attributes)

    def record_tts_ttfa(
        self, ttfa_ms: float, attributes: Optional[dict[str, Any]] = None
    ) -> None:
        if self._available:
            self._tts_ttfa.record(ttfa_ms, attributes=attributes)

    def record_tts_duration(
        self, duration_ms: float, attributes: Optional[dict[str, Any]] = None
    ) -> None:
        if self._available:
            self._tts_duration.record(duration_ms, attributes=attributes)

    def record_e2e_latency(
        self, latency_ms: float, attributes: Optional[dict[str, Any]] = None
    ) -> None:
        if self._available:
            self._e2e_latency.record(latency_ms, attributes=attributes)

    # ==================== Counter Methods ====================

    def add_llm_tokens(
        self, count: int = 1, attributes: Optional[dict[str, Any]] = None
    ) -> None:
        if self._available:
            self._llm_tokens.add(count, attributes=attributes)

    def add_tts_audio_bytes(
        self, byte_count: int, attributes: Optional[dict[str, Any]] = None
    ) -> None:
        if self._available:
            self._tts_audio_bytes.add(byte_count, attributes=attributes)

    def increment_barge_in(
        self, attributes: Optional[dict[str, Any]] = None
    ) -> None:
        if self._available:
            self._barge_in_total.add(1, attributes=attributes)

    def increment_errors(
        self, attributes: Optional[dict[str, Any]] = None
    ) -> None:
        if self._available:
            self._errors_total.add(1, attributes=attributes)

    def increment_turns(
        self, attributes: Optional[dict[str, Any]] = None
    ) -> None:
        if self._available:
            self._turns_total.add(1, attributes=attributes)

    # ==================== Session Gauge ====================

    def session_started(
        self, attributes: Optional[dict[str, Any]] = None
    ) -> None:
        if self._available:
            self._active_sessions.add(1, attributes=attributes)

    def session_ended(
        self, attributes: Optional[dict[str, Any]] = None
    ) -> None:
        if self._available:
            self._active_sessions.add(-1, attributes=attributes)
