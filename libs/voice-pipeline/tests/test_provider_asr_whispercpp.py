"""Tests for whisper.cpp ASR provider."""

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch
import numpy as np
import pytest

from voice_pipeline.providers.asr.whispercpp import (
    WhisperCppASRProvider,
    WhisperCppASRConfig,
    WHISPER_MODEL_SIZES,
)
from voice_pipeline.providers.base import ProviderHealth
from voice_pipeline.interfaces.asr import TranscriptionResult


# Mock module for pywhispercpp
MOCK_PYWHISPERCPP_MODULE = "pywhispercpp.model"


# =============================================================================
# Test Configuration
# =============================================================================


class TestWhisperCppASRConfig:
    """Tests for WhisperCppASRConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = WhisperCppASRConfig()

        assert config.model == "base"
        assert config.model_path is None
        assert config.language is None
        assert config.n_threads is None
        assert config.sample_rate == 16000
        assert config.translate is False
        assert config.beam_size == 5
        assert config.best_of == 5
        assert config.word_timestamps is False
        assert config.temperature == 0.0
        assert config.initial_prompt is None
        assert config.no_context is False
        assert config.single_segment is False
        assert config.print_progress is False

    def test_custom_values(self):
        """Test custom configuration values."""
        config = WhisperCppASRConfig(
            model="large-v3",
            model_path="/path/to/model.bin",
            language="pt",
            n_threads=8,
            sample_rate=16000,
            translate=True,
            beam_size=10,
            best_of=10,
            word_timestamps=True,
            temperature=0.2,
            initial_prompt="Meeting transcript:",
            no_context=True,
            single_segment=True,
            print_progress=True,
        )

        assert config.model == "large-v3"
        assert config.model_path == "/path/to/model.bin"
        assert config.language == "pt"
        assert config.n_threads == 8
        assert config.translate is True
        assert config.beam_size == 10
        assert config.word_timestamps is True
        assert config.initial_prompt == "Meeting transcript:"


# =============================================================================
# Test Provider Initialization
# =============================================================================


class TestWhisperCppASRProviderInit:
    """Tests for WhisperCppASRProvider initialization."""

    def test_default_initialization(self):
        """Test initialization with default config."""
        provider = WhisperCppASRProvider()

        assert provider._asr_config.model == "base"
        assert provider._asr_config.language is None
        assert provider._model is None
        assert provider.provider_name == "whispercpp"
        assert provider.name == "WhisperCppASR"

    def test_initialization_with_config(self):
        """Test initialization with custom config."""
        config = WhisperCppASRConfig(
            model="small.en",
            n_threads=4,
            language="en",
        )
        provider = WhisperCppASRProvider(config=config)

        assert provider._asr_config.model == "small.en"
        assert provider._asr_config.n_threads == 4
        assert provider._asr_config.language == "en"

    def test_initialization_with_shortcuts(self):
        """Test initialization with shortcut parameters."""
        provider = WhisperCppASRProvider(
            model="medium",
            language="es",
            n_threads=6,
        )

        assert provider._asr_config.model == "medium"
        assert provider._asr_config.language == "es"
        assert provider._asr_config.n_threads == 6

    def test_shortcuts_override_config(self):
        """Test that shortcuts override config values."""
        config = WhisperCppASRConfig(
            model="tiny",
            language="fr",
        )
        provider = WhisperCppASRProvider(
            config=config,
            model="large",
            language="de",
        )

        assert provider._asr_config.model == "large"
        assert provider._asr_config.language == "de"

    def test_sample_rate_property(self):
        """Test sample_rate property."""
        provider = WhisperCppASRProvider()
        assert provider.sample_rate == 16000

        provider2 = WhisperCppASRProvider(
            config=WhisperCppASRConfig(sample_rate=8000)
        )
        assert provider2.sample_rate == 8000

    def test_repr(self):
        """Test string representation."""
        provider = WhisperCppASRProvider(model="base.en", language="en")
        repr_str = repr(provider)

        assert "WhisperCppASRProvider" in repr_str
        assert "base.en" in repr_str
        assert "en" in repr_str


# =============================================================================
# Test Provider Lifecycle
# =============================================================================


class TestWhisperCppASRProviderLifecycle:
    """Tests for provider lifecycle (connect/disconnect)."""

    @pytest.mark.asyncio
    async def test_connect_creates_model(self):
        """Test that connect initializes the model."""
        provider = WhisperCppASRProvider(model="base")

        mock_model = MagicMock()

        with patch(
            "pywhispercpp.model.Model",
            return_value=mock_model,
        ):
            await provider.connect()

            assert provider._model is mock_model
            assert provider._connected is True
            assert provider._executor is not None

        await provider.disconnect()

    @pytest.mark.asyncio
    async def test_connect_with_threads(self):
        """Test connect with custom thread count."""
        provider = WhisperCppASRProvider(model="tiny", n_threads=4)

        with patch(
            "pywhispercpp.model.Model"
        ) as MockModel:
            await provider.connect()
            MockModel.assert_called_once_with("tiny", n_threads=4)

        await provider.disconnect()

    @pytest.mark.asyncio
    async def test_connect_with_model_path(self):
        """Test connect with local model path."""
        provider = WhisperCppASRProvider(
            model_path="/path/to/custom_model.bin"
        )

        with patch(
            "pywhispercpp.model.Model"
        ) as MockModel:
            await provider.connect()
            MockModel.assert_called_once_with("/path/to/custom_model.bin")

        await provider.disconnect()

    @pytest.mark.asyncio
    async def test_connect_raises_without_pywhispercpp(self):
        """Test that connect raises ImportError if pywhispercpp not installed."""
        provider = WhisperCppASRProvider()

        with patch.dict("sys.modules", {"pywhispercpp.model": None}):
            with patch(
                "pywhispercpp.model.Model",
                side_effect=ImportError("No module named 'pywhispercpp'"),
            ):
                with pytest.raises(ImportError, match="pywhispercpp"):
                    await provider.connect()

    @pytest.mark.asyncio
    async def test_disconnect_cleans_up(self):
        """Test that disconnect cleans up resources."""
        provider = WhisperCppASRProvider()

        with patch("pywhispercpp.model.Model"):
            await provider.connect()
            assert provider._model is not None
            assert provider._executor is not None

            await provider.disconnect()

            assert provider._model is None
            assert provider._executor is None
            assert provider._connected is False

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test async context manager protocol."""
        provider = WhisperCppASRProvider()

        with patch("pywhispercpp.model.Model"):
            async with provider:
                assert provider._connected is True
                assert provider._model is not None

            assert provider._connected is False
            assert provider._model is None


