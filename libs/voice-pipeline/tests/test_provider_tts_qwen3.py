"""Tests for Qwen3-TTS provider."""

import numpy as np
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from voice_pipeline.interfaces.tts import AudioChunk
from voice_pipeline.providers.base import (
    HealthCheckResult,
    ProviderHealth,
)
from voice_pipeline.providers.tts import Qwen3TTSProvider, Qwen3TTSConfig


class TestQwen3TTSConfig:
    """Tests for Qwen3TTSConfig."""

    def test_default_values(self):
        """Test default configuration values."""
        config = Qwen3TTSConfig()

        assert config.model == "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
        assert config.language == "English"
        assert config.speaker is None
        assert config.instruct == "Clear, natural female voice, speaking in a friendly manner."
        assert config.device == "cpu"
        assert config.dtype == "float32"
        assert config.sample_rate == 24000
        assert config.use_flash_attention is False
        assert config.ref_audio is None
        assert config.ref_text is None
        assert config.voice_description is None

    def test_custom_values(self):
        """Test custom configuration values."""
        config = Qwen3TTSConfig(
            model="Qwen/Qwen3-TTS-12Hz-0.6B-Base",
            language="Portuguese",
            speaker="Ryan",
            instruct="Speak cheerfully",
            device="cuda",
            dtype="bfloat16",
            sample_rate=22050,
            use_flash_attention=True,
            ref_audio="/path/to/audio.wav",
            ref_text="Hello world",
            voice_description="Deep male voice",
        )

        assert config.model == "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
        assert config.language == "Portuguese"
        assert config.speaker == "Ryan"
        assert config.instruct == "Speak cheerfully"
        assert config.device == "cuda"
        assert config.dtype == "bfloat16"
        assert config.sample_rate == 22050
        assert config.use_flash_attention is True
        assert config.ref_audio == "/path/to/audio.wav"
        assert config.ref_text == "Hello world"
        assert config.voice_description == "Deep male voice"


class TestQwen3TTSProviderInit:
    """Tests for Qwen3TTSProvider initialization."""

    def test_default_initialization(self):
        """Test provider with default config."""
        provider = Qwen3TTSProvider()

        assert provider.provider_name == "qwen3-tts"
        assert provider.name == "Qwen3TTS"
        assert provider._tts_config.model == "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
        assert provider._tts_config.language == "English"
        assert provider._tts_config.device == "cpu"
        assert provider.is_connected is False

    def test_initialization_with_config(self):
        """Test provider with custom config."""
        config = Qwen3TTSConfig(
            model="Qwen/Qwen3-TTS-12Hz-0.6B-Base",
            language="Portuguese",
            device="cpu",
        )
        provider = Qwen3TTSProvider(config=config)

        assert provider._tts_config.model == "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
        assert provider._tts_config.language == "Portuguese"
        assert provider._tts_config.device == "cpu"

    def test_initialization_with_shortcuts(self):
        """Test provider with shortcut parameters."""
        provider = Qwen3TTSProvider(
            model="Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
            language="Japanese",
            speaker="Ono_Anna",
            instruct="Speak softly",
            device="cpu",
            dtype="float32",
        )

        assert provider._tts_config.model == "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
        assert provider._tts_config.language == "Japanese"
        assert provider._tts_config.speaker == "Ono_Anna"
        assert provider._tts_config.instruct == "Speak softly"
        assert provider._tts_config.device == "cpu"
        assert provider._tts_config.dtype == "float32"

    def test_shortcuts_override_config(self):
        """Test that shortcuts override config values."""
        config = Qwen3TTSConfig(
            language="English",
            device="cpu",
        )
        provider = Qwen3TTSProvider(
            config=config,
            language="Portuguese",
            device="cpu",
        )

        assert provider._tts_config.language == "Portuguese"

    def test_voice_alias_for_speaker(self):
        """Test that voice parameter maps to speaker."""
        provider = Qwen3TTSProvider(voice="Ryan")

        assert provider._tts_config.speaker == "Ryan"

    def test_auto_dtype_for_cuda(self):
        """Test that dtype is auto-set to bfloat16 for CUDA when default float32."""
        provider = Qwen3TTSProvider(device="cuda")

        assert provider._tts_config.dtype == "bfloat16"

    def test_no_auto_dtype_when_explicit(self):
        """Test that explicit dtype is preserved even on CUDA."""
        provider = Qwen3TTSProvider(device="cuda", dtype="float16")

        assert provider._tts_config.dtype == "float16"

    def test_sample_rate_property(self):
        """Test sample_rate property."""
        provider = Qwen3TTSProvider()
        assert provider.sample_rate == 24000

        config = Qwen3TTSConfig(sample_rate=22050)
        provider = Qwen3TTSProvider(config=config)
        assert provider.sample_rate == 22050

    def test_channels_property(self):
        """Test channels property (always mono)."""
        provider = Qwen3TTSProvider()
        assert provider.channels == 1

    def test_repr(self):
        """Test string representation."""
        provider = Qwen3TTSProvider(
            model="Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
            language="Portuguese",
            device="cpu",
        )
        repr_str = repr(provider)

        assert "Qwen3TTSProvider" in repr_str
        assert "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign" in repr_str
        assert "Portuguese" in repr_str
        assert "cpu" in repr_str


