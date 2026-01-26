"""Tests for Piper TTS provider."""

import numpy as np
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from voice_pipeline.interfaces.tts import AudioChunk
from voice_pipeline.providers.base import (
    HealthCheckResult,
    ProviderHealth,
)
from voice_pipeline.providers.tts import PiperTTSProvider, PiperTTSConfig


class TestPiperTTSConfig:
    """Tests for PiperTTSConfig."""

    def test_default_values(self):
        """Test default configuration values."""
        config = PiperTTSConfig()

        assert config.voice == "en_US-lessac-medium"
        assert config.model_path is None
        assert config.data_dir is None
        assert config.speaker_id == 0
        assert config.length_scale == 1.0
        assert config.noise_scale == 0.667
        assert config.noise_w == 0.8
        assert config.sentence_silence == 0.2

    def test_custom_values(self):
        """Test custom configuration values."""
        config = PiperTTSConfig(
            voice="pt_BR-faber-medium",
            model_path="/path/to/model.onnx",
            data_dir="/path/to/data",
            speaker_id=1,
            length_scale=0.8,
            noise_scale=0.5,
            noise_w=0.6,
            sentence_silence=0.3,
        )

        assert config.voice == "pt_BR-faber-medium"
        assert config.model_path == "/path/to/model.onnx"
        assert config.data_dir == "/path/to/data"
        assert config.speaker_id == 1
        assert config.length_scale == 0.8
        assert config.noise_scale == 0.5
        assert config.noise_w == 0.6
        assert config.sentence_silence == 0.3


class TestPiperTTSProviderInit:
    """Tests for PiperTTSProvider initialization."""

    def test_default_initialization(self):
        """Test provider with default config."""
        provider = PiperTTSProvider()

        assert provider.provider_name == "piper-tts"
        assert provider.name == "PiperTTS"
        assert provider._tts_config.voice == "en_US-lessac-medium"
        assert provider._tts_config.length_scale == 1.0
        assert provider.is_connected is False

    def test_initialization_with_config(self):
        """Test provider with custom config."""
        config = PiperTTSConfig(
            voice="pt_BR-faber-medium",
            length_scale=0.9,
        )
        provider = PiperTTSProvider(config=config)

        assert provider._tts_config.voice == "pt_BR-faber-medium"
        assert provider._tts_config.length_scale == 0.9

    def test_initialization_with_shortcuts(self):
        """Test provider with shortcut parameters."""
        provider = PiperTTSProvider(
            voice="en_US-ryan-medium",
            model_path="/path/to/model.onnx",
            data_dir="/path/to/data",
            speaker_id=2,
            length_scale=1.2,
        )

        assert provider._tts_config.voice == "en_US-ryan-medium"
        assert provider._tts_config.model_path == "/path/to/model.onnx"
        assert provider._tts_config.data_dir == "/path/to/data"
        assert provider._tts_config.speaker_id == 2
        assert provider._tts_config.length_scale == 1.2

    def test_shortcuts_override_config(self):
        """Test that shortcuts override config values."""
        config = PiperTTSConfig(
            voice="en_US-lessac-medium",
            length_scale=1.0,
        )
        provider = PiperTTSProvider(
            config=config,
            voice="pt_BR-faber-medium",
            length_scale=0.8,
        )

        assert provider._tts_config.voice == "pt_BR-faber-medium"
        assert provider._tts_config.length_scale == 0.8

    def test_sample_rate_property(self):
        """Test sample_rate property defaults to 22050."""
        provider = PiperTTSProvider()
        assert provider.sample_rate == 22050

    def test_channels_property(self):
        """Test channels property (always mono)."""
        provider = PiperTTSProvider()
        assert provider.channels == 1

    def test_get_language_from_voice(self):
        """Test language extraction from voice name."""
        provider_pt = PiperTTSProvider(voice="pt_BR-faber-medium")
        assert provider_pt._get_language() == "pt"

        provider_en = PiperTTSProvider(voice="en_US-lessac-medium")
        assert provider_en._get_language() == "en"

        provider_es = PiperTTSProvider(voice="es_ES-mls-medium")
        assert provider_es._get_language() == "es"

        provider_fr = PiperTTSProvider(voice="fr_FR-siwis-medium")
        assert provider_fr._get_language() == "fr"

        provider_de = PiperTTSProvider(voice="de_DE-thorsten-medium")
        assert provider_de._get_language() == "de"

        provider_it = PiperTTSProvider(voice="it_IT-riccardo-medium")
        assert provider_it._get_language() == "it"

    def test_get_language_unknown_defaults_to_en(self):
        """Test unknown language defaults to English."""
        provider = PiperTTSProvider(voice="xx_XX-unknown-medium")
        assert provider._get_language() == "en"

    def test_repr(self):
        """Test string representation."""
        provider = PiperTTSProvider(voice="pt_BR-faber-medium")
        repr_str = repr(provider)

        assert "PiperTTSProvider" in repr_str
        assert "pt_BR-faber-medium" in repr_str
        assert "connected=False" in repr_str


