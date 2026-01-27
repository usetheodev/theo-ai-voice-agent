"""
Tests for the voice_pipeline.telemetry module.

Tests conventions, VoicePipelineMetrics, and setup_telemetry.
"""

import pytest


class TestConventions:
    """Test semantic convention constants."""

    def test_genai_constants_are_strings(self):
        from voice_pipeline.telemetry.conventions import (
            GEN_AI_REQUEST_MODEL,
            GEN_AI_REQUEST_TEMPERATURE,
            GEN_AI_SYSTEM,
            GEN_AI_USAGE_OUTPUT_TOKENS,
        )

        assert isinstance(GEN_AI_SYSTEM, str)
        assert isinstance(GEN_AI_REQUEST_MODEL, str)
        assert isinstance(GEN_AI_REQUEST_TEMPERATURE, str)
        assert isinstance(GEN_AI_USAGE_OUTPUT_TOKENS, str)

    def test_voice_session_constants(self):
        from voice_pipeline.telemetry.conventions import (
            VOICE_PIPELINE_NAME,
            VOICE_SESSION_ID,
            VOICE_TURN_NUMBER,
        )

        assert isinstance(VOICE_SESSION_ID, str)
        assert isinstance(VOICE_TURN_NUMBER, str)
        assert isinstance(VOICE_PIPELINE_NAME, str)

    def test_voice_asr_constants(self):
        from voice_pipeline.telemetry.conventions import (
            VOICE_ASR_CONFIDENCE,
            VOICE_ASR_INPUT_BYTES,
            VOICE_ASR_IS_STREAMING,
            VOICE_ASR_LANGUAGE,
        )

        assert isinstance(VOICE_ASR_LANGUAGE, str)
        assert isinstance(VOICE_ASR_CONFIDENCE, str)
        assert isinstance(VOICE_ASR_INPUT_BYTES, str)
        assert isinstance(VOICE_ASR_IS_STREAMING, str)

    def test_voice_llm_constants(self):
        from voice_pipeline.telemetry.conventions import (
            VOICE_LLM_RESPONSE_LENGTH,
            VOICE_LLM_TOKEN_COUNT,
            VOICE_LLM_TTFT_MS,
        )

        assert isinstance(VOICE_LLM_TOKEN_COUNT, str)
        assert isinstance(VOICE_LLM_TTFT_MS, str)
        assert isinstance(VOICE_LLM_RESPONSE_LENGTH, str)

    def test_voice_tts_constants(self):
        from voice_pipeline.telemetry.conventions import (
            VOICE_TTS_AUDIO_BYTES,
            VOICE_TTS_CHUNK_COUNT,
            VOICE_TTS_SAMPLE_RATE,
            VOICE_TTS_TTFA_MS,
            VOICE_TTS_VOICE,
        )

        assert isinstance(VOICE_TTS_VOICE, str)
        assert isinstance(VOICE_TTS_TTFA_MS, str)
        assert isinstance(VOICE_TTS_AUDIO_BYTES, str)
        assert isinstance(VOICE_TTS_CHUNK_COUNT, str)
        assert isinstance(VOICE_TTS_SAMPLE_RATE, str)

    def test_voice_vad_constants(self):
        from voice_pipeline.telemetry.conventions import (
            VOICE_VAD_CONFIDENCE,
            VOICE_VAD_SPEECH_DURATION_MS,
        )

        assert isinstance(VOICE_VAD_CONFIDENCE, str)
        assert isinstance(VOICE_VAD_SPEECH_DURATION_MS, str)

    def test_voice_pipeline_constants(self):
        from voice_pipeline.telemetry.conventions import (
            VOICE_PIPELINE_BARGE_IN,
            VOICE_PIPELINE_E2E_LATENCY_MS,
        )

        assert isinstance(VOICE_PIPELINE_E2E_LATENCY_MS, str)
        assert isinstance(VOICE_PIPELINE_BARGE_IN, str)

    def test_metric_instrument_names(self):
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

        names = [
            METRIC_ASR_DURATION,
            METRIC_LLM_TTFT,
            METRIC_LLM_DURATION,
            METRIC_TTS_TTFA,
            METRIC_TTS_DURATION,
            METRIC_PIPELINE_E2E_LATENCY,
            METRIC_LLM_TOKENS_GENERATED,
            METRIC_TTS_AUDIO_BYTES_TOTAL,
            METRIC_PIPELINE_BARGE_IN_TOTAL,
            METRIC_PIPELINE_ERRORS_TOTAL,
            METRIC_PIPELINE_TURNS_TOTAL,
            METRIC_PIPELINE_ACTIVE_SESSIONS,
        ]
        for name in names:
            assert isinstance(name, str)
            assert name.startswith("voice.")

    def test_all_constants_use_dot_notation(self):
        from voice_pipeline.telemetry import conventions

        for attr_name in dir(conventions):
            if attr_name.startswith("_"):
                continue
            value = getattr(conventions, attr_name)
            if isinstance(value, str):
                assert "." in value, f"{attr_name}={value} should use dot notation"


