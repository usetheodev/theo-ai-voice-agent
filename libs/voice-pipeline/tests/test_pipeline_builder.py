"""Tests for PipelineBuilder and QuickPipeline."""

import pytest

from voice_pipeline import (
    Pipeline,
    PipelineBuilder,
    PipelineConfig,
)
from voice_pipeline.runnable import VoiceSequence

from tests.mocks import MockASR, MockLLM, MockTTS, MockVAD


class TestPipelineBuilder:
    """Tests for PipelineBuilder fluent API."""

    def test_build_with_instances(self):
        """Test building with pre-built instances."""
        asr = MockASR()
        llm = MockLLM()
        tts = MockTTS()
        vad = MockVAD()

        pipeline = (
            PipelineBuilder()
            .with_asr(asr)
            .with_llm(llm)
            .with_tts(tts)
            .with_vad(vad)
            .build()
        )

        assert isinstance(pipeline, Pipeline)
        assert pipeline.asr is asr
        assert pipeline.llm is llm
        assert pipeline.tts is tts
        assert pipeline.vad is vad

    def test_build_with_classes(self):
        """Test building with provider classes."""
        pipeline = (
            PipelineBuilder()
            .with_asr(MockASR, response="custom text")
            .with_llm(MockLLM, response="custom response")
            .with_tts(MockTTS)
            .with_vad(MockVAD)
            .build()
        )

        assert isinstance(pipeline, Pipeline)
        assert isinstance(pipeline.asr, MockASR)
        assert pipeline.asr.config.response == "custom text"

    def test_build_with_config_object(self):
        """Test building with PipelineConfig object."""
        config = PipelineConfig(
            system_prompt="You are a robot.",
            language="pt",
        )

        pipeline = (
            PipelineBuilder()
            .with_config(config)
            .with_asr(MockASR())
            .with_llm(MockLLM())
            .with_tts(MockTTS())
            .with_vad(MockVAD())
            .build()
        )

        assert pipeline.config.system_prompt == "You are a robot."
        assert pipeline.config.language == "pt"

    def test_build_with_config_kwargs(self):
        """Test building with config keyword arguments."""
        pipeline = (
            PipelineBuilder()
            .with_config(
                system_prompt="You are an AI.",
                language="en",
                enable_barge_in=False,
            )
            .with_asr(MockASR())
            .with_llm(MockLLM())
            .with_tts(MockTTS())
            .with_vad(MockVAD())
            .build()
        )

        assert pipeline.config.system_prompt == "You are an AI."
        assert pipeline.config.enable_barge_in is False

    def test_build_without_config(self):
        """Test building without explicit config uses defaults."""
        pipeline = (
            PipelineBuilder()
            .with_asr(MockASR())
            .with_llm(MockLLM())
            .with_tts(MockTTS())
            .with_vad(MockVAD())
            .build()
        )

        assert isinstance(pipeline.config, PipelineConfig)

    def test_build_missing_asr_raises(self):
        """Test that missing ASR raises ValueError."""
        with pytest.raises(ValueError, match="ASR provider is required"):
            (
                PipelineBuilder()
                .with_llm(MockLLM())
                .with_tts(MockTTS())
                .with_vad(MockVAD())
                .build()
            )

    def test_build_missing_llm_raises(self):
        """Test that missing LLM raises ValueError."""
        with pytest.raises(ValueError, match="LLM provider is required"):
            (
                PipelineBuilder()
                .with_asr(MockASR())
                .with_tts(MockTTS())
                .with_vad(MockVAD())
                .build()
            )

    def test_build_missing_tts_raises(self):
        """Test that missing TTS raises ValueError."""
        with pytest.raises(ValueError, match="TTS provider is required"):
            (
                PipelineBuilder()
                .with_asr(MockASR())
                .with_llm(MockLLM())
                .with_vad(MockVAD())
                .build()
            )

    def test_build_missing_vad_raises(self):
        """Test that missing VAD raises ValueError."""
        with pytest.raises(ValueError, match="VAD provider is required"):
            (
                PipelineBuilder()
                .with_asr(MockASR())
                .with_llm(MockLLM())
                .with_tts(MockTTS())
                .build()
            )

    def test_builder_chaining(self):
        """Test that all methods return self for chaining."""
        builder = PipelineBuilder()

        result = builder.with_config(system_prompt="test")
        assert result is builder

        result = builder.with_asr(MockASR())
        assert result is builder

        result = builder.with_llm(MockLLM())
        assert result is builder

        result = builder.with_tts(MockTTS())
        assert result is builder

        result = builder.with_vad(MockVAD())
        assert result is builder


