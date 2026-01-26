"""Tests for FasterWhisper ASR provider."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import numpy as np


# =============================================================================
# Check if faster-whisper is installed
# =============================================================================


def _has_faster_whisper():
    """Check if faster-whisper is available."""
    try:
        import faster_whisper
        return True
    except ImportError:
        return False


# =============================================================================
# Config Tests (no dependencies required)
# =============================================================================


class TestFasterWhisperConfig:
    """Tests for FasterWhisperConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        from voice_pipeline.providers.asr.faster_whisper import FasterWhisperConfig

        config = FasterWhisperConfig()

        assert config.model == "small"
        assert config.device == "cpu"
        assert config.compute_type == "int8"
        assert config.language is None
        assert config.beam_size == 5
        assert config.vad_filter is True
        assert config.word_timestamps is False
        assert config.sample_rate == 16000
        assert config.cpu_threads == 0
        assert config.temperature == 0.0

    def test_custom_config(self):
        """Test custom configuration."""
        from voice_pipeline.providers.asr.faster_whisper import FasterWhisperConfig

        config = FasterWhisperConfig(
            model="base",
            language="pt",
            device="cuda",
            compute_type="float16",
            beam_size=3,
            vad_filter=False,
        )

        assert config.model == "base"
        assert config.language == "pt"
        assert config.device == "cuda"
        assert config.compute_type == "float16"
        assert config.beam_size == 3
        assert config.vad_filter is False

    def test_config_with_vad_parameters(self):
        """Test configuration with custom VAD parameters."""
        from voice_pipeline.providers.asr.faster_whisper import FasterWhisperConfig

        vad_params = {
            "threshold": 0.5,
            "min_silence_duration_ms": 500,
        }

        config = FasterWhisperConfig(
            vad_filter=True,
            vad_parameters=vad_params,
        )

        assert config.vad_parameters == vad_params


# =============================================================================
# Model Enum Tests
# =============================================================================


class TestModelEnums:
    """Tests for model and compute type enums."""

    def test_whisper_model_sizes(self):
        """Test all Whisper model sizes."""
        from voice_pipeline.providers.asr.faster_whisper import FasterWhisperModel

        assert FasterWhisperModel.TINY.value == "tiny"
        assert FasterWhisperModel.BASE.value == "base"
        assert FasterWhisperModel.SMALL.value == "small"
        assert FasterWhisperModel.MEDIUM.value == "medium"
        assert FasterWhisperModel.LARGE_V3.value == "large-v3"
        assert FasterWhisperModel.DISTIL_LARGE_V3.value == "distil-large-v3"

    def test_compute_types(self):
        """Test all compute types."""
        from voice_pipeline.providers.asr.faster_whisper import ComputeType

        assert ComputeType.INT8.value == "int8"
        assert ComputeType.FLOAT16.value == "float16"
        assert ComputeType.FLOAT32.value == "float32"
        assert ComputeType.AUTO.value == "auto"


# =============================================================================
# Provider Initialization Tests
# =============================================================================


class TestFasterWhisperProviderInit:
    """Tests for provider initialization."""

    def test_init_with_config(self):
        """Test initialization with config object."""
        from voice_pipeline.providers.asr.faster_whisper import (
            FasterWhisperProvider,
            FasterWhisperConfig,
        )

        config = FasterWhisperConfig(model="tiny", language="en")
        provider = FasterWhisperProvider(config=config)

        assert provider._asr_config.model == "tiny"
        assert provider._asr_config.language == "en"
        assert provider._model is None

    def test_init_with_shortcuts(self):
        """Test initialization with shortcut parameters."""
        from voice_pipeline.providers.asr.faster_whisper import FasterWhisperProvider

        provider = FasterWhisperProvider(
            model="base",
            language="pt",
            device="cpu",
            compute_type="int8",
            beam_size=3,
            vad_filter=True,
        )

        assert provider._asr_config.model == "base"
        assert provider._asr_config.language == "pt"
        assert provider._asr_config.device == "cpu"
        assert provider._asr_config.compute_type == "int8"
        assert provider._asr_config.beam_size == 3
        assert provider._asr_config.vad_filter is True

    def test_default_init(self):
        """Test default initialization."""
        from voice_pipeline.providers.asr.faster_whisper import FasterWhisperProvider

        provider = FasterWhisperProvider()

        assert provider._asr_config.model == "small"
        assert provider._asr_config.device == "cpu"
        assert provider._asr_config.compute_type == "int8"

    def test_provider_name(self):
        """Test provider name attributes."""
        from voice_pipeline.providers.asr.faster_whisper import FasterWhisperProvider

        provider = FasterWhisperProvider()

        assert provider.provider_name == "faster-whisper"
        assert provider.name == "FasterWhisper"

    def test_sample_rate(self):
        """Test sample rate property."""
        from voice_pipeline.providers.asr.faster_whisper import FasterWhisperProvider

        provider = FasterWhisperProvider()
        assert provider.sample_rate == 16000


