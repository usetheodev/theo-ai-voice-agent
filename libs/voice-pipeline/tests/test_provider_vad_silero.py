"""Tests for Silero VAD provider."""

import numpy as np
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from voice_pipeline.interfaces.vad import SpeechState, VADEvent
from voice_pipeline.providers.base import HealthCheckResult, ProviderHealth
from voice_pipeline.providers.vad import SileroVADProvider, SileroVADConfig


class TestSileroVADConfig:
    """Tests for SileroVADConfig."""

    def test_default_values(self):
        """Test default configuration values."""
        config = SileroVADConfig()

        assert config.threshold == 0.5
        assert config.min_speech_duration_ms == 50.0
        assert config.min_silence_duration_ms == 500.0
        assert config.speech_pad_ms == 30.0
        assert config.model_path is None
        assert config.window_size_samples == 512

    def test_custom_values(self):
        """Test custom configuration values."""
        config = SileroVADConfig(
            threshold=0.7,
            min_speech_duration_ms=100.0,
            min_silence_duration_ms=300.0,
            speech_pad_ms=50.0,
            model_path="/path/to/model.pt",
            window_size_samples=256,
        )

        assert config.threshold == 0.7
        assert config.min_speech_duration_ms == 100.0
        assert config.min_silence_duration_ms == 300.0
        assert config.speech_pad_ms == 50.0
        assert config.model_path == "/path/to/model.pt"
        assert config.window_size_samples == 256


class TestSileroVADProviderInit:
    """Tests for SileroVADProvider initialization."""

    def test_default_initialization(self):
        """Test provider with default config."""
        provider = SileroVADProvider()

        assert provider.provider_name == "silero-vad"
        assert provider.name == "SileroVAD"
        assert provider._vad_config.threshold == 0.5
        assert provider.is_connected is False

    def test_initialization_with_config(self):
        """Test provider with custom config."""
        config = SileroVADConfig(threshold=0.7, min_silence_duration_ms=300.0)
        provider = SileroVADProvider(config=config)

        assert provider._vad_config.threshold == 0.7
        assert provider._vad_config.min_silence_duration_ms == 300.0

    def test_initialization_with_shortcuts(self):
        """Test provider with shortcut parameters."""
        provider = SileroVADProvider(
            threshold=0.6,
            min_silence_duration_ms=400.0,
        )

        assert provider._vad_config.threshold == 0.6
        assert provider._vad_config.min_silence_duration_ms == 400.0

    def test_shortcuts_override_config(self):
        """Test that shortcuts override config values."""
        config = SileroVADConfig(threshold=0.5, min_silence_duration_ms=500.0)
        provider = SileroVADProvider(
            config=config,
            threshold=0.8,  # Override
            min_silence_duration_ms=200.0,  # Override
        )

        assert provider._vad_config.threshold == 0.8
        assert provider._vad_config.min_silence_duration_ms == 200.0

    def test_frame_size_ms(self):
        """Test frame size property."""
        provider = SileroVADProvider()
        assert provider.frame_size_ms == 32  # 512 samples at 16kHz

    def test_repr(self):
        """Test string representation."""
        provider = SileroVADProvider(threshold=0.6)
        repr_str = repr(provider)

        assert "SileroVADProvider" in repr_str
        assert "threshold=0.6" in repr_str
        assert "connected=False" in repr_str