# =============================================================================
# Test Health Check
# =============================================================================


class TestWhisperCppASRProviderHealthCheck:
    """Tests for provider health check."""

    @pytest.mark.asyncio
    async def test_health_check_unhealthy_when_not_connected(self):
        """Test health check returns unhealthy when not connected."""
        provider = WhisperCppASRProvider()

        result = await provider.health_check()

        assert result.status == ProviderHealth.UNHEALTHY
        assert "not initialized" in result.message.lower()

    @pytest.mark.asyncio
    async def test_health_check_healthy_when_model_works(self):
        """Test health check returns healthy when model is working."""
        provider = WhisperCppASRProvider(model="base")

        mock_model = MagicMock()
        mock_model.transcribe.return_value = []

        with patch(
            "pywhispercpp.model.Model",
            return_value=mock_model,
        ):
            await provider.connect()
            result = await provider.health_check()

            assert result.status == ProviderHealth.HEALTHY
            assert "base" in result.message
            mock_model.transcribe.assert_called()

        await provider.disconnect()

    @pytest.mark.asyncio
    async def test_health_check_unhealthy_on_error(self):
        """Test health check returns unhealthy on transcription error."""
        provider = WhisperCppASRProvider()

        mock_model = MagicMock()
        mock_model.transcribe.side_effect = Exception("Model error")

        with patch(
            "pywhispercpp.model.Model",
            return_value=mock_model,
        ):
            await provider.connect()
            result = await provider.health_check()

            assert result.status == ProviderHealth.UNHEALTHY
            assert "error" in result.message.lower()

        await provider.disconnect()


# =============================================================================
# Test PCM16 to Float32 Conversion
# =============================================================================


