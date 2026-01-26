"""Tests for NVIDIA Nemotron Speech ASR provider."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import numpy as np


# =============================================================================
# Skip if dependencies not installed
# =============================================================================


def _has_nemo():
    """Check if NeMo is available."""
    try:
        import nemo.collections.asr as nemo_asr
        return True
    except ImportError:
        return False


def _has_torch():
    """Check if PyTorch is available."""
    try:
        import torch
        return True
    except ImportError:
        return False


# =============================================================================
# Config Tests (no dependencies required)
# =============================================================================


class TestNemotronASRConfig:
    """Tests for NemotronASRConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        from voice_pipeline.providers.asr.nemotron import (
            NemotronASRConfig,
            ChunkLatencyMode,
        )

        config = NemotronASRConfig()

        assert config.model == "nvidia/nemotron-speech-streaming-en-0.6b"
        assert config.latency_mode == ChunkLatencyMode.LOW
        assert config.device == "cuda"
        assert config.sample_rate == 16000
        assert config.compute_timestamps is False
        assert config.batch_size == 1

    def test_custom_config(self):
        """Test custom configuration."""
        from voice_pipeline.providers.asr.nemotron import (
            NemotronASRConfig,
            ChunkLatencyMode,
        )

        config = NemotronASRConfig(
            latency_mode=ChunkLatencyMode.ULTRA_LOW,
            device="cuda:1",
            compute_timestamps=True,
        )

        assert config.latency_mode == ChunkLatencyMode.ULTRA_LOW
        assert config.device == "cuda:1"
        assert config.compute_timestamps is True

    def test_latency_modes(self):
        """Test all latency modes."""
        from voice_pipeline.providers.asr.nemotron import ChunkLatencyMode

        assert ChunkLatencyMode.ULTRA_LOW.value == "80ms"
        assert ChunkLatencyMode.LOW.value == "160ms"
        assert ChunkLatencyMode.BALANCED.value == "560ms"
        assert ChunkLatencyMode.HIGH_ACCURACY.value == "1120ms"


# =============================================================================
# Provider Initialization Tests
# =============================================================================


class TestNemotronASRProviderInit:
    """Tests for provider initialization."""

    def test_init_with_config(self):
        """Test initialization with config object."""
        from voice_pipeline.providers.asr.nemotron import (
            NemotronASRProvider,
            NemotronASRConfig,
            ChunkLatencyMode,
        )

        config = NemotronASRConfig(latency_mode=ChunkLatencyMode.BALANCED)
        provider = NemotronASRProvider(config=config)

        assert provider._asr_config.latency_mode == ChunkLatencyMode.BALANCED
        assert provider._model is None

    def test_init_with_shortcuts(self):
        """Test initialization with shortcut parameters."""
        from voice_pipeline.providers.asr.nemotron import (
            NemotronASRProvider,
            ChunkLatencyMode,
        )

        provider = NemotronASRProvider(
            latency_mode="ultra_low",
            device="cuda:0",
        )

        assert provider._asr_config.latency_mode == ChunkLatencyMode.ULTRA_LOW
        assert provider._asr_config.device == "cuda:0"

    def test_default_init(self):
        """Test default initialization."""
        from voice_pipeline.providers.asr.nemotron import (
            NemotronASRProvider,
            ChunkLatencyMode,
        )

        provider = NemotronASRProvider()

        assert provider._asr_config.model == "nvidia/nemotron-speech-streaming-en-0.6b"
        assert provider._asr_config.latency_mode == ChunkLatencyMode.LOW

    def test_provider_name(self):
        """Test provider name attributes."""
        from voice_pipeline.providers.asr.nemotron import NemotronASRProvider

        provider = NemotronASRProvider()

        assert provider.provider_name == "nemotron-asr"
        assert provider.name == "NemotronASR"


# =============================================================================
# Chunk Size Tests
# =============================================================================


