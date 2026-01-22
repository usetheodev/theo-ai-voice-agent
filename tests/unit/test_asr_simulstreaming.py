"""
Unit tests for SimulStreaming ASR Provider

Tests the SimulStreaming ASR implementation including:
- Initialization
- Batch transcription (WhisperASR compatible interface)
- Streaming transcription with partial results
- Statistics tracking
- Error handling
"""

import pytest
import numpy as np
from unittest.mock import Mock, patch, AsyncMock
import asyncio

# Import will be mocked if whisper-streaming not installed
try:
    from src.ai.asr_simulstreaming import SimulStreamingASR, ASRResult, is_simulstreaming_available
    SIMULSTREAMING_AVAILABLE = True
except ImportError:
    SIMULSTREAMING_AVAILABLE = False


@pytest.fixture
def sample_audio():
    """Generate sample audio for testing (1 second, 16kHz, sine wave)"""
    sample_rate = 16000
    duration = 1.0
    frequency = 440  # A4 note

    t = np.linspace(0, duration, int(sample_rate * duration))
    audio = np.sin(2 * np.pi * frequency * t).astype(np.float32) * 0.5

    return audio


@pytest.fixture
def mock_whisper_streaming():
    """Mock WhisperStreaming model"""
    mock_model = Mock()
    mock_model.reset = Mock()
    mock_model.process_audio = Mock(return_value={
        'text': 'test transcription',
        'is_partial': False,
        'confidence': 0.95
    })
    return mock_model


@pytest.mark.skipif(not SIMULSTREAMING_AVAILABLE, reason="whisper-streaming not installed")
class TestSimulStreamingASRInstallation:
    """Tests that run only when whisper-streaming is installed"""

    def test_availability_detection(self):
        """Test that is_simulstreaming_available() detects installation correctly"""
        assert is_simulstreaming_available() is True

    @patch('src.ai.asr_simulstreaming.OnlineASRProcessor')
    @patch('src.ai.asr_simulstreaming.FasterWhisperASR')
    def test_initialization(self, mock_faster_whisper, mock_online_processor):
        """Test ASR initialization"""
        asr = SimulStreamingASR(
            model="base",
            language="pt",
            min_chunk_size=1.0
        )

        assert asr.model_name == "base"
        assert asr.language == "pt"
        assert asr.min_chunk_size == 1.0
        assert asr.transcriptions_count == 0
        assert asr.partial_results_count == 0

        # Verify FasterWhisperASR was initialized with correct params
        mock_faster_whisper.assert_called_once()
        mock_online_processor.assert_called_once()