class TestWhisperCppASRProviderAudioConversion:
    """Tests for audio format conversion."""

    def test_pcm16_to_float32_basic(self):
        """Test basic PCM16 to float32 conversion."""
        provider = WhisperCppASRProvider()

        # Create test PCM16 data (silence)
        pcm_data = np.zeros(1000, dtype=np.int16).tobytes()

        result = provider._pcm16_to_float32(pcm_data)

        assert isinstance(result, np.ndarray)
        assert result.dtype == np.float32
        assert len(result) == 1000
        np.testing.assert_array_almost_equal(result, np.zeros(1000))

    def test_pcm16_to_float32_max_values(self):
        """Test conversion with max int16 values."""
        provider = WhisperCppASRProvider()

        # Max positive value
        pcm_max = np.array([32767], dtype=np.int16).tobytes()
        result_max = provider._pcm16_to_float32(pcm_max)
        assert abs(result_max[0] - 1.0) < 0.001

        # Max negative value
        pcm_min = np.array([-32768], dtype=np.int16).tobytes()
        result_min = provider._pcm16_to_float32(pcm_min)
        assert abs(result_min[0] - (-1.0)) < 0.001


# =============================================================================
# Test Transcription Stream
# =============================================================================


class TestWhisperCppASRProviderTranscribeStream:
    """Tests for transcribe_stream method."""

    @pytest.mark.asyncio
    async def test_transcribe_stream_raises_without_model(self):
        """Test that transcribe_stream raises when not connected."""
        provider = WhisperCppASRProvider()

        async def audio_gen():
            yield b"\x00" * 1000

        with pytest.raises(RuntimeError, match="not connected"):
            async for _ in provider.transcribe_stream(audio_gen()):
                pass

    @pytest.mark.asyncio
    async def test_transcribe_stream_basic(self):
        """Test basic transcription streaming."""
        provider = WhisperCppASRProvider()

        # Create mock segment
        mock_segment = MagicMock()
        mock_segment.text = " Hello, world! "
        mock_segment.t0 = 0
        mock_segment.t1 = 100

        mock_model = MagicMock()
        mock_model.transcribe.return_value = [mock_segment]

        with patch(
            "pywhispercpp.model.Model",
            return_value=mock_model,
        ):
            await provider.connect()

            async def audio_gen():
                yield np.zeros(16000, dtype=np.int16).tobytes()

            results = []
            async for result in provider.transcribe_stream(audio_gen()):
                results.append(result)

            assert len(results) == 1
            assert results[0].text == "Hello, world!"
            assert results[0].is_final is True

        await provider.disconnect()

    @pytest.mark.asyncio
    async def test_transcribe_stream_multiple_segments(self):
        """Test transcription with multiple segments."""
        provider = WhisperCppASRProvider()

        # Create mock segments
        segments = []
        for i, text in enumerate(["First sentence.", "Second sentence."]):
            seg = MagicMock()
            seg.text = f" {text} "
            seg.t0 = i * 100
            seg.t1 = (i + 1) * 100
            segments.append(seg)

        mock_model = MagicMock()
        mock_model.transcribe.return_value = segments

        with patch(
            "pywhispercpp.model.Model",
            return_value=mock_model,
        ):
            await provider.connect()

            async def audio_gen():
                yield np.zeros(32000, dtype=np.int16).tobytes()

            results = []
            async for result in provider.transcribe_stream(audio_gen()):
                results.append(result)

            assert len(results) == 2
            assert results[0].text == "First sentence."
            assert results[0].is_final is False
            assert results[1].text == "Second sentence."
            assert results[1].is_final is True

        await provider.disconnect()

    @pytest.mark.asyncio
    async def test_transcribe_stream_empty_audio(self):
        """Test transcription with no audio."""
        provider = WhisperCppASRProvider()

        mock_model = MagicMock()
        mock_model.transcribe.return_value = []

        with patch(
            "pywhispercpp.model.Model",
            return_value=mock_model,
        ):
            await provider.connect()

            async def audio_gen():
                return
                yield  # noqa: unreachable

            results = []
            async for result in provider.transcribe_stream(audio_gen()):
                results.append(result)

            assert len(results) == 1
            assert results[0].text == ""
            assert results[0].is_final is True
            assert results[0].confidence == 0.0

        await provider.disconnect()

    @pytest.mark.asyncio
    async def test_transcribe_stream_with_language(self):
        """Test transcription with specific language."""
        provider = WhisperCppASRProvider()

        mock_segment = MagicMock()
        mock_segment.text = " Olá mundo "
        mock_segment.t0 = 0
        mock_segment.t1 = 100

        mock_model = MagicMock()
        mock_model.transcribe.return_value = [mock_segment]

        with patch(
            "pywhispercpp.model.Model",
            return_value=mock_model,
        ):
            await provider.connect()

            async def audio_gen():
                yield np.zeros(16000, dtype=np.int16).tobytes()

            results = []
            async for result in provider.transcribe_stream(
                audio_gen(), language="pt"
            ):
                results.append(result)

            # Check that language was passed
            call_kwargs = mock_model.transcribe.call_args[1]
            assert call_kwargs.get("language") == "pt"

        await provider.disconnect()

    @pytest.mark.asyncio
    async def test_transcribe_stream_records_metrics(self):
        """Test that transcription records metrics."""
        provider = WhisperCppASRProvider()

        mock_segment = MagicMock()
        mock_segment.text = "Test"
        mock_segment.t0 = 0
        mock_segment.t1 = 50

        mock_model = MagicMock()
        mock_model.transcribe.return_value = [mock_segment]

        with patch(
            "pywhispercpp.model.Model",
            return_value=mock_model,
        ):
            await provider.connect()

            async def audio_gen():
                yield np.zeros(8000, dtype=np.int16).tobytes()

            async for _ in provider.transcribe_stream(audio_gen()):
                pass

            metrics = provider.metrics
            assert metrics.total_requests == 1
            assert metrics.successful_requests == 1

        await provider.disconnect()