class TestQwen3TTSProviderLifecycle:
    """Tests for provider lifecycle (connect/disconnect)."""

    @pytest.mark.asyncio
    async def test_connect_loads_model(self):
        """Test that connect loads the Qwen3-TTS model."""
        provider = Qwen3TTSProvider()

        mock_model = MagicMock()

        with patch.dict("sys.modules", {"qwen_tts": MagicMock(), "torch": MagicMock()}):
            with patch("asyncio.get_event_loop") as mock_loop:
                mock_loop.return_value.run_in_executor = AsyncMock(
                    return_value=mock_model
                )

                await provider.connect()

                assert provider.is_connected is True
                assert provider._model is mock_model

    @pytest.mark.asyncio
    async def test_connect_raises_without_qwen_tts(self):
        """Test that connect raises ImportError without qwen_tts package."""
        provider = Qwen3TTSProvider()

        with patch.dict("sys.modules", {"qwen_tts": None}):
            with patch(
                "builtins.__import__",
                side_effect=ImportError("No module named 'qwen_tts'"),
            ):
                with pytest.raises(ImportError, match="qwen-tts is required"):
                    await provider.connect()

    @pytest.mark.asyncio
    async def test_disconnect_cleans_up(self):
        """Test that disconnect cleans up resources."""
        provider = Qwen3TTSProvider()

        mock_model = MagicMock()
        mock_executor = MagicMock()
        provider._model = mock_model
        provider._executor = mock_executor
        provider._voice_clone_prompt = "some_prompt"
        provider._connected = True

        await provider.disconnect()

        mock_executor.shutdown.assert_called_once_with(wait=False)
        assert provider._model is None
        assert provider._executor is None
        assert provider._voice_clone_prompt is None
        assert provider.is_connected is False


class TestQwen3TTSProviderHealthCheck:
    """Tests for health check functionality."""

    @pytest.mark.asyncio
    async def test_health_check_unhealthy_when_not_connected(self):
        """Test health check returns unhealthy when model not loaded."""
        provider = Qwen3TTSProvider()

        result = await provider.health_check()

        assert result.status == ProviderHealth.UNHEALTHY
        assert "not initialized" in result.message.lower()

    @pytest.mark.asyncio
    async def test_health_check_healthy_when_synthesis_works(self):
        """Test health check returns healthy when synthesis works."""
        provider = Qwen3TTSProvider()

        # Mock model present
        provider._model = MagicMock()
        provider._executor = MagicMock()

        # Mock synthesize to return valid audio bytes
        audio_bytes = (np.zeros(1000, dtype=np.float32) * 32767).astype(np.int16).tobytes()

        with patch.object(provider, "synthesize", new_callable=AsyncMock) as mock_synth:
            mock_synth.return_value = audio_bytes

            result = await provider.health_check()

            assert result.status == ProviderHealth.HEALTHY
            assert "Qwen3-TTS ready" in result.message

    @pytest.mark.asyncio
    async def test_health_check_unhealthy_on_error(self):
        """Test health check returns unhealthy on synthesis error."""
        provider = Qwen3TTSProvider()

        provider._model = MagicMock()
        provider._executor = MagicMock()

        with patch.object(provider, "synthesize", new_callable=AsyncMock) as mock_synth:
            mock_synth.side_effect = Exception("Synthesis failed")

            result = await provider.health_check()

            assert result.status == ProviderHealth.UNHEALTHY
            assert "error" in result.message.lower()

    @pytest.mark.asyncio
    async def test_health_check_healthy_includes_details(self):
        """Test health check includes model details when healthy."""
        provider = Qwen3TTSProvider(
            model="Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
            language="Portuguese",
            device="cpu",
        )

        provider._model = MagicMock()
        provider._executor = MagicMock()

        audio_bytes = (np.zeros(1000, dtype=np.float32) * 32767).astype(np.int16).tobytes()

        with patch.object(provider, "synthesize", new_callable=AsyncMock) as mock_synth:
            mock_synth.return_value = audio_bytes

            result = await provider.health_check()

            assert result.status == ProviderHealth.HEALTHY
            assert result.details is not None
            assert result.details["model"] == "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
            assert result.details["language"] == "Portuguese"
            assert result.details["device"] == "cpu"