# =============================================================================
# Health Check Tests
# =============================================================================


class TestHealthCheck:
    """Tests for health check."""

    @pytest.mark.asyncio
    async def test_health_check_not_connected(self):
        """Test health check when not connected."""
        from voice_pipeline.providers.asr.faster_whisper import FasterWhisperProvider

        provider = FasterWhisperProvider()
        result = await provider._do_health_check()

        assert result.status.value == "unhealthy"
        assert "not loaded" in result.message.lower()


# =============================================================================
# Transcription Tests (Mocked)
# =============================================================================


class TestTranscription:
    """Tests for transcription (mocked)."""

    @pytest.mark.asyncio
    async def test_transcribe_not_connected(self):
        """Test transcription fails when not connected."""
        from voice_pipeline.providers.asr.faster_whisper import FasterWhisperProvider

        provider = FasterWhisperProvider()

        with pytest.raises(RuntimeError, match="not loaded"):
            await provider.transcribe(b"\x00" * 1000)

    @pytest.mark.asyncio
    async def test_transcribe_stream_not_connected(self):
        """Test streaming transcription fails when not connected."""
        from voice_pipeline.providers.asr.faster_whisper import FasterWhisperProvider

        provider = FasterWhisperProvider()

        async def audio_gen():
            yield b"\x00" * 1000

        with pytest.raises(RuntimeError, match="not loaded"):
            async for _ in provider.transcribe_stream(audio_gen()):
                pass


# =============================================================================
# Repr Tests
# =============================================================================


class TestRepr:
    """Tests for string representation."""

    def test_repr(self):
        """Test string representation."""
        from voice_pipeline.providers.asr.faster_whisper import FasterWhisperProvider

        provider = FasterWhisperProvider(
            model="small",
            language="pt",
            device="cpu",
            compute_type="int8",
        )

        repr_str = repr(provider)

        assert "FasterWhisperProvider" in repr_str
        assert "small" in repr_str
        assert "pt" in repr_str
        assert "cpu" in repr_str
        assert "int8" in repr_str


# =============================================================================
# Integration Test (Skipped by default)
# =============================================================================


@pytest.mark.skipif(not _has_faster_whisper(), reason="faster-whisper not installed")
class TestIntegrationWithLibrary:
    """Integration tests that require faster-whisper installed."""

    @pytest.mark.asyncio
    async def test_connect_and_health_check(self):
        """Test connection and health check with real model."""
        from voice_pipeline.providers.asr.faster_whisper import FasterWhisperProvider

        provider = FasterWhisperProvider(
            model="tiny",  # Smallest, fastest to load
            device="cpu",
            compute_type="int8",
        )

        await provider.connect()

        try:
            result = await provider._do_health_check()
            assert result.status.value == "healthy"
            assert "tiny" in result.details.get("model", "")
        finally:
            await provider.disconnect()


@pytest.mark.skip(reason="Requires model download and takes time")
class TestFullIntegration:
    """Full integration tests (require model download)."""

    @pytest.mark.asyncio
    async def test_transcribe_silence(self):
        """Test transcription of silence."""
        from voice_pipeline.providers.asr.faster_whisper import FasterWhisperProvider

        provider = FasterWhisperProvider(
            model="tiny",
            device="cpu",
            compute_type="int8",
        )

        await provider.connect()

        try:
            # 1 second of silence
            audio_bytes = b"\x00" * (16000 * 2)  # 16kHz, 16-bit

            result = await provider.transcribe(audio_bytes)

            assert result.is_final is True
            # Silence should produce empty or minimal text
        finally:
            await provider.disconnect()

    @pytest.mark.asyncio
    async def test_transcribe_with_vad(self):
        """Test transcription with VAD filter."""
        from voice_pipeline.providers.asr.faster_whisper import FasterWhisperProvider

        provider = FasterWhisperProvider(
            model="tiny",
            device="cpu",
            vad_filter=True,
        )

        await provider.connect()

        try:
            # Generate audio with sine wave (speech-like)
            sample_rate = 16000
            duration = 1.0
            t = np.linspace(0, duration, int(sample_rate * duration), dtype=np.float32)
            audio = (np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)
            audio_bytes = audio.tobytes()

            result = await provider.transcribe(audio_bytes)

            assert result.is_final is True
        finally:
            await provider.disconnect()