# =============================================================================
# Test Transcribe Method
# =============================================================================


class TestWhisperCppASRProviderTranscribe:
    """Tests for transcribe method."""

    @pytest.mark.asyncio
    async def test_transcribe_raises_without_model(self):
        """Test that transcribe raises when not connected."""
        provider = WhisperCppASRProvider()

        with pytest.raises(RuntimeError, match="not connected"):
            await provider.transcribe(b"\x00" * 1000)

    @pytest.mark.asyncio
    async def test_transcribe_basic(self):
        """Test basic transcription."""
        provider = WhisperCppASRProvider()

        mock_segment = MagicMock()
        mock_segment.text = " Hello world "
        mock_segment.t0 = 0
        mock_segment.t1 = 150

        mock_model = MagicMock()
        mock_model.transcribe.return_value = [mock_segment]

        with patch(
            "pywhispercpp.model.Model",
            return_value=mock_model,
        ):
            await provider.connect()

            audio_data = np.zeros(16000, dtype=np.int16).tobytes()
            result = await provider.transcribe(audio_data)

            assert isinstance(result, TranscriptionResult)
            assert result.text == "Hello world"
            assert result.is_final is True
            assert result.confidence is None  # whisper.cpp doesn't provide confidence

        await provider.disconnect()

    @pytest.mark.asyncio
    async def test_transcribe_combines_segments(self):
        """Test that transcribe combines multiple segments."""
        provider = WhisperCppASRProvider()

        segments = []
        for i, text in enumerate(["First.", "Second.", "Third."]):
            seg = MagicMock()
            seg.text = f" {text} "
            seg.t0 = i * 100
            seg.t1 = (i + 1) * 100
            segments.append(seg)

        mock_model = MagicMock()
        mock_model.transcribe.return_value = segments

        with patch(
            "pywhispercpp.model.Model",
            return_value=mock_model,
        ):
            await provider.connect()

            audio_data = np.zeros(48000, dtype=np.int16).tobytes()
            result = await provider.transcribe(audio_data)

            assert result.text == "First. Second. Third."
            assert result.start_time == 0.0
            assert result.end_time == 3.0  # 300 centiseconds = 3 seconds

        await provider.disconnect()

    @pytest.mark.asyncio
    async def test_transcribe_with_options(self):
        """Test transcription with various options."""
        provider = WhisperCppASRProvider(
            model="medium",
            language="en",
            translate=True,
            beam_size=10,
            best_of=10,
            word_timestamps=True,
            initial_prompt="Technical meeting:",
        )

        mock_segment = MagicMock()
        mock_segment.text = " Translated text "
        mock_segment.t0 = 0
        mock_segment.t1 = 100

        mock_model = MagicMock()
        mock_model.transcribe.return_value = [mock_segment]

        with patch(
            "pywhispercpp.model.Model",
            return_value=mock_model,
        ):
            await provider.connect()

            audio_data = np.zeros(16000, dtype=np.int16).tobytes()
            await provider.transcribe(audio_data)

            # Check options were passed
            call_kwargs = mock_model.transcribe.call_args[1]
            assert call_kwargs.get("language") == "en"
            assert call_kwargs.get("translate") is True
            assert call_kwargs.get("beam_size") == 10
            assert call_kwargs.get("best_of") == 10
            assert call_kwargs.get("word_timestamps") is True
            assert call_kwargs.get("initial_prompt") == "Technical meeting:"

        await provider.disconnect()

    @pytest.mark.asyncio
    async def test_transcribe_empty_result(self):
        """Test transcription with no speech detected."""
        provider = WhisperCppASRProvider()

        mock_model = MagicMock()
        mock_model.transcribe.return_value = []

        with patch(
            "pywhispercpp.model.Model",
            return_value=mock_model,
        ):
            await provider.connect()

            audio_data = np.zeros(16000, dtype=np.int16).tobytes()
            result = await provider.transcribe(audio_data)

            assert result.text == ""
            assert result.is_final is True
            assert result.confidence == 0.0

        await provider.disconnect()


