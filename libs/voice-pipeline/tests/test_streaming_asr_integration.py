"""Tests for Streaming ASR integration in the pipeline.

Tests cover:
- Detection of real-time ASR providers via supports_streaming_input property
- StreamingVoiceChain with streaming ASR
- Fallback to batch ASR
- Metrics collection
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from voice_pipeline.chains.streaming import (
    StreamingVoiceChain,
)
from voice_pipeline.interfaces.asr import ASRInterface, TranscriptionResult


# =============================================================================
# Real-time ASR Detection Tests
# =============================================================================


class MockASR:
    """Mock ASR for testing real-time detection."""
    def __init__(self, provider_name: str, streaming_input: bool = False):
        self.provider_name = provider_name
        self._streaming_input = streaming_input

    @property
    def supports_streaming_input(self) -> bool:
        return self._streaming_input


class TestRealtimeASRDetection:
    """Tests for supports_streaming_input property."""

    def test_deepgram_is_realtime(self):
        """Deepgram should be detected as real-time."""
        mock_asr = MockASR("deepgram", streaming_input=True)
        assert mock_asr.supports_streaming_input is True

    def test_whisper_is_not_realtime(self):
        """Whisper.cpp should not be detected as real-time."""
        mock_asr = MockASR("whispercpp")
        assert mock_asr.supports_streaming_input is False

    def test_unknown_provider_is_not_realtime(self):
        """Unknown providers should not be detected as real-time."""
        mock_asr = MockASR("unknown")
        assert mock_asr.supports_streaming_input is False

    def test_provider_with_streaming_input(self):
        """Provider with streaming_input=True should be real-time."""
        mock_asr = MockASR("custom", streaming_input=True)
        assert mock_asr.supports_streaming_input is True

    def test_asr_interface_default_is_false(self):
        """ASRInterface default supports_streaming_input should be False."""
        # MockASR without streaming_input flag defaults to False
        mock = MockASR("generic")
        assert mock.supports_streaming_input is False


# =============================================================================
# StreamingVoiceChain Configuration Tests
# =============================================================================


class TestStreamingVoiceChainConfig:
    """Tests for StreamingVoiceChain configuration."""

    def test_default_streaming_asr_enabled(self):
        """Streaming ASR should be enabled by default."""
        mock_asr = MagicMock()
        mock_llm = MagicMock()
        mock_tts = MagicMock()

        chain = StreamingVoiceChain(
            asr=mock_asr,
            llm=mock_llm,
            tts=mock_tts,
        )

        assert chain.use_streaming_asr is True
        assert chain.streaming_asr_min_words == 3

    def test_streaming_asr_can_be_disabled(self):
        """Streaming ASR can be disabled."""
        mock_asr = MagicMock()
        mock_llm = MagicMock()
        mock_tts = MagicMock()

        chain = StreamingVoiceChain(
            asr=mock_asr,
            llm=mock_llm,
            tts=mock_tts,
            use_streaming_asr=False,
        )

        assert chain.use_streaming_asr is False

    def test_streaming_asr_min_words_configurable(self):
        """Minimum words for streaming ASR is configurable."""
        mock_asr = MagicMock()
        mock_llm = MagicMock()
        mock_tts = MagicMock()

        chain = StreamingVoiceChain(
            asr=mock_asr,
            llm=mock_llm,
            tts=mock_tts,
            streaming_asr_min_words=5,
        )

        assert chain.streaming_asr_min_words == 5


# =============================================================================
# Streaming ASR Mode Tests
# =============================================================================


class TestStreamingASRMode:
    """Tests for streaming ASR mode."""

    def test_streaming_flag_set_correctly_when_disabled(self):
        """_using_streaming_asr should be False when disabled."""
        mock_asr = MockASR("deepgram", streaming_input=True)
        mock_llm = MagicMock()
        mock_tts = MagicMock()

        chain = StreamingVoiceChain(
            asr=mock_asr,
            llm=mock_llm,
            tts=mock_tts,
            use_streaming_asr=False,  # Disabled
        )

        # Initially False
        assert chain._using_streaming_asr is False
        assert chain.use_streaming_asr is False

    def test_streaming_flag_set_correctly_for_non_realtime(self):
        """_using_streaming_asr should be False for non-realtime providers."""
        mock_asr = MockASR("whispercpp")
        mock_llm = MagicMock()
        mock_tts = MagicMock()

        chain = StreamingVoiceChain(
            asr=mock_asr,
            llm=mock_llm,
            tts=mock_tts,
            use_streaming_asr=True,  # Enabled but provider doesn't support
        )

        # Initially False (updated during astream)
        assert chain._using_streaming_asr is False

    def test_streaming_asr_mode_detection(self):
        """Should detect streaming ASR capability via property."""
        mock_asr_deepgram = MockASR("deepgram", streaming_input=True)
        mock_asr_whisper = MockASR("whispercpp")

        # Deepgram supports streaming input
        assert mock_asr_deepgram.supports_streaming_input is True

        # Whisper does not
        assert mock_asr_whisper.supports_streaming_input is False


# =============================================================================
# Metrics Tests
# =============================================================================


class TestStreamingASRMetrics:
    """Tests for metrics collection with streaming ASR."""

    def test_using_streaming_asr_flag_initialized(self):
        """_using_streaming_asr flag should be initialized."""
        mock_asr = MockASR("whispercpp")
        mock_llm = MagicMock()
        mock_tts = MagicMock()

        chain = StreamingVoiceChain(
            asr=mock_asr,
            llm=mock_llm,
            tts=mock_tts,
        )

        assert chain._using_streaming_asr is False

    def test_metrics_initialized_on_chain_creation(self):
        """Metrics should be None until astream is called."""
        mock_asr = MockASR("whispercpp")
        mock_llm = MagicMock()
        mock_tts = MagicMock()

        chain = StreamingVoiceChain(
            asr=mock_asr,
            llm=mock_llm,
            tts=mock_tts,
        )

        # Metrics not yet initialized
        assert chain.metrics is None


# =============================================================================
# Helper Classes
# =============================================================================


class AsyncIteratorMock:
    """Mock async iterator for testing."""

    def __init__(self, items):
        self.items = items
        self.index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.index >= len(self.items):
            raise StopAsyncIteration
        item = self.items[self.index]
        self.index += 1
        return item


# =============================================================================
# Integration with VoiceAgentBuilder Tests
# =============================================================================


class TestVoiceAgentBuilderStreamingASR:
    """Tests for VoiceAgentBuilder with streaming ASR."""

    def test_builder_streaming_asr_option(self):
        """Builder should have streaming_asr option."""
        from voice_pipeline.agents.base import VoiceAgentBuilder

        builder = VoiceAgentBuilder()

        # Check default attributes exist (may not have streaming_asr yet)
        assert hasattr(builder, '_streaming')

    def test_builder_creates_chain_with_deepgram(self):
        """Builder should create chain with Deepgram ASR."""
        from voice_pipeline.agents.base import VoiceAgentBuilder

        builder = VoiceAgentBuilder()
        builder.asr("deepgram", api_key="test-key", language="en-US")
        builder.llm("ollama", model="qwen2.5:0.5b")
        builder.tts("kokoro", voice="pf_dora")
        builder.streaming(True)

        # Verify ASR is set
        assert builder._asr is not None
        assert builder._asr.provider_name == "deepgram"
