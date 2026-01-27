"""
Tests for the enhanced OpenTelemetryHandler with semantic conventions,
VAD spans, metrics integration, and token counting fix.
"""

import asyncio

import pytest

try:
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    OTEL_SDK_AVAILABLE = True
except ImportError:
    OTEL_SDK_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not OTEL_SDK_AVAILABLE, reason="OpenTelemetry SDK not installed"
)


@pytest.fixture
def span_exporter():
    return InMemorySpanExporter()


@pytest.fixture
def tracer_provider(span_exporter):
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    yield provider
    provider.shutdown()


@pytest.fixture
def metric_reader():
    return InMemoryMetricReader()


@pytest.fixture
def meter_provider(metric_reader):
    provider = MeterProvider(metric_readers=[metric_reader])
    yield provider
    provider.shutdown()


@pytest.fixture
def handler(tracer_provider, meter_provider):
    from voice_pipeline.callbacks.handlers.tracing import OpenTelemetryHandler

    return OpenTelemetryHandler(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        session_id="test-session-123",
        provider_info={
            "asr": {"name": "deepgram", "model": "nova-2", "is_streaming": True},
            "llm": {
                "name": "openai",
                "model": "gpt-4o",
                "temperature": "0.7",
            },
            "tts": {
                "name": "elevenlabs",
                "model": "eleven_turbo_v2",
                "voice": "rachel",
            },
        },
        record_output=True,
    )


@pytest.fixture
def handler_no_metrics(tracer_provider):
    """Handler without metrics (meter_provider=None)."""
    from voice_pipeline.callbacks.handlers.tracing import OpenTelemetryHandler

    return OpenTelemetryHandler(
        tracer_provider=tracer_provider,
        session_id="no-metrics-session",
    )


@pytest.fixture
def ctx():
    from voice_pipeline.callbacks.base import RunContext

    return RunContext(run_id="test-run-001", run_name="test-pipeline")


def _get_spans_by_name(exporter):
    """Get finished spans grouped by name."""
    spans = exporter.get_finished_spans()
    result = {}
    for span in spans:
        result[span.name] = span
    return result


def _get_span_attrs(span):
    """Get span attributes as dict."""
    return dict(span.attributes) if span.attributes else {}