# =============================================================================
# Test Error Handling
# =============================================================================


class TestWhisperCppASRProviderErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_retryable_error_memory(self):
        """Test that memory errors are retryable."""
        provider = WhisperCppASRProvider()

        mock_model = MagicMock()
        mock_model.transcribe.side_effect = Exception("CUDA out of memory")

        with patch(
            "pywhispercpp.model.Model",
            return_value=mock_model,
        ):
            await provider.connect()

            from voice_pipeline.providers.base import RetryableError

            with pytest.raises(RetryableError):
                await provider.transcribe(b"\x00" * 1000)

        await provider.disconnect()

    @pytest.mark.asyncio
    async def test_non_retryable_error_model_not_found(self):
        """Test that model not found is non-retryable."""
        provider = WhisperCppASRProvider()

        mock_model = MagicMock()
        mock_model.transcribe.side_effect = Exception("Model not found: xyz")

        with patch(
            "pywhispercpp.model.Model",
            return_value=mock_model,
        ):
            await provider.connect()

            from voice_pipeline.providers.base import NonRetryableError

            with pytest.raises(NonRetryableError):
                await provider.transcribe(b"\x00" * 1000)

        await provider.disconnect()

    @pytest.mark.asyncio
    async def test_error_records_metrics(self):
        """Test that errors record failure metrics."""
        provider = WhisperCppASRProvider()

        mock_model = MagicMock()
        mock_model.transcribe.side_effect = Exception("Some error")

        with patch(
            "pywhispercpp.model.Model",
            return_value=mock_model,
        ):
            await provider.connect()

            try:
                await provider.transcribe(b"\x00" * 1000)
            except Exception:
                pass

            metrics = provider.metrics
            assert metrics.failed_requests == 1

        await provider.disconnect()


# =============================================================================
# Test VoiceRunnable Interface
# =============================================================================