class TestChunkSizes:
    """Tests for chunk size calculations."""

    def test_chunk_size_ultra_low(self):
        """Test ultra-low latency chunk size."""
        from voice_pipeline.providers.asr.nemotron import (
            NemotronASRProvider,
            ChunkLatencyMode,
        )

        provider = NemotronASRProvider(latency_mode=ChunkLatencyMode.ULTRA_LOW)

        assert provider.chunk_size_ms == 80
        assert provider.chunk_size_samples == 1280  # 80ms * 16000 / 1000
        assert provider.chunk_size_bytes == 2560  # 1280 * 2

    def test_chunk_size_low(self):
        """Test low latency chunk size."""
        from voice_pipeline.providers.asr.nemotron import (
            NemotronASRProvider,
            ChunkLatencyMode,
        )

        provider = NemotronASRProvider(latency_mode=ChunkLatencyMode.LOW)

        assert provider.chunk_size_ms == 160
        assert provider.chunk_size_samples == 2560
        assert provider.chunk_size_bytes == 5120

    def test_chunk_size_balanced(self):
        """Test balanced latency chunk size."""
        from voice_pipeline.providers.asr.nemotron import (
            NemotronASRProvider,
            ChunkLatencyMode,
        )

        provider = NemotronASRProvider(latency_mode=ChunkLatencyMode.BALANCED)

        assert provider.chunk_size_ms == 560
        assert provider.chunk_size_samples == 8960
        assert provider.chunk_size_bytes == 17920

    def test_chunk_size_high_accuracy(self):
        """Test high accuracy chunk size."""
        from voice_pipeline.providers.asr.nemotron import (
            NemotronASRProvider,
            ChunkLatencyMode,
        )

        provider = NemotronASRProvider(latency_mode=ChunkLatencyMode.HIGH_ACCURACY)

        assert provider.chunk_size_ms == 1120
        assert provider.chunk_size_samples == 17920
        assert provider.chunk_size_bytes == 35840


# =============================================================================
# Health Check Tests
# =============================================================================


class TestHealthCheck:
    """Tests for health check."""

    @pytest.mark.asyncio
    async def test_health_check_not_connected(self):
        """Test health check when not connected."""
        from voice_pipeline.providers.asr.nemotron import NemotronASRProvider

        provider = NemotronASRProvider()
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
        from voice_pipeline.providers.asr.nemotron import NemotronASRProvider

        provider = NemotronASRProvider()

        with pytest.raises(RuntimeError, match="not loaded"):
            await provider.transcribe(b"\x00" * 1000)

    @pytest.mark.asyncio
    async def test_transcribe_stream_not_connected(self):
        """Test streaming transcription fails when not connected."""
        from voice_pipeline.providers.asr.nemotron import NemotronASRProvider

        provider = NemotronASRProvider()

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
        from voice_pipeline.providers.asr.nemotron import (
            NemotronASRProvider,
            ChunkLatencyMode,
        )

        provider = NemotronASRProvider(
            latency_mode=ChunkLatencyMode.BALANCED,
            device="cuda:0",
        )

        repr_str = repr(provider)

        assert "NemotronASRProvider" in repr_str
        assert "560ms" in repr_str
        assert "cuda:0" in repr_str


# =============================================================================
# Integration Test (Skipped by default)
# =============================================================================


@pytest.mark.skip(reason="Requires GPU and model download")
class TestIntegration:
    """Integration tests (require actual hardware)."""

    @pytest.mark.asyncio
    async def test_full_transcription(self):
        """Test full transcription flow."""
        from voice_pipeline.providers.asr.nemotron import (
            NemotronASRProvider,
            ChunkLatencyMode,
        )

        provider = NemotronASRProvider(
            latency_mode=ChunkLatencyMode.LOW,
            device="cuda",
        )

        await provider.connect()

        try:
            # Generate 1 second of sine wave (440 Hz)
            sample_rate = 16000
            duration = 1.0
            t = np.linspace(0, duration, int(sample_rate * duration), dtype=np.float32)
            audio = (np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)
            audio_bytes = audio.tobytes()

            result = await provider.transcribe(audio_bytes)

            # Sine wave should produce empty or minimal transcription
            assert result.is_final is True
            assert result.language == "en"

        finally:
            await provider.disconnect()