class TestSpanCreation:
    """Test that spans are created with correct semantic conventions."""

    @pytest.mark.asyncio
    async def test_pipeline_span_has_session_id(self, handler, ctx, span_exporter):
        await handler.on_pipeline_start(ctx)
        await handler.on_pipeline_end(ctx)

        spans = _get_spans_by_name(span_exporter)
        assert "pipeline" in spans
        attrs = _get_span_attrs(spans["pipeline"])
        assert attrs["voice.session.id"] == "test-session-123"

    @pytest.mark.asyncio
    async def test_pipeline_span_has_name(self, handler, ctx, span_exporter):
        await handler.on_pipeline_start(ctx)
        await handler.on_pipeline_end(ctx)

        spans = _get_spans_by_name(span_exporter)
        attrs = _get_span_attrs(spans["pipeline"])
        assert attrs["voice.pipeline.name"] == "test-pipeline"

    @pytest.mark.asyncio
    async def test_pipeline_span_has_e2e_latency(self, handler, ctx, span_exporter):
        await handler.on_pipeline_start(ctx)
        await handler.on_pipeline_end(ctx)

        spans = _get_spans_by_name(span_exporter)
        attrs = _get_span_attrs(spans["pipeline"])
        assert "voice.pipeline.e2e_latency_ms" in attrs

    @pytest.mark.asyncio
    async def test_asr_span_has_provider_info(self, handler, ctx, span_exporter):
        await handler.on_pipeline_start(ctx)

        from voice_pipeline.interfaces import TranscriptionResult

        await handler.on_asr_start(ctx, b"\x00" * 1600)
        await handler.on_asr_end(
            ctx,
            TranscriptionResult(
                text="hello world",
                is_final=True,
                confidence=0.95,
                language="en-US",
            ),
        )
        await handler.on_pipeline_end(ctx)

        spans = _get_spans_by_name(span_exporter)
        assert "asr" in spans
        attrs = _get_span_attrs(spans["asr"])
        assert attrs["voice.provider.name"] == "deepgram"
        assert attrs["gen_ai.request.model"] == "nova-2"
        assert attrs["voice.asr.input_bytes"] == 1600

    @pytest.mark.asyncio
    async def test_asr_span_has_streaming_flag(self, handler, ctx, span_exporter):
        await handler.on_pipeline_start(ctx)
        await handler.on_asr_start(ctx, b"\x00" * 100)

        from voice_pipeline.interfaces import TranscriptionResult

        await handler.on_asr_end(
            ctx, TranscriptionResult(text="test", is_final=True)
        )
        await handler.on_pipeline_end(ctx)

        spans = _get_spans_by_name(span_exporter)
        attrs = _get_span_attrs(spans["asr"])
        assert attrs["voice.asr.is_streaming"] is True

    @pytest.mark.asyncio
    async def test_asr_span_has_language_and_confidence(
        self, handler, ctx, span_exporter
    ):
        await handler.on_pipeline_start(ctx)

        from voice_pipeline.interfaces import TranscriptionResult

        await handler.on_asr_start(ctx, b"\x00" * 100)
        await handler.on_asr_end(
            ctx,
            TranscriptionResult(
                text="bonjour",
                is_final=True,
                confidence=0.92,
                language="fr",
            ),
        )
        await handler.on_pipeline_end(ctx)

        spans = _get_spans_by_name(span_exporter)
        attrs = _get_span_attrs(spans["asr"])
        assert attrs["voice.asr.confidence"] == 0.92
        assert attrs["voice.asr.language"] == "fr"

    @pytest.mark.asyncio
    async def test_llm_span_has_genai_attrs(self, handler, ctx, span_exporter):
        await handler.on_pipeline_start(ctx)
        await handler.on_llm_start(
            ctx, [{"role": "user", "content": "Hello"}]
        )
        await handler.on_llm_end(ctx, "Hi there!")
        await handler.on_pipeline_end(ctx)

        spans = _get_spans_by_name(span_exporter)
        assert "llm" in spans
        attrs = _get_span_attrs(spans["llm"])
        assert attrs["gen_ai.system"] == "openai"
        assert attrs["gen_ai.request.model"] == "gpt-4o"
        assert attrs["gen_ai.request.temperature"] == "0.7"

    @pytest.mark.asyncio
    async def test_tts_span_has_voice_attr(self, handler, ctx, span_exporter):
        await handler.on_pipeline_start(ctx)
        await handler.on_tts_start(ctx, "Hello world")
        await handler.on_tts_end(ctx)
        await handler.on_pipeline_end(ctx)

        spans = _get_spans_by_name(span_exporter)
        assert "tts" in spans
        attrs = _get_span_attrs(spans["tts"])
        assert attrs["voice.tts.voice"] == "rachel"
        assert attrs["voice.provider.name"] == "elevenlabs"


