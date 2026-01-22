"""
Unit tests for Distil-Whisper ASR implementation.

Tests cover:
- Availability detection
- Initialization
- Array transcription
- Stream transcription
- Error handling
- Statistics
"""

import asyncio
import pytest
import numpy as np
from unittest.mock import Mock, patch, AsyncMock


@pytest.fixture
def sample_audio():
    """Generate sample audio data (1 second @ 16kHz, 440Hz sine wave)."""
    sample_rate = 16000
    duration = 1.0
    t = np.linspace(0, duration, int(sample_rate * duration))
    audio = np.sin(2 * np.pi * 440 * t).astype(np.float32) * 0.3
    return audio


@pytest.fixture
def sample_audio_int16():
    """Generate sample audio as int16 (needs normalization)."""
    sample_rate = 16000
    duration = 1.0
    t = np.linspace(0, duration, int(sample_rate * duration))
    audio = (np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)
    return audio


class TestDistilWhisperAvailability:
    """Test availability detection."""

    def test_availability_check(self):
        """Test is_distilwhisper_available function."""
        from src.ai.asr_distilwhisper import is_distilwhisper_available

        # Should return True or False depending on installation
        result = is_distilwhisper_available()
        assert isinstance(result, bool)


@pytest.mark.skipif(
    not pytest.importorskip("faster_whisper", reason="faster-whisper not installed"),
    reason="faster-whisper library not available",
)
class TestDistilWhisperASRWithLibrary:
    """Tests that require faster-whisper library."""

    @patch('src.ai.asr_distilwhisper.WhisperModel')
    def test_initialization_default(self, mock_whisper_model):
        """Test ASR initialization with default parameters."""
        from src.ai.asr_distilwhisper import DistilWhisperASR

        mock_model = Mock()
        mock_whisper_model.return_value = mock_model

        asr = DistilWhisperASR()

        # Should use PT-BR model by default for Portuguese
        assert asr.model_name == "freds0/distil-whisper-large-v3-ptbr"
        assert asr.language == "pt"
        assert asr.device == "cpu"
        assert asr.compute_type == "int8"
        assert asr.transcriptions_count == 0

        mock_whisper_model.assert_called_once()

    @patch('src.ai.asr_distilwhisper.WhisperModel')
    def test_initialization_custom_model(self, mock_whisper_model):
        """Test ASR initialization with custom model."""
        from src.ai.asr_distilwhisper import DistilWhisperASR

        mock_model = Mock()
        mock_whisper_model.return_value = mock_model

        asr = DistilWhisperASR(
            model="distil-large-v2",
            language="en",
            device="cuda",
            compute_type="float16",
        )

        assert asr.model_name == "distil-large-v2"
        assert asr.language == "en"
        assert asr.device == "cuda"
        assert asr.compute_type == "float16"

    @patch('src.ai.asr_distilwhisper.WhisperModel')
    def test_transcribe_array_success(self, mock_whisper_model, sample_audio):
        """Test successful array transcription."""
        from src.ai.asr_distilwhisper import DistilWhisperASR

        # Mock segment
        mock_segment = Mock()
        mock_segment.text = "olá mundo"

        # Mock info
        mock_info = Mock()
        mock_info.language = "pt"
        mock_info.language_probability = 0.95

        mock_model = Mock()
        mock_model.transcribe = Mock(return_value=([mock_segment], mock_info))
        mock_whisper_model.return_value = mock_model

        asr = DistilWhisperASR(model="distil-large-v3", language="pt")
        result = asr.transcribe_array(sample_audio)

        assert result == "olá mundo"
        assert asr.transcriptions_count == 1

    @patch('src.ai.asr_distilwhisper.WhisperModel')
    def test_transcribe_array_multiple_segments(self, mock_whisper_model, sample_audio):
        """Test transcription with multiple segments."""
        from src.ai.asr_distilwhisper import DistilWhisperASR

        # Mock multiple segments
        segment1 = Mock()
        segment1.text = "olá"
        segment2 = Mock()
        segment2.text = "mundo"

        mock_info = Mock()
        mock_info.language = "pt"
        mock_info.language_probability = 0.95

        mock_model = Mock()
        mock_model.transcribe = Mock(return_value=([segment1, segment2], mock_info))
        mock_whisper_model.return_value = mock_model

        asr = DistilWhisperASR()
        result = asr.transcribe_array(sample_audio)

        assert result == "olá mundo"
        assert asr.transcriptions_count == 1

    @patch('src.ai.asr_distilwhisper.WhisperModel')
    def test_transcribe_array_no_speech(self, mock_whisper_model, sample_audio):
        """Test transcription with no speech detected."""
        from src.ai.asr_distilwhisper import DistilWhisperASR

        mock_info = Mock()
        mock_info.language = "pt"
        mock_info.language_probability = 0.95

        mock_model = Mock()
        mock_model.transcribe = Mock(return_value=([], mock_info))
        mock_whisper_model.return_value = mock_model

        asr = DistilWhisperASR()
        result = asr.transcribe_array(sample_audio)

        assert result is None
        assert asr.transcriptions_count == 1

    @patch('src.ai.asr_distilwhisper.WhisperModel')
    def test_transcribe_array_empty_audio(self, mock_whisper_model):
        """Test transcription with empty audio."""
        from src.ai.asr_distilwhisper import DistilWhisperASR

        mock_model = Mock()
        mock_whisper_model.return_value = mock_model

        asr = DistilWhisperASR()

        # Empty array
        result = asr.transcribe_array(np.array([]))
        assert result is None

        # None
        result = asr.transcribe_array(None)
        assert result is None

    @patch('src.ai.asr_distilwhisper.WhisperModel')
    def test_transcribe_array_int16_normalization(self, mock_whisper_model, sample_audio_int16):
        """Test automatic normalization of int16 audio."""
        from src.ai.asr_distilwhisper import DistilWhisperASR

        mock_segment = Mock()
        mock_segment.text = "test"

        mock_info = Mock()
        mock_info.language = "pt"
        mock_info.language_probability = 0.95

        mock_model = Mock()
        mock_model.transcribe = Mock(return_value=([mock_segment], mock_info))
        mock_whisper_model.return_value = mock_model

        asr = DistilWhisperASR()
        result = asr.transcribe_array(sample_audio_int16)

        # Should normalize and transcribe
        assert result == "test"

        # Check that transcribe was called with float32 normalized audio
        call_args = mock_model.transcribe.call_args[0][0]
        assert call_args.dtype == np.float32
        assert call_args.max() <= 1.0
        assert call_args.min() >= -1.0

    @patch('src.ai.asr_distilwhisper.WhisperModel')
    def test_transcribe_array_error_handling(self, mock_whisper_model, sample_audio):
        """Test error handling during transcription."""
        from src.ai.asr_distilwhisper import DistilWhisperASR

        mock_model = Mock()
        mock_model.transcribe = Mock(side_effect=Exception("Transcription failed"))
        mock_whisper_model.return_value = mock_model

        asr = DistilWhisperASR()
        result = asr.transcribe_array(sample_audio)

        # Should return None on error
        assert result is None

    @patch('src.ai.asr_distilwhisper.WhisperModel')
    @pytest.mark.asyncio
    async def test_transcribe_stream_single_chunk(self, mock_whisper_model, sample_audio):
        """Test streaming transcription with single chunk."""
        from src.ai.asr_distilwhisper import DistilWhisperASR, ASRResult

        mock_segment = Mock()
        mock_segment.text = "streaming test"

        mock_info = Mock()
        mock_info.language = "pt"
        mock_info.language_probability = 0.95

        mock_model = Mock()
        mock_model.transcribe = Mock(return_value=([mock_segment], mock_info))
        mock_whisper_model.return_value = mock_model

        asr = DistilWhisperASR()

        # Create async iterator with large enough chunk
        async def audio_generator():
            # Generate 5 seconds of audio (chunk_duration_s default)
            long_audio = np.tile(sample_audio, 5)
            yield long_audio

        results = []
        async for result in asr.transcribe_stream(audio_generator()):
            results.append(result)

        # Should have at least one result (partial when buffer filled)
        assert len(results) >= 1
        assert results[0].text == "streaming test"
        assert results[0].is_partial is True

    @patch('src.ai.asr_distilwhisper.WhisperModel')
    @pytest.mark.asyncio
    async def test_transcribe_stream_multiple_chunks(self, mock_whisper_model, sample_audio):
        """Test streaming transcription with multiple chunks."""
        from src.ai.asr_distilwhisper import DistilWhisperASR

        mock_segment = Mock()
        mock_segment.text = "chunk"

        mock_info = Mock()
        mock_info.language = "pt"
        mock_info.language_probability = 0.95

        mock_model = Mock()
        mock_model.transcribe = Mock(return_value=([mock_segment], mock_info))
        mock_whisper_model.return_value = mock_model

        asr = DistilWhisperASR()

        # Create async iterator with multiple small chunks
        async def audio_generator():
            # Generate 3 chunks of 2 seconds each (> chunk_duration_s)
            for _ in range(3):
                chunk = np.tile(sample_audio, 2)
                yield chunk

        results = []
        async for result in asr.transcribe_stream(audio_generator(), chunk_duration_s=1.5):
            results.append(result)

        # Should have multiple results (partials + final)
        assert len(results) >= 3
        assert all(r.text == "chunk" for r in results)

    @patch('src.ai.asr_distilwhisper.WhisperModel')
    @pytest.mark.asyncio
    async def test_transcribe_stream_empty(self, mock_whisper_model):
        """Test streaming transcription with no audio."""
        from src.ai.asr_distilwhisper import DistilWhisperASR

        mock_model = Mock()
        mock_whisper_model.return_value = mock_model

        asr = DistilWhisperASR()

        async def empty_generator():
            return
            yield  # Make it a generator

        results = []
        async for result in asr.transcribe_stream(empty_generator()):
            results.append(result)

        assert len(results) == 0

    @patch('src.ai.asr_distilwhisper.WhisperModel')
    def test_get_stats(self, mock_whisper_model):
        """Test statistics retrieval."""
        from src.ai.asr_distilwhisper import DistilWhisperASR

        mock_model = Mock()
        mock_whisper_model.return_value = mock_model

        asr = DistilWhisperASR(
            model="distil-large-v3",
            language="en",
            device="cuda",
            compute_type="float16",
        )

        stats = asr.get_stats()

        assert stats["model"] == "distil-large-v3"
        assert stats["language"] == "en"
        assert stats["device"] == "cuda"
        assert stats["compute_type"] == "float16"
        assert stats["transcriptions_count"] == 0