class TestBuildChain:
    """Tests for building simple chains."""

    def test_build_chain(self):
        """Test building a simple ASR | LLM | TTS chain."""
        chain = (
            PipelineBuilder()
            .with_asr(MockASR())
            .with_llm(MockLLM())
            .with_tts(MockTTS())
            .build_chain()
        )

        assert isinstance(chain, VoiceSequence)

    def test_build_chain_missing_provider(self):
        """Test that build_chain requires ASR, LLM, TTS."""
        with pytest.raises(ValueError, match="ASR provider is required"):
            (
                PipelineBuilder()
                .with_llm(MockLLM())
                .with_tts(MockTTS())
                .build_chain()
            )

    @pytest.mark.asyncio
    async def test_chain_processes_audio(self):
        """Test that built chain processes audio correctly."""
        chain = (
            PipelineBuilder()
            .with_asr(MockASR(response="hello"))
            .with_llm(MockLLM(response="world"))
            .with_tts(MockTTS())
            .build_chain()
        )

        result = await chain.ainvoke(b"\x00" * 1000)
        assert result is not None


class TestCallbacksAndErrorHandling:
    """Tests for callbacks and error handling in builder."""

    def test_with_callback(self):
        """Test adding a single callback."""
        from voice_pipeline.callbacks import LoggingHandler

        builder = PipelineBuilder()
        handler = LoggingHandler()

        result = builder.with_callback(handler)

        assert result is builder
        assert handler in builder._callbacks

    def test_with_callbacks(self):
        """Test adding multiple callbacks."""
        from voice_pipeline.callbacks import LoggingHandler, StdOutHandler

        builder = PipelineBuilder()
        handlers = [LoggingHandler(), StdOutHandler()]

        result = builder.with_callbacks(handlers)

        assert result is builder
        assert len(builder._callbacks) == 2

    def test_on_error(self):
        """Test setting error handler."""
        builder = PipelineBuilder()
        errors = []

        def error_handler(e):
            errors.append(e)

        result = builder.on_error(error_handler)

        assert result is builder
        assert builder._on_error is error_handler


class TestTransportAndRealtime:
    """Tests for transport and realtime provider configuration."""

    def test_with_transport_instance(self):
        """Test adding transport instance."""
        from tests.mocks import MockTransport

        builder = PipelineBuilder()
        transport = MockTransport()

        result = builder.with_transport(transport)

        assert result is builder
        assert builder._transport_instance is transport

    def test_with_realtime_instance(self):
        """Test adding realtime instance."""
        from tests.mocks import MockRealtime

        builder = PipelineBuilder()
        realtime = MockRealtime()

        result = builder.with_realtime(realtime)

        assert result is builder
        assert builder._realtime_instance is realtime


class TestMixedConfiguration:
    """Tests for mixed class/instance configurations."""

    def test_mixed_class_and_instance(self):
        """Test using both classes and instances."""
        asr_instance = MockASR(response="instance")
        llm_class = MockLLM  # Class, not instance

        pipeline = (
            PipelineBuilder()
            .with_asr(asr_instance)  # Instance
            .with_llm(llm_class, response="class")  # Class with kwargs
            .with_tts(MockTTS())  # Instance
            .with_vad(MockVAD)  # Class without kwargs
            .build()
        )

        # Instance should be used directly
        assert pipeline.asr is asr_instance
        assert pipeline.asr.config.response == "instance"

        # Class should be instantiated with kwargs
        assert isinstance(pipeline.llm, MockLLM)
        assert pipeline.llm.config.response == "class"
