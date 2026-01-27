"""
OpenTelemetry tracing callback handler for Voice Pipeline.

Provides distributed tracing support with semantic conventions,
OTel Metrics integration, and VAD span support.
"""

import time
from typing import Any, Optional

from voice_pipeline.callbacks.base import RunContext, VoiceCallbackHandler
from voice_pipeline.interfaces import (
    AudioChunk,
    LLMChunk,
    TranscriptionResult,
    VADEvent,
)

# Try to import OpenTelemetry, but make it optional
try:
    from opentelemetry import trace
    from opentelemetry.trace import Span, SpanKind, Status, StatusCode

    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False
    trace = None
    Span = None
    SpanKind = None
    Status = None
    StatusCode = None

# Import telemetry conventions and metrics (always available, no OTel dep)
from voice_pipeline.telemetry.conventions import (
    GEN_AI_REQUEST_MODEL,
    GEN_AI_REQUEST_TEMPERATURE,
    GEN_AI_SYSTEM,
    GEN_AI_USAGE_OUTPUT_TOKENS,
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

try:
    from voice_pipeline.telemetry.metrics import (
        OTEL_METRICS_AVAILABLE,
        VoicePipelineMetrics,
    )
except ImportError:
    OTEL_METRICS_AVAILABLE = False
    VoicePipelineMetrics = None


class OpenTelemetryHandler(VoiceCallbackHandler):
    """
    Callback handler that creates OpenTelemetry spans with semantic
    conventions and OTel Metrics integration.

    Creates a span hierarchy that maps to the pipeline structure:
    - Pipeline span (root)
      - Turn spans
        - VAD span
        - ASR span
        - LLM span
        - TTS span

    Requires: pip install opentelemetry-api opentelemetry-sdk

    Example:
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.metrics import MeterProvider

        handler = OpenTelemetryHandler(
            tracer_name="voice-pipeline",
            session_id="session-123",
            provider_info={
                "asr": {"name": "deepgram", "model": "nova-2"},
                "llm": {"name": "openai", "model": "gpt-4o"},
                "tts": {"name": "elevenlabs", "model": "eleven_turbo_v2"},
            },
        )

        async with run_with_callbacks([handler]):
            result = await chain.ainvoke(audio)
    """

    def __init__(
        self,
        tracer_name: str = "voice_pipeline",
        tracer_provider: Optional[Any] = None,
        meter_provider: Optional[Any] = None,
        record_input: bool = False,
        record_output: bool = True,
        session_id: Optional[str] = None,
        provider_info: Optional[dict[str, dict[str, str]]] = None,
    ):
        """
        Initialize the OpenTelemetry handler.

        Args:
            tracer_name: Name for the tracer.
            tracer_provider: Custom TracerProvider (uses global if not provided).
            meter_provider: Custom MeterProvider for OTel Metrics.
            record_input: Record input data in spans (may contain PII).
            record_output: Record output data in spans.
            session_id: Voice session identifier.
            provider_info: Provider details per component, e.g.
                {"asr": {"name": "deepgram", "model": "nova-2"}, ...}
        """
        if not OTEL_AVAILABLE:
            raise ImportError(
                "OpenTelemetry is not installed. "
                "Install with: pip install opentelemetry-api opentelemetry-sdk"
            )

        if tracer_provider:
            self.tracer = trace.get_tracer(tracer_name, tracer_provider=tracer_provider)
        else:
            self.tracer = trace.get_tracer(tracer_name)

        self.record_input = record_input
        self.record_output = record_output
        self.session_id = session_id
        self.provider_info = provider_info or {}

        # OTel Metrics (graceful if not available)
        self._metrics: Optional[VoicePipelineMetrics] = None
        if VoicePipelineMetrics is not None and OTEL_METRICS_AVAILABLE:
            try:
                self._metrics = VoicePipelineMetrics(meter_provider=meter_provider)
            except Exception:
                pass

        # Store active spans by run_id
        self._spans: dict[str, dict[str, Span]] = {}

        # Internal state tracking
        self._turn_number: int = 0
        self._token_counts: dict[str, int] = {}
        self._asr_start_times: dict[str, float] = {}
        self._llm_start_times: dict[str, float] = {}
        self._tts_start_times: dict[str, float] = {}
        self._llm_first_token: dict[str, float] = {}
        self._tts_first_chunk: dict[str, float] = {}
        self._tts_audio_bytes: dict[str, int] = {}
        self._tts_chunk_counts: dict[str, int] = {}
        self._vad_start_times: dict[str, float] = {}
        self._pipeline_start_times: dict[str, float] = {}

    def _get_spans(self, ctx: RunContext) -> dict[str, Span]:
        """Get or create span storage for a run."""
        if ctx.run_id not in self._spans:
            self._spans[ctx.run_id] = {}
        return self._spans[ctx.run_id]

    def _common_attributes(self, ctx: RunContext) -> dict[str, Any]:
        """Build common attributes for all spans."""
        attrs: dict[str, Any] = {"run_id": ctx.run_id}
        if ctx.run_name:
            attrs["run_name"] = ctx.run_name
            attrs[VOICE_PIPELINE_NAME] = ctx.run_name
        if ctx.parent_run_id:
            attrs["parent_run_id"] = ctx.parent_run_id
        if self.session_id:
            attrs[VOICE_SESSION_ID] = self.session_id
        if self._turn_number > 0:
            attrs[VOICE_TURN_NUMBER] = self._turn_number
        return attrs

    def _provider_attrs(self, component: str) -> dict[str, Any]:
        """Get provider attributes for a component."""
        attrs: dict[str, Any] = {}
        info = self.provider_info.get(component, {})
        if "name" in info:
            attrs[VOICE_PROVIDER_NAME] = info["name"]
        if "model" in info:
            attrs[GEN_AI_REQUEST_MODEL] = info["model"]
        return attrs

    def _start_span(
        self,
        ctx: RunContext,
        name: str,
        kind: Any = None,
        parent_name: Optional[str] = None,
        attributes: Optional[dict[str, Any]] = None,
    ) -> Span:
        """Start a new span."""
        spans = self._get_spans(ctx)

        # Determine parent context
        parent_span = None
        if parent_name and parent_name in spans:
            parent_span = spans[parent_name]
        elif "turn" in spans:
            parent_span = spans["turn"]
        elif "pipeline" in spans:
            parent_span = spans["pipeline"]

        # Create span context
        span_context = None
        if parent_span:
            span_context = trace.set_span_in_context(parent_span)

        # Merge common attributes
        all_attrs = self._common_attributes(ctx)
        if attributes:
            all_attrs.update(attributes)

        # Start span
        span = self.tracer.start_span(
            name,
            context=span_context,
            kind=kind or SpanKind.INTERNAL,
            attributes=all_attrs,
        )

        # Store span
        spans[name] = span
        return span

    def _end_span(
        self,
        ctx: RunContext,
        name: str,
        status: Optional[Any] = None,
        attributes: Optional[dict[str, Any]] = None,
    ) -> None:
        """End a span."""
        spans = self._get_spans(ctx)
        span = spans.pop(name, None)

        if span:
            if attributes:
                for key, value in attributes.items():
                    if value is not None:
                        span.set_attribute(key, value)

            if status:
                span.set_status(status)
            else:
                span.set_status(Status(StatusCode.OK))

            span.end()

    def _record_error(
        self,
        ctx: RunContext,
        span_name: str,
        error: Exception,
    ) -> None:
        """Record an error on a span."""
        spans = self._get_spans(ctx)
        span = spans.get(span_name)

        if span:
            span.record_exception(error)
            span.set_status(Status(StatusCode.ERROR, str(error)))

    def _cleanup(self, ctx: RunContext) -> None:
        """Clean up all spans and internal state for a run."""
        spans = self._spans.pop(ctx.run_id, {})
        for span in spans.values():
            if span.is_recording():
                span.end()

        # Clean up state dicts
        self._token_counts.pop(ctx.run_id, None)
        self._asr_start_times.pop(ctx.run_id, None)
        self._llm_start_times.pop(ctx.run_id, None)
        self._tts_start_times.pop(ctx.run_id, None)
        self._llm_first_token.pop(ctx.run_id, None)
        self._tts_first_chunk.pop(ctx.run_id, None)
        self._tts_audio_bytes.pop(ctx.run_id, None)
        self._tts_chunk_counts.pop(ctx.run_id, None)
        self._vad_start_times.pop(ctx.run_id, None)
        self._pipeline_start_times.pop(ctx.run_id, None)

    # ==================== Pipeline Lifecycle ====================

    async def on_pipeline_start(self, ctx: RunContext) -> None:
        self._pipeline_start_times[ctx.run_id] = time.perf_counter()
        attrs: dict[str, Any] = {"component": "voice_pipeline"}

        self._start_span(
            ctx,
            "pipeline",
            kind=SpanKind.SERVER,
            attributes=attrs,
        )

        if self._metrics:
            self._metrics.session_started()

    async def on_pipeline_end(self, ctx: RunContext, output: Any = None) -> None:
        e2e_ms = None
        start = self._pipeline_start_times.get(ctx.run_id)
        if start is not None:
            e2e_ms = (time.perf_counter() - start) * 1000

        end_attrs: dict[str, Any] = {"elapsed_ms": ctx.elapsed_ms}
        if e2e_ms is not None:
            end_attrs[VOICE_PIPELINE_E2E_LATENCY_MS] = e2e_ms

        self._end_span(ctx, "pipeline", attributes=end_attrs)

        if self._metrics:
            self._metrics.session_ended()
            if e2e_ms is not None:
                self._metrics.record_e2e_latency(e2e_ms)

        self._cleanup(ctx)

    async def on_pipeline_error(self, ctx: RunContext, error: Exception) -> None:
        self._record_error(ctx, "pipeline", error)
        self._end_span(
            ctx,
            "pipeline",
            status=Status(StatusCode.ERROR, str(error)),
        )

        if self._metrics:
            self._metrics.increment_errors()
            self._metrics.session_ended()

        self._cleanup(ctx)

    # ==================== VAD Events ====================

    async def on_vad_speech_start(self, ctx: RunContext, event: VADEvent) -> None:
        self._vad_start_times[ctx.run_id] = time.perf_counter()

        attrs: dict[str, Any] = {"component": "vad"}
        if event.confidence is not None:
            attrs[VOICE_VAD_CONFIDENCE] = event.confidence

        self._start_span(
            ctx,
            "vad",
            parent_name="turn",
            attributes=attrs,
        )

    async def on_vad_speech_end(self, ctx: RunContext, event: VADEvent) -> None:
        end_attrs: dict[str, Any] = {}
        vad_start = self._vad_start_times.pop(ctx.run_id, None)
        if vad_start is not None:
            duration_ms = (time.perf_counter() - vad_start) * 1000
            end_attrs[VOICE_VAD_SPEECH_DURATION_MS] = duration_ms

        if event.confidence is not None:
            end_attrs[VOICE_VAD_CONFIDENCE] = event.confidence

        self._end_span(ctx, "vad", attributes=end_attrs)

    # ==================== ASR Events ====================

    async def on_asr_start(self, ctx: RunContext, input: bytes) -> None:
        self._asr_start_times[ctx.run_id] = time.perf_counter()

        attrs: dict[str, Any] = {
            "component": "asr",
            VOICE_ASR_INPUT_BYTES: len(input),
        }
        attrs.update(self._provider_attrs("asr"))

        # Check if streaming based on provider info
        asr_info = self.provider_info.get("asr", {})
        if "is_streaming" in asr_info:
            attrs[VOICE_ASR_IS_STREAMING] = asr_info["is_streaming"]

        if self.record_input:
            attrs["input_sample"] = input[:100].hex()

        self._start_span(ctx, "asr", attributes=attrs)

    async def on_asr_partial(
        self, ctx: RunContext, result: TranscriptionResult
    ) -> None:
        spans = self._get_spans(ctx)
        span = spans.get("asr")
        if span:
            attrs: dict[str, Any] = {"text_length": len(result.text)}
            if result.confidence is not None:
                attrs[VOICE_ASR_CONFIDENCE] = result.confidence
            span.add_event("partial_result", attributes=attrs)

    async def on_asr_end(
        self, ctx: RunContext, result: TranscriptionResult
    ) -> None:
        end_attrs: dict[str, Any] = {"text_length": len(result.text)}

        if result.confidence is not None:
            end_attrs[VOICE_ASR_CONFIDENCE] = result.confidence
        if result.language:
            end_attrs[VOICE_ASR_LANGUAGE] = result.language
        if self.record_output:
            end_attrs["text"] = result.text

        # Calculate and record duration
        asr_start = self._asr_start_times.pop(ctx.run_id, None)
        if asr_start is not None:
            duration_ms = (time.perf_counter() - asr_start) * 1000
            end_attrs["duration_ms"] = duration_ms
            if self._metrics:
                self._metrics.record_asr_duration(duration_ms)

        self._end_span(ctx, "asr", attributes=end_attrs)

    async def on_asr_error(self, ctx: RunContext, error: Exception) -> None:
        self._record_error(ctx, "asr", error)
        self._asr_start_times.pop(ctx.run_id, None)
        self._end_span(ctx, "asr", status=Status(StatusCode.ERROR, str(error)))

    # ==================== LLM Events ====================

    async def on_llm_start(
        self, ctx: RunContext, messages: list[dict[str, str]]
    ) -> None:
        self._llm_start_times[ctx.run_id] = time.perf_counter()
        self._token_counts[ctx.run_id] = 0
        # Reset first token tracker
        self._llm_first_token.pop(ctx.run_id, None)

        attrs: dict[str, Any] = {
            "component": "llm",
            "message_count": len(messages),
        }
        attrs.update(self._provider_attrs("llm"))

        # Add GenAI system attribute
        llm_info = self.provider_info.get("llm", {})
        if "name" in llm_info:
            attrs[GEN_AI_SYSTEM] = llm_info["name"]
        if "temperature" in llm_info:
            attrs[GEN_AI_REQUEST_TEMPERATURE] = llm_info["temperature"]

        if self.record_input and messages:
            attrs["last_message_preview"] = messages[-1].get("content", "")[:200]

        self._start_span(ctx, "llm", attributes=attrs)

    async def on_llm_token(self, ctx: RunContext, token: str) -> None:
        # Increment internal counter (FIX: don't use span.attributes.get())
        self._token_counts[ctx.run_id] = self._token_counts.get(ctx.run_id, 0) + 1

        # Detect first token for TTFT
        if ctx.run_id not in self._llm_first_token:
            self._llm_first_token[ctx.run_id] = time.perf_counter()
            llm_start = self._llm_start_times.get(ctx.run_id)
            if llm_start is not None:
                ttft_ms = (self._llm_first_token[ctx.run_id] - llm_start) * 1000
                spans = self._get_spans(ctx)
                span = spans.get("llm")
                if span:
                    span.set_attribute(VOICE_LLM_TTFT_MS, ttft_ms)
                if self._metrics:
                    self._metrics.record_llm_ttft(ttft_ms)

    async def on_llm_end(self, ctx: RunContext, response: str) -> None:
        token_count = self._token_counts.pop(ctx.run_id, 0)

        end_attrs: dict[str, Any] = {
            VOICE_LLM_TOKEN_COUNT: token_count,
            GEN_AI_USAGE_OUTPUT_TOKENS: token_count,
            VOICE_LLM_RESPONSE_LENGTH: len(response),
        }

        if self.record_output:
            end_attrs["response_preview"] = response[:500]

        # Calculate duration
        llm_start = self._llm_start_times.pop(ctx.run_id, None)
        if llm_start is not None:
            duration_ms = (time.perf_counter() - llm_start) * 1000
            end_attrs["duration_ms"] = duration_ms
            if self._metrics:
                self._metrics.record_llm_duration(duration_ms)

        if self._metrics and token_count > 0:
            self._metrics.add_llm_tokens(token_count)

        self._llm_first_token.pop(ctx.run_id, None)
        self._end_span(ctx, "llm", attributes=end_attrs)

    async def on_llm_error(self, ctx: RunContext, error: Exception) -> None:
        self._record_error(ctx, "llm", error)
        self._token_counts.pop(ctx.run_id, None)
        self._llm_start_times.pop(ctx.run_id, None)
        self._llm_first_token.pop(ctx.run_id, None)
        self._end_span(ctx, "llm", status=Status(StatusCode.ERROR, str(error)))

    # ==================== TTS Events ====================

    async def on_tts_start(self, ctx: RunContext, text: str) -> None:
        self._tts_start_times[ctx.run_id] = time.perf_counter()
        self._tts_audio_bytes[ctx.run_id] = 0
        self._tts_chunk_counts[ctx.run_id] = 0
        # Reset first chunk tracker
        self._tts_first_chunk.pop(ctx.run_id, None)

        attrs: dict[str, Any] = {
            "component": "tts",
            "input_length": len(text),
        }
        attrs.update(self._provider_attrs("tts"))

        tts_info = self.provider_info.get("tts", {})
        if "voice" in tts_info:
            attrs[VOICE_TTS_VOICE] = tts_info["voice"]

        if self.record_input:
            attrs["input_preview"] = text[:200]

        self._start_span(ctx, "tts", attributes=attrs)

    async def on_tts_chunk(self, ctx: RunContext, chunk: AudioChunk) -> None:
        self._tts_chunk_counts[ctx.run_id] = (
            self._tts_chunk_counts.get(ctx.run_id, 0) + 1
        )
        self._tts_audio_bytes[ctx.run_id] = (
            self._tts_audio_bytes.get(ctx.run_id, 0) + len(chunk.data)
        )

        # Detect first chunk for TTFA
        if ctx.run_id not in self._tts_first_chunk:
            self._tts_first_chunk[ctx.run_id] = time.perf_counter()
            tts_start = self._tts_start_times.get(ctx.run_id)
            if tts_start is not None:
                ttfa_ms = (self._tts_first_chunk[ctx.run_id] - tts_start) * 1000
                spans = self._get_spans(ctx)
                span = spans.get("tts")
                if span:
                    span.set_attribute(VOICE_TTS_TTFA_MS, ttfa_ms)
                if self._metrics:
                    self._metrics.record_tts_ttfa(ttfa_ms)

        spans = self._get_spans(ctx)
        span = spans.get("tts")
        if span:
            span.add_event(
                "audio_chunk",
                attributes={
                    "chunk_size_bytes": len(chunk.data),
                    VOICE_TTS_SAMPLE_RATE: chunk.sample_rate,
                },
            )

        if self._metrics:
            self._metrics.add_tts_audio_bytes(len(chunk.data))

    async def on_tts_end(self, ctx: RunContext) -> None:
        end_attrs: dict[str, Any] = {
            VOICE_TTS_AUDIO_BYTES: self._tts_audio_bytes.pop(ctx.run_id, 0),
            VOICE_TTS_CHUNK_COUNT: self._tts_chunk_counts.pop(ctx.run_id, 0),
        }

        # Calculate duration
        tts_start = self._tts_start_times.pop(ctx.run_id, None)
        if tts_start is not None:
            duration_ms = (time.perf_counter() - tts_start) * 1000
            end_attrs["duration_ms"] = duration_ms
            if self._metrics:
                self._metrics.record_tts_duration(duration_ms)

        self._tts_first_chunk.pop(ctx.run_id, None)
        self._end_span(ctx, "tts", attributes=end_attrs)

    async def on_tts_error(self, ctx: RunContext, error: Exception) -> None:
        self._record_error(ctx, "tts", error)
        self._tts_start_times.pop(ctx.run_id, None)
        self._tts_audio_bytes.pop(ctx.run_id, None)
        self._tts_chunk_counts.pop(ctx.run_id, None)
        self._tts_first_chunk.pop(ctx.run_id, None)
        self._end_span(ctx, "tts", status=Status(StatusCode.ERROR, str(error)))

    # ==================== Special Events ====================

    async def on_barge_in(self, ctx: RunContext) -> None:
        spans = self._get_spans(ctx)
        span = spans.get("pipeline")
        if span:
            span.add_event("barge_in")
            span.set_attribute(VOICE_PIPELINE_BARGE_IN, True)

        if self._metrics:
            self._metrics.increment_barge_in()

    async def on_turn_start(self, ctx: RunContext) -> None:
        self._turn_number += 1
        self._start_span(
            ctx,
            "turn",
            parent_name="pipeline",
            attributes={VOICE_TURN_NUMBER: self._turn_number},
        )

        if self._metrics:
            self._metrics.increment_turns()

    async def on_turn_end(self, ctx: RunContext) -> None:
        self._end_span(ctx, "turn")


# Factory function for conditional import
def create_otel_handler(
    tracer_name: str = "voice_pipeline",
    session_id: Optional[str] = None,
    provider_info: Optional[dict[str, dict[str, str]]] = None,
    **kwargs,
) -> Optional[OpenTelemetryHandler]:
    """
    Create an OpenTelemetry handler if available.

    Returns None if OpenTelemetry is not installed.

    Args:
        tracer_name: Name for the tracer.
        session_id: Voice session identifier.
        provider_info: Provider details per component.
        **kwargs: Additional arguments for OpenTelemetryHandler.

    Returns:
        OpenTelemetryHandler or None.
    """
    if not OTEL_AVAILABLE:
        return None

    return OpenTelemetryHandler(
        tracer_name=tracer_name,
        session_id=session_id,
        provider_info=provider_info,
        **kwargs,
    )