class TestPiperTTSProviderLifecycle:
    """Tests for provider lifecycle (connect/disconnect)."""

    @pytest.mark.asyncio
    async def test_connect_loads_voice(self):
        """Test that connect loads the Piper voice model."""
        provider = PiperTTSProvider(model_path="/path/to/model.onnx")

        mock_voice = MagicMock()
        mock_voice.config.sample_rate = 22050

        with patch.dict("sys.modules", {"piper": MagicMock()}):
            with patch("asyncio.get_event_loop") as mock_loop:
                mock_loop.return_value.run_in_executor = AsyncMock(
                    return_value=mock_voice
                )

                await provider.connect()

                assert provider.is_connected is True
                assert provider._voice is mock_voice

    @pytest.mark.asyncio
    async def test_connect_raises_without_piper(self):
        """Test that connect raises ImportError without piper package."""
        provider = PiperTTSProvider()

        with patch.dict("sys.modules", {"piper": None}):
            with patch(
                "builtins.__import__",
                side_effect=ImportError("No module named 'piper'"),
            ):
                with pytest.raises(ImportError, match="piper-tts is required"):
                    await provider.connect()

    @pytest.mark.asyncio
    async def test_disconnect_cleans_up(self):
        """Test that disconnect cleans up resources."""
        provider = PiperTTSProvider()

        mock_voice = MagicMock()
        mock_executor = MagicMock()
        provider._voice = mock_voice
        provider._executor = mock_executor
        provider._connected = True

        await provider.disconnect()

        mock_executor.shutdown.assert_called_once_with(wait=False)
        assert provider._voice is None
        assert provider._executor is None
        assert provider.is_connected is False


class TestPiperTTSProviderHealthCheck:
    """Tests for health check functionality."""

    @pytest.mark.asyncio
    async def test_health_check_unhealthy_when_not_connected(self):
        """Test health check returns unhealthy when voice not loaded."""
        provider = PiperTTSProvider()

        result = await provider.health_check()

        assert result.status == ProviderHealth.UNHEALTHY
        assert "not loaded" in result.message.lower()

    @pytest.mark.asyncio
    async def test_health_check_healthy_when_synthesis_works(self):
        """Test health check returns healthy when synthesis test passes."""
        provider = PiperTTSProvider()

        mock_voice = MagicMock()
        provider._voice = mock_voice
        provider._executor = MagicMock()

        with patch("asyncio.get_event_loop") as mock_loop:
            # Return True to indicate successful synthesis test
            mock_loop.return_value.run_in_executor = AsyncMock(return_value=True)

            result = await provider.health_check()

            assert result.status == ProviderHealth.HEALTHY
            assert "Piper ready" in result.message

    @pytest.mark.asyncio
    async def test_health_check_unhealthy_on_error(self):
        """Test health check returns unhealthy on synthesis error."""
        provider = PiperTTSProvider()

        mock_voice = MagicMock()
        provider._voice = mock_voice
        provider._executor = MagicMock()

        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.run_in_executor = AsyncMock(
                side_effect=Exception("ONNX runtime error")
            )

            result = await provider.health_check()

            assert result.status == ProviderHealth.UNHEALTHY
            assert "error" in result.message.lower()

    @pytest.mark.asyncio
    async def test_health_check_degraded_on_empty_audio(self):
        """Test health check returns degraded when synthesis returns empty audio."""
        provider = PiperTTSProvider()

        mock_voice = MagicMock()
        provider._voice = mock_voice
        provider._executor = MagicMock()

        with patch("asyncio.get_event_loop") as mock_loop:
            # Return False to indicate empty audio output
            mock_loop.return_value.run_in_executor = AsyncMock(return_value=False)

            result = await provider.health_check()

            assert result.status == ProviderHealth.DEGRADED
            assert "empty" in result.message.lower()

    @pytest.mark.asyncio
    async def test_health_check_healthy_includes_details(self):
        """Test health check includes voice details when healthy."""
        provider = PiperTTSProvider(voice="pt_BR-faber-medium")

        mock_voice = MagicMock()
        provider._voice = mock_voice
        provider._executor = MagicMock()

        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.run_in_executor = AsyncMock(return_value=True)

            result = await provider.health_check()

            assert result.status == ProviderHealth.HEALTHY
            assert result.details is not None
            assert result.details["voice"] == "pt_BR-faber-medium"
            assert result.details["sample_rate"] == 22050