class TestSimulStreamingASRMocked:
    """Tests that work with mocked whisper-streaming (always run)"""

    @patch('src.ai.asr_simulstreaming.SIMULSTREAMING_AVAILABLE', True)
    @patch('src.ai.asr_simulstreaming.OnlineASRProcessor')
    @patch('src.ai.asr_simulstreaming.FasterWhisperASR')
    def test_transcribe_array_success(self, mock_faster_whisper, mock_online_processor, sample_audio):
        """Test successful batch transcription"""
        mock_model = Mock()
        mock_model.init = Mock()
        mock_model.insert_audio_chunk = Mock()
        mock_model.process_iter = Mock(return_value=None)
        mock_model.finish = Mock(return_value=(0.0, 1.0, 'olá mundo'))
        mock_online_processor.return_value = mock_model

        asr = SimulStreamingASR(model="base", language="pt")
        result = asr.transcribe_array(sample_audio)

        assert result == 'olá mundo'
        assert asr.transcriptions_count == 1
        mock_model.init.assert_called()
        mock_model.insert_audio_chunk.assert_called_once()
        mock_model.finish.assert_called_once()

    @patch('src.ai.asr_simulstreaming.SIMULSTREAMING_AVAILABLE', True)
    @patch('src.ai.asr_simulstreaming.OnlineASRProcessor')
    @patch('src.ai.asr_simulstreaming.FasterWhisperASR')
    def test_transcribe_array_empty_result(self, mock_faster_whisper, mock_online_processor, sample_audio):
        """Test transcription with empty result"""
        mock_model = Mock()
        mock_model.init = Mock()
        mock_model.insert_audio_chunk = Mock()
        mock_model.process_iter = Mock(return_value=None)
        mock_model.finish = Mock(return_value=(0.0, 1.0, ''))  # Empty text
        mock_online_processor.return_value = mock_model

        asr = SimulStreamingASR(model="base", language="pt")
        result = asr.transcribe_array(sample_audio)

        assert result is None
        assert asr.transcriptions_count == 0

    @patch('src.ai.asr_simulstreaming.SIMULSTREAMING_AVAILABLE', True)
    @patch('src.ai.asr_simulstreaming.OnlineASRProcessor')
    @patch('src.ai.asr_simulstreaming.FasterWhisperASR')
    def test_transcribe_array_error_handling(self, mock_faster_whisper, mock_online_processor, sample_audio):
        """Test error handling in transcription"""
        mock_model = Mock()
        mock_model.init = Mock()
        mock_model.insert_audio_chunk = Mock(side_effect=Exception("Test error"))
        mock_online_processor.return_value = mock_model

        asr = SimulStreamingASR(model="base", language="pt")
        result = asr.transcribe_array(sample_audio)

        assert result is None

    @patch('src.ai.asr_simulstreaming.SIMULSTREAMING_AVAILABLE', True)
    @patch('src.ai.asr_simulstreaming.OnlineASRProcessor')
    @patch('src.ai.asr_simulstreaming.FasterWhisperASR')
    def test_audio_normalization(self, mock_faster_whisper, mock_online_processor):
        """Test audio normalization for out-of-range values"""
        mock_model = Mock()
        mock_model.init = Mock()
        mock_model.insert_audio_chunk = Mock()
        mock_model.process_iter = Mock(return_value=None)
        mock_model.finish = Mock(return_value=(0.0, 1.0, 'test'))
        mock_online_processor.return_value = mock_model

        asr = SimulStreamingASR(model="base", language="pt")

        # Test with audio outside [-1, 1] range
        audio = np.array([1.5, -1.5, 0.5], dtype=np.float32)
        result = asr.transcribe_array(audio)

        # Verify audio was clipped
        called_audio = mock_model.insert_audio_chunk.call_args[0][0]
        assert np.all(called_audio >= -1.0)
        assert np.all(called_audio <= 1.0)

    @patch('src.ai.asr_simulstreaming.SIMULSTREAMING_AVAILABLE', True)
    @patch('src.ai.asr_simulstreaming.OnlineASRProcessor')
    @patch('src.ai.asr_simulstreaming.FasterWhisperASR')
    @pytest.mark.asyncio
    async def test_transcribe_stream_partial_results(self, mock_faster_whisper, mock_online_processor):
        """Test streaming transcription with partial results"""
        mock_model = Mock()
        mock_model.init = Mock()
        mock_model.insert_audio_chunk = Mock()

        # Simulate partial results then final
        mock_model.process_iter = Mock(side_effect=[
            (0.0, 0.5, 'olá'),  # First chunk - partial
            None,  # Second chunk - no new words yet
        ])
        mock_model.finish = Mock(return_value=(0.0, 1.0, 'olá mundo'))  # Final
        mock_online_processor.return_value = mock_model

        asr = SimulStreamingASR(model="base", language="pt")

        # Create audio iterator
        async def audio_gen():
            audio1 = np.zeros(4000, dtype=np.float32)
            audio2 = np.zeros(4000, dtype=np.float32)
            yield audio1
            yield audio2

        results = []
        async for result in asr.transcribe_stream(audio_gen()):
            results.append(result)

        assert len(results) == 2  # 1 partial + 1 final
        assert results[0].text == 'olá'
        assert results[0].is_partial is True
        assert results[1].text == 'olá mundo'
        assert results[1].is_partial is False
        assert asr.partial_results_count == 1
        assert asr.transcriptions_count == 1

    @patch('src.ai.asr_simulstreaming.SIMULSTREAMING_AVAILABLE', True)
    @patch('src.ai.asr_simulstreaming.OnlineASRProcessor')
    @patch('src.ai.asr_simulstreaming.FasterWhisperASR')
    def test_get_stats(self, mock_faster_whisper, mock_online_processor):
        """Test statistics retrieval"""
        mock_model = Mock()
        mock_model.init = Mock()
        mock_model.insert_audio_chunk = Mock()
        mock_model.process_iter = Mock(return_value=None)
        mock_model.finish = Mock(return_value=(0.0, 1.0, 'test'))
        mock_online_processor.return_value = mock_model

        asr = SimulStreamingASR(
            model="base",
            language="pt",
            min_chunk_size=1.0,
            n_threads=4
        )

        # Do a transcription
        audio = np.zeros(16000, dtype=np.float32)
        asr.transcribe_array(audio)

        stats = asr.get_stats()

        assert stats['provider'] == 'simulstreaming'
        assert stats['transcriptions_count'] == 1
        assert stats['model'] == 'base'
        assert stats['language'] == 'pt'
        assert stats['min_chunk_size'] == 1.0
        assert stats['n_threads'] == 4

    @patch('src.ai.asr_simulstreaming.SIMULSTREAMING_AVAILABLE', True)
    @patch('src.ai.asr_simulstreaming.OnlineASRProcessor')
    @patch('src.ai.asr_simulstreaming.FasterWhisperASR')
    def test_reset_state(self, mock_faster_whisper, mock_online_processor):
        """Test state reset"""
        mock_model = Mock()
        mock_model.init = Mock()
        mock_online_processor.return_value = mock_model

        asr = SimulStreamingASR(model="base", language="pt")
        asr.reset()

        # Verify model init was called (used for reset)
        assert mock_model.init.call_count >= 1

    @patch('src.ai.asr_simulstreaming.SIMULSTREAMING_AVAILABLE', True)
    @patch('src.ai.asr_simulstreaming.OnlineASRProcessor')
    @patch('src.ai.asr_simulstreaming.FasterWhisperASR')
    def test_transcribe_wav_bytes(self, mock_faster_whisper, mock_online_processor):
        """Test WAV bytes transcription (WhisperASR compatible)"""
        import wave
        import io

        mock_model = Mock()
        mock_model.init = Mock()
        mock_model.insert_audio_chunk = Mock()
        mock_model.process_iter = Mock(return_value=None)
        mock_model.finish = Mock(return_value=(0.0, 1.0, 'wav test'))
        mock_online_processor.return_value = mock_model

        asr = SimulStreamingASR(model="base", language="pt")

        # Create WAV bytes
        sample_rate = 16000
        audio = np.zeros(16000, dtype=np.int16)

        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(audio.tobytes())

        wav_bytes = wav_buffer.getvalue()

        result = asr.transcribe(wav_bytes)

        assert result == 'wav test'
        mock_model.insert_audio_chunk.assert_called_once()