class TestVADSpans:
    """Test VAD span creation and finalization."""

    @pytest.mark.asyncio
    async def test_vad_span_created_and_finalized(
        self, handler, ctx, span_exporter
    ):
        from voice_pipeline.interfaces import VADEvent

        await handler.on_pipeline_start(ctx)
        await handler.on_turn_start(ctx)

        await handler.on_vad_speech_start(
            ctx, VADEvent(is_speech=True, confidence=0.9)
        )
        await handler.on_vad_speech_end(
            ctx, VADEvent(is_speech=False, confidence=0.85)
        )

        await handler.on_turn_end(ctx)
        await handler.on_pipeline_end(ctx)

        spans = _get_spans_by_name(span_exporter)
        assert "vad" in spans
        attrs = _get_span_attrs(spans["vad"])
        assert attrs["voice.vad.confidence"] == 0.85
        assert "voice.vad.speech_duration_ms" in attrs

    @pytest.mark.asyncio
    async def test_vad_span_has_component_attr(
        self, handler, ctx, span_exporter
    ):
        from voice_pipeline.interfaces import VADEvent

        await handler.on_pipeline_start(ctx)
        await handler.on_vad_speech_start(
            ctx, VADEvent(is_speech=True, confidence=0.95)
        )
        await handler.on_vad_speech_end(
            ctx, VADEvent(is_speech=False, confidence=0.8)
        )
        await handler.on_pipeline_end(ctx)

        spans = _get_spans_by_name(span_exporter)
        attrs = _get_span_attrs(spans["vad"])
        assert attrs["component"] == "vad"


class TestTokenCountFix:
    """Test that token counting uses internal counter, not span.attributes.get()."""

    @pytest.mark.asyncio
    async def test_token_count_correct_after_streaming(
        self, handler, ctx, span_exporter
    ):
        await handler.on_pipeline_start(ctx)
        await handler.on_llm_start(
            ctx, [{"role": "user", "content": "Count test"}]
        )

        # Stream 5 tokens
        for token in ["Hello", " ", "world", "!", " How"]:
            await handler.on_llm_token(ctx, token)

        await handler.on_llm_end(ctx, "Hello world! How")
        await handler.on_pipeline_end(ctx)

        spans = _get_spans_by_name(span_exporter)
        attrs = _get_span_attrs(spans["llm"])
        assert attrs["voice.llm.token_count"] == 5
        assert attrs["gen_ai.usage.output_tokens"] == 5

    @pytest.mark.asyncio
    async def test_ttft_recorded_on_first_token(
        self, handler, ctx, span_exporter
    ):
        await handler.on_pipeline_start(ctx)
        await handler.on_llm_start(
            ctx, [{"role": "user", "content": "TTFT test"}]
        )

        await handler.on_llm_token(ctx, "First")
        await handler.on_llm_token(ctx, " token")
        await handler.on_llm_end(ctx, "First token")
        await handler.on_pipeline_end(ctx)

        spans = _get_spans_by_name(span_exporter)
        attrs = _get_span_attrs(spans["llm"])
        assert "voice.llm.ttft_ms" in attrs
        assert attrs["voice.llm.ttft_ms"] > 0

    @pytest.mark.asyncio
    async def test_token_count_zero_if_no_tokens(
        self, handler, ctx, span_exporter
    ):
        await handler.on_pipeline_start(ctx)
        await handler.on_llm_start(
            ctx, [{"role": "user", "content": "Empty response"}]
        )
        await handler.on_llm_end(ctx, "")
        await handler.on_pipeline_end(ctx)

        spans = _get_spans_by_name(span_exporter)
        attrs = _get_span_attrs(spans["llm"])
        assert attrs["voice.llm.token_count"] == 0


