"""
OpenTelemetry tracing callback handler for Voice Pipeline.

Provides distributed tracing support for observability platforms.
"""

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


class OpenTelemetryHandler(VoiceCallbackHandler):
    """
    Callback handler that creates OpenTelemetry spans.

    Creates a span hierarchy that maps to the pipeline structure:
    - Pipeline span (root)
      - Turn spans
        - ASR span
        - LLM span
        - TTS span

    Requires: pip install opentelemetry-api opentelemetry-sdk

    Example:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider

        trace.set_tracer_provider(TracerProvider())

        handler = OpenTelemetryHandler(tracer_name="voice-pipeline")

        async with run_with_callbacks([handler]):
            result = await chain.ainvoke(audio)
    """

    def __init__(
        self,
        tracer_name: str = "voice_pipeline",
        tracer_provider: Optional[Any] = None,
        record_input: bool = False,
        record_output: bool = True,
    ):
        """
        Initialize the OpenTelemetry handler.

        Args:
            tracer_name: Name for the tracer.
            tracer_provider: Custom TracerProvider (uses global if not provided).
            record_input: Record input data in spans (may contain PII).
            record_output: Record output data in spans.
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

        # Store active spans by run_id
        self._spans: dict[str, dict[str, Span]] = {}

    def _get_spans(self, ctx: RunContext) -> dict[str, Span]:
        """Get or create span storage for a run."""
        if ctx.run_id not in self._spans:
            self._spans[ctx.run_id] = {}
        return self._spans[ctx.run_id]

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
        elif "pipeline" in spans:
            parent_span = spans["pipeline"]

        # Create span context
        span_context = None
        if parent_span:
            span_context = trace.set_span_in_context(parent_span)

        # Start span
        span = self.tracer.start_span(
            name,
            context=span_context,
            kind=kind or SpanKind.INTERNAL,
            attributes=attributes,
        )

        # Store span
        spans[name] = span

        # Set common attributes
        span.set_attribute("run_id", ctx.run_id)
        if ctx.run_name:
            span.set_attribute("run_name", ctx.run_name)
        if ctx.parent_run_id:
            span.set_attribute("parent_run_id", ctx.parent_run_id)

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
        """Clean up all spans for a run."""
        spans = self._spans.pop(ctx.run_id, {})
        for span in spans.values():
            if span.is_recording():
                span.end()

    # ==================== Pipeline Lifecycle ====================

    async def on_pipeline_start(self, ctx: RunContext) -> None:
        self._start_span(
            ctx,
            "pipeline",
            kind=SpanKind.SERVER,
            attributes={
                "component": "voice_pipeline",
            },
        )

    async def on_pipeline_end(self, ctx: RunContext, output: Any = None) -> None:
        self._end_span(
            ctx,
            "pipeline",
            attributes={
                "elapsed_ms": ctx.elapsed_ms,
            },
        )
        self._cleanup(ctx)

    async def on_pipeline_error(self, ctx: RunContext, error: Exception) -> None:
        self._record_error(ctx, "pipeline", error)
        self._end_span(
            ctx,
            "pipeline",
            status=Status(StatusCode.ERROR, str(error)),
        )
        self._cleanup(ctx)

    # ==================== ASR Events ====================

    async def on_asr_start(self, ctx: RunContext, input: bytes) -> None:
        attrs = {"input_size_bytes": len(input)}
        if self.record_input:
            attrs["input_sample"] = input[:100].hex()

        self._start_span(
            ctx,
            "asr",
            attributes={
                "component": "asr",
                **attrs,
            },
        )

    async def on_asr_partial(
        self, ctx: RunContext, result: TranscriptionResult
    ) -> None:
        spans = self._get_spans(ctx)
        span = spans.get("asr")
        if span:
            span.add_event(
                "partial_result",
                attributes={
                    "text_length": len(result.text),
                    "confidence": result.confidence,
                },
            )

    async def on_asr_end(
        self, ctx: RunContext, result: TranscriptionResult
    ) -> None:
        attrs = {
            "confidence": result.confidence,
            "text_length": len(result.text),
        }

        if self.record_output:
            attrs["text"] = result.text

        if result.language:
            attrs["language"] = result.language

        self._end_span(ctx, "asr", attributes=attrs)

    async def on_asr_error(self, ctx: RunContext, error: Exception) -> None:
        self._record_error(ctx, "asr", error)
        self._end_span(ctx, "asr", status=Status(StatusCode.ERROR, str(error)))

    # ==================== LLM Events ====================

    async def on_llm_start(
        self, ctx: RunContext, messages: list[dict[str, str]]
    ) -> None:
        attrs = {"message_count": len(messages)}
        if self.record_input and messages:
            # Only record last message to limit size
            attrs["last_message_preview"] = messages[-1]["content"][:200]

        self._start_span(
            ctx,
            "llm",
            attributes={
                "component": "llm",
                **attrs,
            },
        )

    async def on_llm_token(self, ctx: RunContext, token: str) -> None:
        spans = self._get_spans(ctx)
        span = spans.get("llm")
        if span:
            # Update token count attribute
            current = span.attributes.get("token_count", 0) if hasattr(span, 'attributes') else 0
            span.set_attribute("token_count", current + 1)

    async def on_llm_end(self, ctx: RunContext, response: str) -> None:
        attrs = {"response_length": len(response)}

        if self.record_output:
            # Truncate for span attribute limit
            attrs["response_preview"] = response[:500]

        self._end_span(ctx, "llm", attributes=attrs)

    async def on_llm_error(self, ctx: RunContext, error: Exception) -> None:
        self._record_error(ctx, "llm", error)
        self._end_span(ctx, "llm", status=Status(StatusCode.ERROR, str(error)))

    # ==================== TTS Events ====================

    async def on_tts_start(self, ctx: RunContext, text: str) -> None:
        attrs = {"input_length": len(text)}
        if self.record_input:
            attrs["input_preview"] = text[:200]

        self._start_span(
            ctx,
            "tts",
            attributes={
                "component": "tts",
                **attrs,
            },
        )

    async def on_tts_chunk(self, ctx: RunContext, chunk: AudioChunk) -> None:
        spans = self._get_spans(ctx)
        span = spans.get("tts")
        if span:
            span.add_event(
                "audio_chunk",
                attributes={
                    "chunk_size_bytes": len(chunk.data),
                    "sample_rate": chunk.sample_rate,
                },
            )

    async def on_tts_end(self, ctx: RunContext) -> None:
        self._end_span(ctx, "tts")

    async def on_tts_error(self, ctx: RunContext, error: Exception) -> None:
        self._record_error(ctx, "tts", error)
        self._end_span(ctx, "tts", status=Status(StatusCode.ERROR, str(error)))

    # ==================== Special Events ====================

    async def on_barge_in(self, ctx: RunContext) -> None:
        spans = self._get_spans(ctx)
        span = spans.get("pipeline")
        if span:
            span.add_event("barge_in")
            span.set_attribute("barge_in_occurred", True)

    async def on_turn_start(self, ctx: RunContext) -> None:
        self._start_span(ctx, "turn", parent_name="pipeline")

    async def on_turn_end(self, ctx: RunContext) -> None:
        self._end_span(ctx, "turn")


# Factory function for conditional import
def create_otel_handler(
    tracer_name: str = "voice_pipeline",
    **kwargs,
) -> Optional[OpenTelemetryHandler]:
    """
    Create an OpenTelemetry handler if available.

    Returns None if OpenTelemetry is not installed.

    Args:
        tracer_name: Name for the tracer.
        **kwargs: Additional arguments for OpenTelemetryHandler.

    Returns:
        OpenTelemetryHandler or None.
    """
    if not OTEL_AVAILABLE:
        return None

    return OpenTelemetryHandler(tracer_name=tracer_name, **kwargs)