class TestDistilWhisperASRWithoutLibrary:
    """Tests that work without faster-whisper library."""

    @patch('src.ai.asr_distilwhisper.FASTER_WHISPER_AVAILABLE', False)
    def test_initialization_without_library(self):
        """Test initialization fails gracefully without library."""
        from src.ai.asr_distilwhisper import DistilWhisperASR

        with pytest.raises(RuntimeError, match="faster-whisper not installed"):
            DistilWhisperASR()


@pytest.mark.benchmark
@pytest.mark.skipif(
    not pytest.importorskip("faster_whisper", reason="faster-whisper not installed"),
    reason="Benchmark requires faster-whisper library",
)
class TestDistilWhisperASRPerformance:
    """Performance benchmarks (optional, run with: pytest -m benchmark)."""

    @patch('src.ai.asr_distilwhisper.WhisperModel')
    def test_transcription_latency(self, mock_whisper_model, sample_audio, benchmark):
        """Benchmark transcription latency."""
        from src.ai.asr_distilwhisper import DistilWhisperASR

        mock_segment = Mock()
        mock_segment.text = "benchmark test"

        mock_info = Mock()
        mock_info.language = "pt"
        mock_info.language_probability = 0.95

        mock_model = Mock()
        mock_model.transcribe = Mock(return_value=([mock_segment], mock_info))
        mock_whisper_model.return_value = mock_model

        asr = DistilWhisperASR()

        # Benchmark
        result = benchmark(asr.transcribe_array, sample_audio)
        assert result == "benchmark test"