class TestVoicePipelineMetrics:
    """Test VoicePipelineMetrics instrument creation and recording."""

    def test_creates_without_error(self):
        from voice_pipeline.telemetry.metrics import (
            OTEL_METRICS_AVAILABLE,
            VoicePipelineMetrics,
        )

        if not OTEL_METRICS_AVAILABLE:
            pytest.skip("OTel metrics not available")

        metrics = VoicePipelineMetrics()
        assert metrics._available is True

    def test_creates_with_meter_provider(self):
        try:
            from opentelemetry.sdk.metrics import MeterProvider
        except ImportError:
            pytest.skip("OTel SDK not available")

        from voice_pipeline.telemetry.metrics import VoicePipelineMetrics

        provider = MeterProvider()
        metrics = VoicePipelineMetrics(meter_provider=provider)
        assert metrics._available is True
        provider.shutdown()

    def test_record_asr_duration_no_error(self):
        from voice_pipeline.telemetry.metrics import (
            OTEL_METRICS_AVAILABLE,
            VoicePipelineMetrics,
        )

        if not OTEL_METRICS_AVAILABLE:
            pytest.skip("OTel metrics not available")

        metrics = VoicePipelineMetrics()
        metrics.record_asr_duration(150.0)
        metrics.record_asr_duration(200.0, {"voice.provider.name": "deepgram"})

    def test_record_llm_ttft_no_error(self):
        from voice_pipeline.telemetry.metrics import (
            OTEL_METRICS_AVAILABLE,
            VoicePipelineMetrics,
        )

        if not OTEL_METRICS_AVAILABLE:
            pytest.skip("OTel metrics not available")

        metrics = VoicePipelineMetrics()
        metrics.record_llm_ttft(45.0)

    def test_record_llm_duration_no_error(self):
        from voice_pipeline.telemetry.metrics import (
            OTEL_METRICS_AVAILABLE,
            VoicePipelineMetrics,
        )

        if not OTEL_METRICS_AVAILABLE:
            pytest.skip("OTel metrics not available")

        metrics = VoicePipelineMetrics()
        metrics.record_llm_duration(500.0)

    def test_record_tts_ttfa_no_error(self):
        from voice_pipeline.telemetry.metrics import (
            OTEL_METRICS_AVAILABLE,
            VoicePipelineMetrics,
        )

        if not OTEL_METRICS_AVAILABLE:
            pytest.skip("OTel metrics not available")

        metrics = VoicePipelineMetrics()
        metrics.record_tts_ttfa(30.0)

    def test_record_tts_duration_no_error(self):
        from voice_pipeline.telemetry.metrics import (
            OTEL_METRICS_AVAILABLE,
            VoicePipelineMetrics,
        )

        if not OTEL_METRICS_AVAILABLE:
            pytest.skip("OTel metrics not available")

        metrics = VoicePipelineMetrics()
        metrics.record_tts_duration(250.0)

    def test_record_e2e_latency_no_error(self):
        from voice_pipeline.telemetry.metrics import (
            OTEL_METRICS_AVAILABLE,
            VoicePipelineMetrics,
        )

        if not OTEL_METRICS_AVAILABLE:
            pytest.skip("OTel metrics not available")

        metrics = VoicePipelineMetrics()
        metrics.record_e2e_latency(800.0)

    def test_counter_methods_no_error(self):
        from voice_pipeline.telemetry.metrics import (
            OTEL_METRICS_AVAILABLE,
            VoicePipelineMetrics,
        )

        if not OTEL_METRICS_AVAILABLE:
            pytest.skip("OTel metrics not available")

        metrics = VoicePipelineMetrics()
        metrics.add_llm_tokens(10)
        metrics.add_tts_audio_bytes(4096)
        metrics.increment_barge_in()
        metrics.increment_errors()
        metrics.increment_turns()

    def test_session_gauge_no_error(self):
        from voice_pipeline.telemetry.metrics import (
            OTEL_METRICS_AVAILABLE,
            VoicePipelineMetrics,
        )

        if not OTEL_METRICS_AVAILABLE:
            pytest.skip("OTel metrics not available")

        metrics = VoicePipelineMetrics()
        metrics.session_started()
        metrics.session_ended()

    def test_graceful_when_otel_not_available(self, monkeypatch):
        """Test that VoicePipelineMetrics degrades gracefully."""
        from voice_pipeline.telemetry import metrics as metrics_mod

        # Simulate OTel not being available
        monkeypatch.setattr(metrics_mod, "OTEL_METRICS_AVAILABLE", False)
        monkeypatch.setattr(metrics_mod, "otel_metrics", None)

        m = metrics_mod.VoicePipelineMetrics()
        assert m._available is False

        # All methods should be no-ops
        m.record_asr_duration(100.0)
        m.record_llm_ttft(50.0)
        m.record_llm_duration(300.0)
        m.record_tts_ttfa(20.0)
        m.record_tts_duration(200.0)
        m.record_e2e_latency(500.0)
        m.add_llm_tokens(5)
        m.add_tts_audio_bytes(1024)
        m.increment_barge_in()
        m.increment_errors()
        m.increment_turns()
        m.session_started()
        m.session_ended()