class TestTTSMetrics:
    """Test TTS TTFA detection and audio byte tracking."""

    @pytest.mark.asyncio
    async def test_ttfa_recorded_on_first_chunk(
        self, handler, ctx, span_exporter
    ):
        from voice_pipeline.interfaces import AudioChunk

        await handler.on_pipeline_start(ctx)
        await handler.on_tts_start(ctx, "Hello world")

        chunk = AudioChunk(data=b"\x00" * 480, sample_rate=24000)
        await handler.on_tts_chunk(ctx, chunk)
        await handler.on_tts_chunk(ctx, chunk)
        await handler.on_tts_end(ctx)
        await handler.on_pipeline_end(ctx)

        spans = _get_spans_by_name(span_exporter)
        attrs = _get_span_attrs(spans["tts"])
        assert "voice.tts.ttfa_ms" in attrs
        assert attrs["voice.tts.ttfa_ms"] > 0

    @pytest.mark.asyncio
    async def test_audio_bytes_accumulated(
        self, handler, ctx, span_exporter
    ):
        from voice_pipeline.interfaces import AudioChunk

        await handler.on_pipeline_start(ctx)
        await handler.on_tts_start(ctx, "Test")

        chunk1 = AudioChunk(data=b"\x00" * 100, sample_rate=24000)
        chunk2 = AudioChunk(data=b"\x00" * 200, sample_rate=24000)
        await handler.on_tts_chunk(ctx, chunk1)
        await handler.on_tts_chunk(ctx, chunk2)
        await handler.on_tts_end(ctx)
        await handler.on_pipeline_end(ctx)

        spans = _get_spans_by_name(span_exporter)
        attrs = _get_span_attrs(spans["tts"])
        assert attrs["voice.tts.audio_bytes"] == 300
        assert attrs["voice.tts.chunk_count"] == 2


class TestTurnNumbering:
    """Test turn number increments correctly."""

    @pytest.mark.asyncio
    async def test_turn_number_increments(self, handler, ctx, span_exporter):
        await handler.on_pipeline_start(ctx)

        await handler.on_turn_start(ctx)
        await handler.on_turn_end(ctx)

        await handler.on_turn_start(ctx)
        await handler.on_turn_end(ctx)

        await handler.on_pipeline_end(ctx)

        finished = span_exporter.get_finished_spans()
        turn_spans = [s for s in finished if s.name == "turn"]
        assert len(turn_spans) == 2

        attrs0 = _get_span_attrs(turn_spans[0])
        attrs1 = _get_span_attrs(turn_spans[1])
        assert attrs0["voice.turn.number"] == 1
        assert attrs1["voice.turn.number"] == 2

    @pytest.mark.asyncio
    async def test_session_id_in_turn_span(self, handler, ctx, span_exporter):
        await handler.on_pipeline_start(ctx)
        await handler.on_turn_start(ctx)
        await handler.on_turn_end(ctx)
        await handler.on_pipeline_end(ctx)

        finished = span_exporter.get_finished_spans()
        turn_spans = [s for s in finished if s.name == "turn"]
        assert len(turn_spans) == 1
        attrs = _get_span_attrs(turn_spans[0])
        assert attrs["voice.session.id"] == "test-session-123"


class TestBargeIn:
    """Test barge-in event handling."""

    @pytest.mark.asyncio
    async def test_barge_in_sets_attribute(self, handler, ctx, span_exporter):
        await handler.on_pipeline_start(ctx)
        await handler.on_barge_in(ctx)
        await handler.on_pipeline_end(ctx)

        spans = _get_spans_by_name(span_exporter)
        attrs = _get_span_attrs(spans["pipeline"])
        assert attrs["voice.pipeline.barge_in"] is True


class TestHandlerWithoutMetrics:
    """Test handler works gracefully without metrics."""

    @pytest.mark.asyncio
    async def test_full_cycle_without_metrics(
        self, handler_no_metrics, ctx, span_exporter
    ):
        handler = handler_no_metrics

        from voice_pipeline.interfaces import AudioChunk, TranscriptionResult, VADEvent

        await handler.on_pipeline_start(ctx)
        await handler.on_turn_start(ctx)

        # VAD
        await handler.on_vad_speech_start(
            ctx, VADEvent(is_speech=True, confidence=0.9)
        )
        await handler.on_vad_speech_end(
            ctx, VADEvent(is_speech=False, confidence=0.8)
        )

        # ASR
        await handler.on_asr_start(ctx, b"\x00" * 1600)
        await handler.on_asr_end(
            ctx, TranscriptionResult(text="test", is_final=True)
        )

        # LLM
        await handler.on_llm_start(
            ctx, [{"role": "user", "content": "test"}]
        )
        await handler.on_llm_token(ctx, "response")
        await handler.on_llm_end(ctx, "response")

        # TTS
        await handler.on_tts_start(ctx, "response")
        await handler.on_tts_chunk(
            ctx, AudioChunk(data=b"\x00" * 480, sample_rate=24000)
        )
        await handler.on_tts_end(ctx)

        await handler.on_turn_end(ctx)
        await handler.on_pipeline_end(ctx)

        # Verify spans were created
        finished = span_exporter.get_finished_spans()
        span_names = {s.name for s in finished}
        assert "pipeline" in span_names
        assert "turn" in span_names
        assert "vad" in span_names
        assert "asr" in span_names
        assert "llm" in span_names
        assert "tts" in span_names


