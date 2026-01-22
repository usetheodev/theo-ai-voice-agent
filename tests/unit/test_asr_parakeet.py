"""
Unit tests for Parakeet TDT ASR implementation.

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
from unittest.mock import Mock, patch, AsyncMock, MagicMock


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


class TestParakeetAvailability:
    """Test availability detection."""

    def test_availability_check(self):
        """Test is_parakeet_available function."""
        from src.ai.asr_parakeet import is_parakeet_available

        # Should return True or False depending on installation
        result = is_parakeet_available()
        assert isinstance(result, bool)


@pytest.mark.skipif(
    not pytest.importorskip("nemo.collections.asr", reason="nemo_toolkit not installed"),
    reason="NeMo toolkit not available",
)
class TestParakeetASRWithLibrary:
    """Tests that require NeMo toolkit."""

    @patch('src.ai.asr_parakeet.nemo_asr.models.ASRModel.from_pretrained')
    @patch('src.ai.asr_parakeet.torch.cuda.is_available')
    def test_initialization_auto_gpu(self, mock_cuda, mock_from_pretrained):
        """Test ASR initialization with GPU auto-detection."""
        from src.ai.asr_parakeet import ParakeetASR

        mock_cuda.return_value = True
        mock_model = Mock()
        mock_model.to = Mock(return_value=mock_model)
        mock_model.eval = Mock(return_value=mock_model)
        mock_from_pretrained.return_value = mock_model

        asr = ParakeetASR()

        assert asr.model_name == "nvidia/parakeet-tdt-0.6b-v3"
        assert asr.device == "cuda"
        assert asr.use_onnx is False
        assert asr.transcriptions_count == 0

        mock_from_pretrained.assert_called_once()
        mock_model.to.assert_called_once_with("cuda")
        mock_model.eval.assert_called_once()

    @patch('src.ai.asr_parakeet.nemo_asr.models.ASRModel.from_pretrained')
    @patch('src.ai.asr_parakeet.torch.cuda.is_available')
    def test_initialization_auto_cpu(self, mock_cuda, mock_from_pretrained):
        """Test ASR initialization with CPU auto-detection."""
        from src.ai.asr_parakeet import ParakeetASR

        mock_cuda.return_value = False
        mock_model = Mock()
        mock_from_pretrained.return_value = mock_model

        asr = ParakeetASR()

        assert asr.device == "cpu"
        mock_from_pretrained.assert_called_once()

    @patch('src.ai.asr_parakeet.nemo_asr.models.ASRModel.from_pretrained')
    def test_initialization_custom_model(self, mock_from_pretrained):
        """Test ASR initialization with custom model."""
        from src.ai.asr_parakeet import ParakeetASR

        mock_model = Mock()
        mock_from_pretrained.return_value = mock_model

        asr = ParakeetASR(
            model="nvidia/parakeet-tdt-1.1b",
            device="cpu",
            use_onnx=True,
        )

        assert asr.model_name == "nvidia/parakeet-tdt-1.1b"
        assert asr.device == "cpu"
        assert asr.use_onnx is True

    @patch('src.ai.asr_parakeet.nemo_asr.models.ASRModel.from_pretrained')
    @patch('src.ai.asr_parakeet.tempfile.NamedTemporaryFile')
    @patch('src.ai.asr_parakeet.sf.write')
    @patch('src.ai.asr_parakeet.os.unlink')
    def test_transcribe_array_success(
        self,
        mock_unlink,
        mock_sf_write,
        mock_temp,
        mock_from_pretrained,
        sample_audio
    ):
        """Test successful array transcription."""
        from src.ai.asr_parakeet import ParakeetASR

        # Mock temporary file
        mock_temp_file = Mock()
        mock_temp_file.name = '/tmp/test_audio.wav'
        mock_temp_file.__enter__ = Mock(return_value=mock_temp_file)
        mock_temp_file.__exit__ = Mock(return_value=False)
        mock_temp.return_value = mock_temp_file

        # Mock transcription result
        mock_output = Mock()
        mock_output.text = "olá mundo"

        mock_model = Mock()
        mock_model.transcribe = Mock(return_value=[mock_output])
        mock_from_pretrained.return_value = mock_model

        asr = ParakeetASR(device="cpu")
        result = asr.transcribe_array(sample_audio)

        assert result == "olá mundo"
        assert asr.transcriptions_count == 1
        mock_model.transcribe.assert_called_once()
        mock_unlink.assert_called_once()

    @patch('src.ai.asr_parakeet.nemo_asr.models.ASRModel.from_pretrained')
    def test_transcribe_array_empty_audio(self, mock_from_pretrained):
        """Test transcription with empty audio."""
        from src.ai.asr_parakeet import ParakeetASR

        mock_model = Mock()
        mock_from_pretrained.return_value = mock_model

        asr = ParakeetASR(device="cpu")

        # Empty array
        result = asr.transcribe_array(np.array([]))
        assert result is None

        # None
        result = asr.transcribe_array(None)
        assert result is None

    @patch('src.ai.asr_parakeet.nemo_asr.models.ASRModel.from_pretrained')
    @patch('src.ai.asr_parakeet.tempfile.NamedTemporaryFile')
    @patch('src.ai.asr_parakeet.sf.write')
    @patch('src.ai.asr_parakeet.os.unlink')
    def test_transcribe_array_int16_normalization(
        self,
        mock_unlink,
        mock_sf_write,
        mock_temp,
        mock_from_pretrained,
        sample_audio_int16
    ):
        """Test automatic normalization of int16 audio."""
        from src.ai.asr_parakeet import ParakeetASR

        mock_temp_file = Mock()
        mock_temp_file.name = '/tmp/test_audio.wav'
        mock_temp_file.__enter__ = Mock(return_value=mock_temp_file)
        mock_temp_file.__exit__ = Mock(return_value=False)
        mock_temp.return_value = mock_temp_file

        mock_output = Mock()
        mock_output.text = "test"

        mock_model = Mock()
        mock_model.transcribe = Mock(return_value=[mock_output])
        mock_from_pretrained.return_value = mock_model

        asr = ParakeetASR(device="cpu")
        result = asr.transcribe_array(sample_audio_int16)

        # Should normalize and transcribe
        assert result == "test"

        # Check that sf.write was called with float32 normalized audio
        call_args = mock_sf_write.call_args[0]
        audio_written = call_args[1]
        assert audio_written.dtype == np.float32
        assert audio_written.max() <= 1.0
        assert audio_written.min() >= -1.0

    @patch('src.ai.asr_parakeet.nemo_asr.models.ASRModel.from_pretrained')
    @patch('src.ai.asr_parakeet.tempfile.NamedTemporaryFile')
    def test_transcribe_array_no_speech(
        self,
        mock_temp,
        mock_from_pretrained,
        sample_audio
    ):
        """Test transcription with no speech detected."""
        from src.ai.asr_parakeet import ParakeetASR

        mock_temp_file = Mock()
        mock_temp_file.name = '/tmp/test_audio.wav'
        mock_temp_file.__enter__ = Mock(return_value=mock_temp_file)
        mock_temp_file.__exit__ = Mock(return_value=False)
        mock_temp.return_value = mock_temp_file

        # Empty output
        mock_output = Mock()
        mock_output.text = ""

        mock_model = Mock()
        mock_model.transcribe = Mock(return_value=[mock_output])
        mock_from_pretrained.return_value = mock_model

        asr = ParakeetASR(device="cpu")
        result = asr.transcribe_array(sample_audio)

        assert result is None
        assert asr.transcriptions_count == 1

    @patch('src.ai.asr_parakeet.nemo_asr.models.ASRModel.from_pretrained')
    @patch('src.ai.asr_parakeet.tempfile.NamedTemporaryFile')
    def test_transcribe_array_error_handling(
        self,
        mock_temp,
        mock_from_pretrained,
        sample_audio
    ):
        """Test error handling during transcription."""
        from src.ai.asr_parakeet import ParakeetASR

        mock_temp_file = Mock()
        mock_temp_file.name = '/tmp/test_audio.wav'
        mock_temp_file.__enter__ = Mock(return_value=mock_temp_file)
        mock_temp_file.__exit__ = Mock(return_value=False)
        mock_temp.return_value = mock_temp_file

        mock_model = Mock()
        mock_model.transcribe = Mock(side_effect=Exception("Transcription failed"))
        mock_from_pretrained.return_value = mock_model

        asr = ParakeetASR(device="cpu")
        result = asr.transcribe_array(sample_audio)

        # Should return None on error
        assert result is None

    @patch('src.ai.asr_parakeet.nemo_asr.models.ASRModel.from_pretrained')
    @pytest.mark.asyncio
    async def test_transcribe_stream_single_chunk(
        self,
        mock_from_pretrained,
        sample_audio
    ):
        """Test streaming transcription with single chunk."""
        from src.ai.asr_parakeet import ParakeetASR, ASRResult

        mock_output = Mock()
        mock_output.text = "streaming test"

        mock_model = Mock()
        mock_model.transcribe = Mock(return_value=[mock_output])
        mock_from_pretrained.return_value = mock_model

        asr = ParakeetASR(device="cpu")

        # Create async iterator with large enough chunk
        async def audio_generator():
            # Generate 3 seconds of audio (> chunk_duration_s default of 2s)
            long_audio = np.tile(sample_audio, 3)
            yield long_audio

        results = []
        async for result in asr.transcribe_stream(audio_generator()):
            results.append(result)

        # Should have at least one result
        assert len(results) >= 1
        assert results[0].text == "streaming test"
        assert results[0].is_partial is True

    @patch('src.ai.asr_parakeet.nemo_asr.models.ASRModel.from_pretrained')
    @pytest.mark.asyncio
    async def test_transcribe_stream_empty(self, mock_from_pretrained):
        """Test streaming transcription with no audio."""
        from src.ai.asr_parakeet import ParakeetASR

        mock_model = Mock()
        mock_from_pretrained.return_value = mock_model

        asr = ParakeetASR(device="cpu")

        async def empty_generator():
            return
            yield  # Make it a generator

        results = []
        async for result in asr.transcribe_stream(empty_generator()):
            results.append(result)

        assert len(results) == 0

    @patch('src.ai.asr_parakeet.nemo_asr.models.ASRModel.from_pretrained')
    @patch('src.ai.asr_parakeet.torch.cuda.is_available')
    def test_get_stats(self, mock_cuda, mock_from_pretrained):
        """Test statistics retrieval."""
        from src.ai.asr_parakeet import ParakeetASR

        mock_cuda.return_value = True
        mock_model = Mock()
        mock_model.to = Mock(return_value=mock_model)
        mock_model.eval = Mock(return_value=mock_model)
        mock_from_pretrained.return_value = mock_model

        asr = ParakeetASR(
            model="nvidia/parakeet-tdt-1.1b",
            device="cuda",
            use_onnx=True,
        )

        stats = asr.get_stats()

        assert stats["model"] == "nvidia/parakeet-tdt-1.1b"
        assert stats["device"] == "cuda"
        assert stats["use_onnx"] is True
        assert stats["transcriptions_count"] == 0
        assert "cuda_available" in stats


class TestParakeetASRWithoutLibrary:
    """Tests that work without NeMo toolkit."""

    @patch('src.ai.asr_parakeet.NEMO_AVAILABLE', False)
    def test_initialization_without_library(self):
        """Test initialization fails gracefully without library."""
        from src.ai.asr_parakeet import ParakeetASR

        with pytest.raises(RuntimeError, match="NeMo toolkit not installed"):
            ParakeetASR()


@pytest.mark.benchmark
@pytest.mark.skipif(
    not pytest.importorskip("nemo.collections.asr", reason="nemo_toolkit not installed"),
    reason="Benchmark requires NeMo toolkit",
)
class TestParakeetASRPerformance:
    """Performance benchmarks (optional, run with: pytest -m benchmark)."""

    @patch('src.ai.asr_parakeet.nemo_asr.models.ASRModel.from_pretrained')
    @patch('src.ai.asr_parakeet.tempfile.NamedTemporaryFile')
    @patch('src.ai.asr_parakeet.sf.write')
    @patch('src.ai.asr_parakeet.os.unlink')
    def test_transcription_latency(
        self,
        mock_unlink,
        mock_sf_write,
        mock_temp,
        mock_from_pretrained,
        sample_audio,
        benchmark
    ):
        """Benchmark transcription latency."""
        from src.ai.asr_parakeet import ParakeetASR

        mock_temp_file = Mock()
        mock_temp_file.name = '/tmp/test_audio.wav'
        mock_temp_file.__enter__ = Mock(return_value=mock_temp_file)
        mock_temp_file.__exit__ = Mock(return_value=False)
        mock_temp.return_value = mock_temp_file

        mock_output = Mock()
        mock_output.text = "benchmark test"

        mock_model = Mock()
        mock_model.transcribe = Mock(return_value=[mock_output])
        mock_from_pretrained.return_value = mock_model

        asr = ParakeetASR(device="cpu")

        # Benchmark
        result = benchmark(asr.transcribe_array, sample_audio)
        assert result == "benchmark test"