class TestSimulStreamingASRUnavailable:
    """Tests for when whisper-streaming is not installed"""

    @patch('src.ai.asr_simulstreaming.SIMULSTREAMING_AVAILABLE', False)
    def test_import_error_on_init(self):
        """Test that initialization fails gracefully when whisper-streaming not available"""
        with pytest.raises(ImportError, match="whisper-streaming is not installed"):
            from src.ai.asr_simulstreaming import SimulStreamingASR
            SimulStreamingASR(model="base", language="pt")

    def test_availability_detection_when_unavailable(self):
        """Test availability detection returns False when not installed"""
        with patch('src.ai.asr_simulstreaming.SIMULSTREAMING_AVAILABLE', False):
            from src.ai.asr_simulstreaming import is_simulstreaming_available
            assert is_simulstreaming_available() is False


class TestASRResultDataclass:
    """Tests for ASRResult dataclass"""

    @patch('src.ai.asr_simulstreaming.SIMULSTREAMING_AVAILABLE', True)
    def test_asr_result_creation(self):
        """Test ASRResult creation with defaults"""
        from src.ai.asr_simulstreaming import ASRResult

        result = ASRResult(text="test text")

        assert result.text == "test text"
        assert result.is_partial is False
        assert result.confidence == 1.0
        assert result.timestamp == 0.0

    @patch('src.ai.asr_simulstreaming.SIMULSTREAMING_AVAILABLE', True)
    def test_asr_result_with_custom_values(self):
        """Test ASRResult with custom values"""
        from src.ai.asr_simulstreaming import ASRResult

        result = ASRResult(
            text="partial text",
            is_partial=True,
            confidence=0.85,
            timestamp=1.5
        )

        assert result.text == "partial text"
        assert result.is_partial is True
        assert result.confidence == 0.85
        assert result.timestamp == 1.5


# Performance/benchmark tests (optional, run separately)
@pytest.mark.benchmark
@pytest.mark.skipif(not SIMULSTREAMING_AVAILABLE, reason="whisper-streaming not installed")
class TestSimulStreamingASRPerformance:
    """Performance benchmarks for SimulStreaming ASR"""

    @patch('src.ai.asr_simulstreaming.OnlineASRProcessor')
    @patch('src.ai.asr_simulstreaming.FasterWhisperASR')
    def test_batch_transcription_speed(self, mock_faster_whisper, mock_online_processor, sample_audio, benchmark):
        """Benchmark batch transcription speed"""
        mock_model = Mock()
        mock_model.init = Mock()
        mock_model.insert_audio_chunk = Mock()
        mock_model.process_iter = Mock(return_value=None)
        mock_model.finish = Mock(return_value=(0.0, 1.0, 'benchmark test'))
        mock_online_processor.return_value = mock_model

        asr = SimulStreamingASR(model="base", language="pt")

        benchmark(asr.transcribe_array, sample_audio)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