class TestErrorHandling:
    """Test error paths cleanup state correctly."""

    @pytest.mark.asyncio
    async def test_pipeline_error_cleans_up(
        self, handler, ctx, span_exporter
    ):
        await handler.on_pipeline_start(ctx)
        await handler.on_pipeline_error(ctx, RuntimeError("test error"))

        spans = _get_spans_by_name(span_exporter)
        assert "pipeline" in spans

        # Internal state should be cleaned up
        assert ctx.run_id not in handler._spans
        assert ctx.run_id not in handler._pipeline_start_times

    @pytest.mark.asyncio
    async def test_asr_error_cleans_up_timing(
        self, handler, ctx, span_exporter
    ):
        await handler.on_pipeline_start(ctx)
        await handler.on_asr_start(ctx, b"\x00" * 100)
        await handler.on_asr_error(ctx, RuntimeError("ASR failed"))
        await handler.on_pipeline_end(ctx)

        assert ctx.run_id not in handler._asr_start_times

    @pytest.mark.asyncio
    async def test_llm_error_cleans_up_state(
        self, handler, ctx, span_exporter
    ):
        await handler.on_pipeline_start(ctx)
        await handler.on_llm_start(
            ctx, [{"role": "user", "content": "test"}]
        )
        await handler.on_llm_token(ctx, "partial")
        await handler.on_llm_error(ctx, RuntimeError("LLM failed"))
        await handler.on_pipeline_end(ctx)

        assert ctx.run_id not in handler._token_counts
        assert ctx.run_id not in handler._llm_start_times
        assert ctx.run_id not in handler._llm_first_token

    @pytest.mark.asyncio
    async def test_tts_error_cleans_up_state(
        self, handler, ctx, span_exporter
    ):
        from voice_pipeline.interfaces import AudioChunk

        await handler.on_pipeline_start(ctx)
        await handler.on_tts_start(ctx, "test")
        await handler.on_tts_chunk(
            ctx, AudioChunk(data=b"\x00" * 100, sample_rate=24000)
        )
        await handler.on_tts_error(ctx, RuntimeError("TTS failed"))
        await handler.on_pipeline_end(ctx)

        assert ctx.run_id not in handler._tts_start_times
        assert ctx.run_id not in handler._tts_audio_bytes
        assert ctx.run_id not in handler._tts_chunk_counts
        assert ctx.run_id not in handler._tts_first_chunk


class TestFactoryFunction:
    """Test create_otel_handler factory."""

    def test_factory_returns_handler(self, tracer_provider):
        from voice_pipeline.callbacks.handlers.tracing import create_otel_handler

        handler = create_otel_handler(
            tracer_provider=tracer_provider,
            session_id="factory-session",
            provider_info={"llm": {"name": "test"}},
        )
        assert handler is not None
        assert handler.session_id == "factory-session"
        assert handler.provider_info == {"llm": {"name": "test"}}

    def test_factory_returns_none_when_unavailable(self, monkeypatch):
        from voice_pipeline.callbacks.handlers import tracing

        monkeypatch.setattr(tracing, "OTEL_AVAILABLE", False)
        handler = tracing.create_otel_handler()
        assert handler is None