class TestSetupTelemetry:
    """Test setup_telemetry function."""

    def test_setup_with_console_returns_providers(self):
        try:
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.trace import TracerProvider
        except ImportError:
            pytest.skip("OTel SDK not available")

        from voice_pipeline.telemetry.setup import setup_telemetry

        result = setup_telemetry(console=True)

        assert "tracer_provider" in result
        assert "meter_provider" in result
        assert "resource" in result
        assert isinstance(result["tracer_provider"], TracerProvider)
        assert isinstance(result["meter_provider"], MeterProvider)

        # Cleanup
        result["tracer_provider"].shutdown()
        result["meter_provider"].shutdown()

    def test_setup_with_defaults(self):
        try:
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.trace import TracerProvider
        except ImportError:
            pytest.skip("OTel SDK not available")

        from voice_pipeline.telemetry.setup import setup_telemetry

        result = setup_telemetry()

        assert isinstance(result["tracer_provider"], TracerProvider)
        assert isinstance(result["meter_provider"], MeterProvider)

        result["tracer_provider"].shutdown()
        result["meter_provider"].shutdown()

    def test_setup_with_custom_resource_attributes(self):
        try:
            from opentelemetry.sdk.trace import TracerProvider
        except ImportError:
            pytest.skip("OTel SDK not available")

        from voice_pipeline.telemetry.setup import setup_telemetry

        result = setup_telemetry(
            service_name="test-service",
            service_version="1.0.0",
            resource_attributes={"deployment.environment": "test"},
        )

        assert isinstance(result["tracer_provider"], TracerProvider)

        result["tracer_provider"].shutdown()
        result["meter_provider"].shutdown()

    def test_setup_raises_when_sdk_not_available(self, monkeypatch):
        from voice_pipeline.telemetry import setup as setup_mod

        monkeypatch.setattr(setup_mod, "OTEL_SDK_AVAILABLE", False)

        with pytest.raises(ImportError, match="OpenTelemetry SDK"):
            setup_mod.setup_telemetry()


class TestTelemetryModuleExports:
    """Test that the telemetry __init__ exports work."""

    def test_import_setup_telemetry(self):
        from voice_pipeline.telemetry import setup_telemetry

        assert callable(setup_telemetry)

    def test_import_voice_pipeline_metrics(self):
        from voice_pipeline.telemetry import VoicePipelineMetrics

        assert VoicePipelineMetrics is not None

    def test_import_availability_flags(self):
        from voice_pipeline.telemetry import (
            OTEL_METRICS_AVAILABLE,
            OTEL_SDK_AVAILABLE,
        )

        assert isinstance(OTEL_METRICS_AVAILABLE, bool)
        assert isinstance(OTEL_SDK_AVAILABLE, bool)

    def test_import_convention_constants(self):
        from voice_pipeline.telemetry import (
            GEN_AI_SYSTEM,
            VOICE_ASR_LANGUAGE,
            VOICE_LLM_TOKEN_COUNT,
            VOICE_SESSION_ID,
            VOICE_TTS_VOICE,
            VOICE_VAD_CONFIDENCE,
        )

        assert all(
            isinstance(c, str)
            for c in [
                GEN_AI_SYSTEM,
                VOICE_SESSION_ID,
                VOICE_ASR_LANGUAGE,
                VOICE_LLM_TOKEN_COUNT,
                VOICE_TTS_VOICE,
                VOICE_VAD_CONFIDENCE,
            ]
        )
