"""Tests for TTS warmup functionality.

The warmup feature eliminates cold-start latency by pre-loading
TTS models before the first synthesis request.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from voice_pipeline.interfaces.tts import TTSInterface, AudioChunk


# =============================================================================
# Test Fixtures
# =============================================================================


class MockTTS(TTSInterface):
    """Mock TTS for testing warmup."""

    name = "MockTTS"

    def __init__(self):
        self.synthesize_calls = []
        self._is_warmed_up = False

    async def synthesize_stream(self, text_stream, voice=None, speed=1.0, **kwargs):
        async for text in text_stream:
            self.synthesize_calls.append(text)
            yield AudioChunk(
                data=b"\x00" * 1000,
                sample_rate=24000,
            )

    async def synthesize(self, text, voice=None, speed=1.0, **kwargs):
        self.synthesize_calls.append(text)
        return b"\x00" * 1000


@pytest.fixture
def mock_tts():
    """Create a mock TTS for testing."""
    return MockTTS()


# =============================================================================
# TTSInterface Warmup Tests
# =============================================================================


class TestTTSInterfaceWarmup:
    """Tests for TTSInterface.warmup() method."""

    async def test_warmup_calls_synthesize(self, mock_tts):
        """Warmup should call synthesize with default text."""
        warmup_ms = await mock_tts.warmup()

        assert len(mock_tts.synthesize_calls) == 1
        assert mock_tts.synthesize_calls[0] == "Hello."
        assert warmup_ms > 0

    async def test_warmup_with_custom_text(self, mock_tts):
        """Warmup should accept custom text."""
        warmup_ms = await mock_tts.warmup(text="Custom warmup.")

        assert mock_tts.synthesize_calls[0] == "Custom warmup."

    async def test_warmup_sets_flag(self, mock_tts):
        """Warmup should set is_warmed_up flag."""
        assert mock_tts.is_warmed_up is False

        await mock_tts.warmup()

        assert mock_tts.is_warmed_up is True

    async def test_warmup_returns_time(self, mock_tts):
        """Warmup should return elapsed time in milliseconds."""
        warmup_ms = await mock_tts.warmup()

        assert isinstance(warmup_ms, float)
        assert warmup_ms >= 0

    async def test_multiple_warmups(self, mock_tts):
        """Multiple warmups should work but may be unnecessary."""
        await mock_tts.warmup()
        await mock_tts.warmup()

        assert len(mock_tts.synthesize_calls) == 2
        assert mock_tts.is_warmed_up is True


# =============================================================================
# KokoroTTS Warmup Tests
# =============================================================================


class TestKokoroTTSWarmup:
    """Tests for KokoroTTSProvider.warmup() method."""

    def test_warmup_uses_language_appropriate_text(self):
        """Kokoro warmup should use language-appropriate text."""
        from voice_pipeline.providers.tts.kokoro import KokoroTTSProvider

        # Test that warmup texts are defined for each language
        tts = KokoroTTSProvider(lang_code="p", voice="pf_dora")

        # Check warmup text for each language
        assert tts._WARMUP_TEXTS["p"] == "Olá."
        assert tts._WARMUP_TEXTS["a"] == "Hello."
        assert tts._WARMUP_TEXTS["b"] == "Hello."
        assert tts._WARMUP_TEXTS["j"] == "こんにちは。"
        assert tts._WARMUP_TEXTS["k"] == "안녕하세요."
        assert tts._WARMUP_TEXTS["z"] == "你好。"

    async def test_warmup_raises_if_not_connected(self):
        """Warmup should raise if not connected."""
        from voice_pipeline.providers.tts.kokoro import KokoroTTSProvider

        tts = KokoroTTSProvider(lang_code="p", voice="pf_dora")

        with pytest.raises(RuntimeError, match="not connected"):
            await tts.warmup()


# =============================================================================
# StreamingVoiceChain Warmup Tests
# =============================================================================


class TestStreamingVoiceChainWarmup:
    """Tests for StreamingVoiceChain auto_warmup feature."""

    async def test_auto_warmup_enabled_by_default(self):
        """auto_warmup should be enabled by default."""
        from voice_pipeline.chains.streaming import StreamingVoiceChain

        # Create mocks
        asr = MagicMock()
        llm = MagicMock()
        tts = MagicMock()
        tts.warmup = AsyncMock(return_value=100.0)

        chain = StreamingVoiceChain(
            asr=asr,
            llm=llm,
            tts=tts,
        )

        assert chain.auto_warmup is True

    async def test_connect_calls_warmup_when_enabled(self):
        """connect() should call tts.warmup() when auto_warmup is True."""
        from voice_pipeline.chains.streaming import StreamingVoiceChain

        # Create mocks
        asr = MagicMock()
        asr.connect = AsyncMock()
        llm = MagicMock()
        llm.connect = AsyncMock()
        tts = MagicMock()
        tts.connect = AsyncMock()
        tts.warmup = AsyncMock(return_value=150.5)

        chain = StreamingVoiceChain(
            asr=asr,
            llm=llm,
            tts=tts,
            auto_warmup=True,
        )

        await chain.connect()

        tts.warmup.assert_called_once()
        assert chain.warmup_time_ms == 150.5

    async def test_connect_skips_warmup_when_disabled(self):
        """connect() should skip warmup when auto_warmup is False."""
        from voice_pipeline.chains.streaming import StreamingVoiceChain

        # Create mocks
        asr = MagicMock()
        asr.connect = AsyncMock()
        llm = MagicMock()
        llm.connect = AsyncMock()
        tts = MagicMock()
        tts.connect = AsyncMock()
        tts.warmup = AsyncMock(return_value=100.0)

        chain = StreamingVoiceChain(
            asr=asr,
            llm=llm,
            tts=tts,
            auto_warmup=False,
        )

        await chain.connect()

        tts.warmup.assert_not_called()
        assert chain.warmup_time_ms is None


# =============================================================================
# VoiceAgentBuilder Warmup Tests
# =============================================================================


class TestVoiceAgentBuilderWarmup:
    """Tests for VoiceAgentBuilder.warmup() method."""

    def test_warmup_default_is_true(self):
        """warmup should be enabled by default."""
        from voice_pipeline.agents.base import VoiceAgentBuilder

        builder = VoiceAgentBuilder()
        assert builder._auto_warmup is True

    def test_warmup_can_be_disabled(self):
        """warmup(False) should disable auto warmup."""
        from voice_pipeline.agents.base import VoiceAgentBuilder

        builder = VoiceAgentBuilder()
        builder.warmup(False)

        assert builder._auto_warmup is False

    def test_warmup_returns_self(self):
        """warmup() should return self for chaining."""
        from voice_pipeline.agents.base import VoiceAgentBuilder

        builder = VoiceAgentBuilder()
        result = builder.warmup(True)

        assert result is builder

    def test_build_passes_warmup_to_streaming_chain(self):
        """build() should pass auto_warmup to StreamingVoiceChain."""
        from voice_pipeline.agents.base import VoiceAgentBuilder

        # Create mock providers directly
        mock_asr = MagicMock()
        mock_llm = MagicMock()
        mock_tts = MagicMock()

        builder = VoiceAgentBuilder()
        builder._asr = mock_asr
        builder._llm = mock_llm
        builder._tts = mock_tts
        builder._streaming = True
        builder._auto_warmup = False

        chain = builder.build()

        assert chain.auto_warmup is False


# =============================================================================
# Integration Tests
# =============================================================================


class TestWarmupIntegration:
    """Integration tests for warmup across the pipeline."""

    async def test_full_builder_with_warmup(self):
        """Test full builder chain with warmup option."""
        from voice_pipeline import VoiceAgent

        # This should not raise
        builder = (
            VoiceAgent.builder()
            .llm("ollama", model="qwen2.5:0.5b")
            .streaming(True)
            .warmup(True)
        )

        assert builder._streaming is True
        assert builder._auto_warmup is True

    async def test_builder_warmup_chaining(self):
        """Test that warmup chains correctly with other methods."""
        from voice_pipeline import VoiceAgent

        builder = (
            VoiceAgent.builder()
            .llm("ollama", model="qwen2.5:0.5b")
            .system_prompt("You are helpful.")
            .warmup(True)
            .streaming(True)
            .memory(max_messages=10)
        )

        assert builder._auto_warmup is True
        assert builder._streaming is True
        assert builder._memory is not None