class TestWhisperCppASRProviderVoiceRunnable:
    """Tests for VoiceRunnable interface."""

    @pytest.mark.asyncio
    async def test_ainvoke_with_bytes(self):
        """Test ainvoke with audio bytes."""
        provider = WhisperCppASRProvider()

        mock_segment = MagicMock()
        mock_segment.text = " Hello "
        mock_segment.t0 = 0
        mock_segment.t1 = 50

        mock_model = MagicMock()
        mock_model.transcribe.return_value = [mock_segment]

        with patch(
            "pywhispercpp.model.Model",
            return_value=mock_model,
        ):
            await provider.connect()

            audio_data = np.zeros(8000, dtype=np.int16).tobytes()
            result = await provider.ainvoke(audio_data)

            assert isinstance(result, TranscriptionResult)
            assert result.text == "Hello"

        await provider.disconnect()

    @pytest.mark.asyncio
    async def test_ainvoke_with_stream(self):
        """Test ainvoke with audio stream."""
        provider = WhisperCppASRProvider()

        mock_segment = MagicMock()
        mock_segment.text = " Streamed audio "
        mock_segment.t0 = 0
        mock_segment.t1 = 100

        mock_model = MagicMock()
        mock_model.transcribe.return_value = [mock_segment]

        with patch(
            "pywhispercpp.model.Model",
            return_value=mock_model,
        ):
            await provider.connect()

            async def audio_gen():
                for _ in range(3):
                    yield np.zeros(8000, dtype=np.int16).tobytes()

            result = await provider.ainvoke(audio_gen())

            assert result.text == "Streamed audio"

        await provider.disconnect()

    @pytest.mark.asyncio
    async def test_astream(self):
        """Test astream method."""
        provider = WhisperCppASRProvider()

        mock_segment = MagicMock()
        mock_segment.text = " Streaming result "
        mock_segment.t0 = 0
        mock_segment.t1 = 100

        mock_model = MagicMock()
        mock_model.transcribe.return_value = [mock_segment]

        with patch(
            "pywhispercpp.model.Model",
            return_value=mock_model,
        ):
            await provider.connect()

            audio_data = np.zeros(16000, dtype=np.int16).tobytes()

            results = []
            async for result in provider.astream(audio_data):
                results.append(result)

            assert len(results) == 1
            assert results[0].text == "Streaming result"

        await provider.disconnect()


# =============================================================================
# Test Model Sizes Dictionary
# =============================================================================


class TestWhisperCppModelSizes:
    """Tests for model sizes dictionary."""

    def test_model_sizes_contains_basic_models(self):
        """Test that model sizes dict has basic models."""
        assert "tiny" in WHISPER_MODEL_SIZES
        assert "base" in WHISPER_MODEL_SIZES
        assert "small" in WHISPER_MODEL_SIZES
        assert "medium" in WHISPER_MODEL_SIZES
        assert "large" in WHISPER_MODEL_SIZES

    def test_model_sizes_contains_english_models(self):
        """Test that model sizes dict has English-only models."""
        assert "tiny.en" in WHISPER_MODEL_SIZES
        assert "base.en" in WHISPER_MODEL_SIZES
        assert "small.en" in WHISPER_MODEL_SIZES
        assert "medium.en" in WHISPER_MODEL_SIZES

    def test_model_sizes_contains_turbo(self):
        """Test that model sizes dict has turbo model."""
        assert "turbo" in WHISPER_MODEL_SIZES


# =============================================================================
# Integration Tests (require pywhispercpp installed)
# =============================================================================


@pytest.mark.integration
class TestWhisperCppASRProviderIntegration:
    """Integration tests with real whisper.cpp model.

    These tests require pywhispercpp to be installed and will
    download the model on first run.
    """

    @pytest.mark.asyncio
    async def test_real_transcription(self):
        """Test real transcription with actual model."""
        pytest.importorskip("pywhispercpp")

        provider = WhisperCppASRProvider(
            model="tiny.en",  # Smallest model for fast tests
            n_threads=4,
        )

        try:
            await provider.connect()

            # Create simple test audio (440 Hz tone for 1 second)
            sample_rate = 16000
            duration = 1.0
            t = np.linspace(0, duration, int(sample_rate * duration), dtype=np.float32)
            audio_float = 0.5 * np.sin(2 * np.pi * 440 * t)
            audio_int16 = (audio_float * 32767).astype(np.int16)
            audio_bytes = audio_int16.tobytes()

            result = await provider.transcribe(audio_bytes)

            # Should return some result (even if empty for tone)
            assert isinstance(result, TranscriptionResult)
            assert result.is_final is True

        finally:
            await provider.disconnect()

    @pytest.mark.asyncio
    async def test_real_streaming(self):
        """Test real streaming with actual model."""
        pytest.importorskip("pywhispercpp")

        provider = WhisperCppASRProvider(
            model="tiny.en",
            n_threads=4,
        )

        try:
            await provider.connect()

            # Create test audio
            sample_rate = 16000
            audio_int16 = np.zeros(sample_rate, dtype=np.int16)
            audio_bytes = audio_int16.tobytes()

            async def audio_gen():
                yield audio_bytes

            results = []
            async for result in provider.transcribe_stream(audio_gen()):
                results.append(result)

            # Should get at least one result
            assert len(results) >= 1
            assert results[-1].is_final is True

        finally:
            await provider.disconnect()