class TestSileroVADProviderLifecycle:
    """Tests for provider lifecycle (connect/disconnect)."""

    @pytest.mark.asyncio
    async def test_connect_loads_model(self):
        """Test that connect loads the model."""
        provider = SileroVADProvider()

        # Mock torch.hub.load
        mock_model = MagicMock()
        mock_model.eval = MagicMock()

        with patch("torch.hub.load", return_value=(mock_model, None)) as mock_load:
            await provider.connect()

            mock_load.assert_called_once_with(
                repo_or_dir="snakers4/silero-vad",
                model="silero_vad",
                force_reload=False,
                onnx=False,
                trust_repo=True,
            )
            mock_model.eval.assert_called_once()
            assert provider.is_connected is True
            assert provider._model is mock_model

    @pytest.mark.asyncio
    async def test_connect_with_local_model(self):
        """Test connect with local model path."""
        config = SileroVADConfig(model_path="/path/to/model.pt")
        provider = SileroVADProvider(config=config)

        mock_model = MagicMock()
        mock_model.eval = MagicMock()

        with patch("torch.jit.load", return_value=mock_model) as mock_jit_load:
            await provider.connect()

            mock_jit_load.assert_called_once_with("/path/to/model.pt")
            assert provider._model is mock_model

    @pytest.mark.asyncio
    async def test_connect_raises_without_torch(self):
        """Test that connect raises ImportError without torch."""
        provider = SileroVADProvider()

        with patch.dict("sys.modules", {"torch": None}):
            with patch("builtins.__import__", side_effect=ImportError("No module named 'torch'")):
                with pytest.raises(ImportError, match="torch is required"):
                    await provider.connect()

    @pytest.mark.asyncio
    async def test_disconnect_unloads_model(self):
        """Test that disconnect unloads the model."""
        provider = SileroVADProvider()
        provider._model = MagicMock()
        provider._connected = True

        await provider.disconnect()

        assert provider._model is None
        assert provider.is_connected is False

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test async context manager."""
        provider = SileroVADProvider()

        mock_model = MagicMock()
        mock_model.eval = MagicMock()

        with patch("torch.hub.load", return_value=(mock_model, None)):
            async with provider as p:
                assert p.is_connected is True
                assert p._model is mock_model

            assert provider.is_connected is False
            assert provider._model is None


class TestSileroVADProviderReset:
    """Tests for reset functionality."""

    def test_reset_clears_state(self):
        """Test that reset clears all state."""
        provider = SileroVADProvider()

        # Set some state
        provider._is_speaking = True
        provider._speech_start_time = 12345.0
        provider._silence_start_time = 12346.0
        provider._current_speech_duration_ms = 100.0
        provider._current_silence_duration_ms = 50.0

        provider.reset()

        assert provider._is_speaking is False
        assert provider._speech_start_time is None
        assert provider._silence_start_time is None
        assert provider._current_speech_duration_ms == 0.0
        assert provider._current_silence_duration_ms == 0.0

    def test_reset_with_model_resets_states(self):
        """Test that reset calls model.reset_states() if available."""
        provider = SileroVADProvider()
        mock_model = MagicMock()
        provider._model = mock_model

        provider.reset()

        mock_model.reset_states.assert_called_once()

    def test_reset_handles_model_without_reset_states(self):
        """Test reset handles model without reset_states method."""
        provider = SileroVADProvider()
        mock_model = MagicMock()
        del mock_model.reset_states  # Remove reset_states method
        provider._model = mock_model

        # Should not raise
        provider.reset()


class TestSileroVADProviderHealthCheck:
    """Tests for health check functionality."""

    @pytest.mark.asyncio
    async def test_health_check_unhealthy_when_not_connected(self):
        """Test health check returns unhealthy when model not loaded."""
        provider = SileroVADProvider()

        result = await provider.health_check()

        assert result.status == ProviderHealth.UNHEALTHY
        assert "not loaded" in result.message.lower()

    @pytest.mark.asyncio
    async def test_health_check_healthy_when_connected(self):
        """Test health check returns healthy when model is working."""
        provider = SileroVADProvider()

        # Mock model
        mock_model = MagicMock()
        mock_model.return_value = MagicMock(item=MagicMock(return_value=0.1))
        provider._model = mock_model

        with patch("torch.zeros", return_value=MagicMock()):
            result = await provider.health_check()

        assert result.status == ProviderHealth.HEALTHY
        assert result.latency_ms is not None

    @pytest.mark.asyncio
    async def test_health_check_unhealthy_on_error(self):
        """Test health check returns unhealthy on error."""
        provider = SileroVADProvider()

        # Mock model that raises error
        mock_model = MagicMock()
        mock_model.side_effect = RuntimeError("Model error")
        provider._model = mock_model

        with patch("torch.zeros", return_value=MagicMock()):
            result = await provider.health_check()

        assert result.status == ProviderHealth.UNHEALTHY


class TestSileroVADProviderProcess:
    """Tests for audio processing."""

    def _create_audio_chunk(self, samples: int = 512, sample_rate: int = 16000) -> bytes:
        """Create a test audio chunk."""
        # Create random audio data
        audio = np.random.uniform(-0.5, 0.5, samples).astype(np.float32)
        # Convert to int16
        audio_int16 = (audio * 32768).astype(np.int16)
        return audio_int16.tobytes()

    def _create_silence_chunk(self, samples: int = 512) -> bytes:
        """Create a silent audio chunk."""
        return np.zeros(samples, dtype=np.int16).tobytes()

    @pytest.mark.asyncio
    async def test_process_raises_without_model(self):
        """Test process raises error when model not loaded."""
        provider = SileroVADProvider()
        audio = self._create_audio_chunk()

        with pytest.raises(RuntimeError, match="not loaded"):
            await provider.process(audio, sample_rate=16000)

    @pytest.mark.asyncio
    async def test_process_raises_invalid_sample_rate(self):
        """Test process raises error for invalid sample rate."""
        provider = SileroVADProvider()
        provider._model = MagicMock()
        audio = self._create_audio_chunk()

        with pytest.raises(ValueError, match="Unsupported sample rate"):
            await provider.process(audio, sample_rate=44100)

    @pytest.mark.asyncio
    async def test_process_accepts_valid_sample_rates(self):
        """Test process accepts 8000 and 16000 Hz."""
        provider = SileroVADProvider()

        mock_model = MagicMock()
        mock_model.return_value = MagicMock(item=MagicMock(return_value=0.3))
        provider._model = mock_model

        # Mock torch
        with patch("torch.from_numpy", return_value=MagicMock()):
            with patch("torch.no_grad", return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock())):
                # 16kHz should work
                audio_16k = self._create_audio_chunk(512, 16000)
                result = await provider.process(audio_16k, sample_rate=16000)
                assert isinstance(result, VADEvent)

                # 8kHz should work
                provider.reset()
                audio_8k = self._create_audio_chunk(256, 8000)
                result = await provider.process(audio_8k, sample_rate=8000)
                assert isinstance(result, VADEvent)

    @pytest.mark.asyncio
    async def test_process_silence_returns_silence_state(self):
        """Test processing silence returns SILENCE state."""
        provider = SileroVADProvider()

        mock_model = MagicMock()
        mock_model.return_value = MagicMock(item=MagicMock(return_value=0.1))  # Low probability
        provider._model = mock_model

        with patch("torch.from_numpy", return_value=MagicMock()):
            with patch("torch.no_grad", return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock())):
                audio = self._create_silence_chunk()
                result = await provider.process(audio, sample_rate=16000)

                assert result.is_speech is False
                assert result.state == SpeechState.SILENCE
                assert result.confidence == 0.1

    @pytest.mark.asyncio
    async def test_process_speech_triggers_after_min_duration(self):
        """Test speech is triggered after minimum duration."""
        provider = SileroVADProvider(
            threshold=0.5,
            min_speech_duration_ms=50.0,  # 50ms
        )

        mock_model = MagicMock()
        mock_model.return_value = MagicMock(item=MagicMock(return_value=0.8))  # High probability
        provider._model = mock_model

        with patch("torch.from_numpy", return_value=MagicMock()):
            with patch("torch.no_grad", return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock())):
                # Process multiple chunks (each 32ms at 16kHz with 512 samples)
                audio = self._create_audio_chunk(512, 16000)

                # First chunk (32ms) - not enough duration yet
                result = await provider.process(audio, sample_rate=16000)
                # State is UNCERTAIN because speech probability is high but not confirmed yet
                assert result.state == SpeechState.UNCERTAIN

                # Second chunk (64ms total) - now speech should be confirmed
                result = await provider.process(audio, sample_rate=16000)
                assert result.is_speech is True
                assert result.state == SpeechState.SPEECH

    @pytest.mark.asyncio
    async def test_process_silence_ends_speech_after_min_duration(self):
        """Test silence ends speech after minimum duration."""
        provider = SileroVADProvider(
            threshold=0.5,
            min_speech_duration_ms=30.0,  # Low threshold for quick speech start
            min_silence_duration_ms=100.0,  # 100ms to end
        )

        mock_model = MagicMock()
        provider._model = mock_model

        with patch("torch.from_numpy", return_value=MagicMock()):
            with patch("torch.no_grad", return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock())):
                audio = self._create_audio_chunk(512, 16000)

                # First: high speech probability - need 2 chunks to trigger speech
                mock_model.return_value = MagicMock(item=MagicMock(return_value=0.8))
                result = await provider.process(audio, sample_rate=16000)  # ~32ms
                result = await provider.process(audio, sample_rate=16000)  # ~64ms total
                assert result.is_speech is True

                # Then: low speech probability (silence)
                mock_model.return_value = MagicMock(item=MagicMock(return_value=0.1))

                # First silence chunk (~32ms)
                result = await provider.process(audio, sample_rate=16000)
                assert result.is_speech is True  # Still speaking (min_silence not reached)

                # More silence chunks
                result = await provider.process(audio, sample_rate=16000)
                result = await provider.process(audio, sample_rate=16000)
                result = await provider.process(audio, sample_rate=16000)

                # After enough silence (~128ms > 100ms), speech should end
                assert result.is_speech is False
                assert result.state == SpeechState.SILENCE

    @pytest.mark.asyncio
    async def test_process_records_metrics(self):
        """Test that process records metrics."""
        provider = SileroVADProvider()

        mock_model = MagicMock()
        mock_model.return_value = MagicMock(item=MagicMock(return_value=0.5))
        provider._model = mock_model

        with patch("torch.from_numpy", return_value=MagicMock()):
            with patch("torch.no_grad", return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock())):
                audio = self._create_audio_chunk()
                await provider.process(audio, sample_rate=16000)

                assert provider.metrics.successful_requests == 1
                assert provider.metrics.total_requests == 1


class TestSileroVADProviderGetSpeechProbability:
    """Tests for get_speech_probability method."""

    def _create_audio_chunk(self, samples: int = 512) -> bytes:
        """Create a test audio chunk."""
        audio = np.random.uniform(-0.5, 0.5, samples).astype(np.float32)
        audio_int16 = (audio * 32768).astype(np.int16)
        return audio_int16.tobytes()

    def test_get_speech_probability_raises_without_model(self):
        """Test raises error when model not loaded."""
        provider = SileroVADProvider()
        audio = self._create_audio_chunk()

        with pytest.raises(RuntimeError, match="not loaded"):
            provider.get_speech_probability(audio, sample_rate=16000)

    def test_get_speech_probability_returns_float(self):
        """Test returns speech probability as float."""
        provider = SileroVADProvider()

        mock_model = MagicMock()
        mock_model.return_value = MagicMock(item=MagicMock(return_value=0.75))
        provider._model = mock_model

        with patch("torch.from_numpy", return_value=MagicMock()):
            with patch("torch.no_grad", return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock())):
                audio = self._create_audio_chunk()
                prob = provider.get_speech_probability(audio, sample_rate=16000)

                assert prob == 0.75


class TestSileroVADProviderConfiguration:
    """Tests for dynamic configuration methods."""

    def test_set_threshold_valid(self):
        """Test setting valid threshold."""
        provider = SileroVADProvider()

        provider.set_threshold(0.7)
        assert provider._vad_config.threshold == 0.7

        provider.set_threshold(0.0)
        assert provider._vad_config.threshold == 0.0

        provider.set_threshold(1.0)
        assert provider._vad_config.threshold == 1.0

    def test_set_threshold_invalid(self):
        """Test setting invalid threshold raises error."""
        provider = SileroVADProvider()

        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            provider.set_threshold(-0.1)

        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            provider.set_threshold(1.5)

    def test_set_min_silence_duration_valid(self):
        """Test setting valid silence duration."""
        provider = SileroVADProvider()

        provider.set_min_silence_duration(300.0)
        assert provider._vad_config.min_silence_duration_ms == 300.0

        provider.set_min_silence_duration(0.0)
        assert provider._vad_config.min_silence_duration_ms == 0.0

    def test_set_min_silence_duration_invalid(self):
        """Test setting negative duration raises error."""
        provider = SileroVADProvider()

        with pytest.raises(ValueError, match="positive"):
            provider.set_min_silence_duration(-100.0)
