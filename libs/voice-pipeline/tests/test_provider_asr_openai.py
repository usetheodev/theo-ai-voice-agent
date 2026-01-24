"""Tests for OpenAI ASR (Whisper) provider."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from voice_pipeline.interfaces.asr import TranscriptionResult
from voice_pipeline.providers.base import (
    HealthCheckResult,
    ProviderHealth,
    RetryableError,
    NonRetryableError,
)
from voice_pipeline.providers.asr import OpenAIASRProvider, OpenAIASRConfig


class TestOpenAIASRConfig:
    """Tests for OpenAIASRConfig."""

    def test_default_values(self):
        """Test default configuration values."""
        config = OpenAIASRConfig()

        assert config.model == "whisper-1"
        assert config.language is None
        assert config.response_format == "verbose_json"
        assert config.temperature == 0.0
        assert config.sample_rate == 16000
        assert config.api_key is None
        assert config.prompt is None

    def test_custom_values(self):
        """Test custom configuration values."""
        config = OpenAIASRConfig(
            model="whisper-1",
            language="en",
            response_format="json",
            temperature=0.2,
            sample_rate=48000,
            api_key="sk-test",
            prompt="Transcribe the following audio:",
        )

        assert config.model == "whisper-1"
        assert config.language == "en"
        assert config.response_format == "json"
        assert config.temperature == 0.2
        assert config.sample_rate == 48000
        assert config.api_key == "sk-test"
        assert config.prompt == "Transcribe the following audio:"


class TestOpenAIASRProviderInit:
    """Tests for OpenAIASRProvider initialization."""

    def test_default_initialization(self):
        """Test provider with default config."""
        provider = OpenAIASRProvider()

        assert provider.provider_name == "openai-asr"
        assert provider.name == "OpenAIASR"
        assert provider._asr_config.model == "whisper-1"
        assert provider._asr_config.language is None
        assert provider.is_connected is False

    def test_initialization_with_config(self):
        """Test provider with custom config."""
        config = OpenAIASRConfig(language="pt", temperature=0.1)
        provider = OpenAIASRProvider(config=config)

        assert provider._asr_config.language == "pt"
        assert provider._asr_config.temperature == 0.1

    def test_initialization_with_shortcuts(self):
        """Test provider with shortcut parameters."""
        provider = OpenAIASRProvider(
            model="whisper-1",
            language="en",
            api_key="sk-shortcut",
        )

        assert provider._asr_config.model == "whisper-1"
        assert provider._asr_config.language == "en"
        assert provider._asr_config.api_key == "sk-shortcut"

    def test_shortcuts_override_config(self):
        """Test that shortcuts override config values."""
        config = OpenAIASRConfig(language="pt")
        provider = OpenAIASRProvider(
            config=config,
            language="en",
        )

        assert provider._asr_config.language == "en"

    def test_sample_rate_property(self):
        """Test sample rate property."""
        provider = OpenAIASRProvider()
        assert provider.sample_rate == 16000

        config = OpenAIASRConfig(sample_rate=48000)
        provider = OpenAIASRProvider(config=config)
        assert provider.sample_rate == 48000

    def test_repr(self):
        """Test string representation."""
        provider = OpenAIASRProvider(language="en")
        repr_str = repr(provider)

        assert "OpenAIASRProvider" in repr_str
        assert "whisper-1" in repr_str
        assert "en" in repr_str
        assert "connected=False" in repr_str


class TestOpenAIASRProviderLifecycle:
    """Tests for provider lifecycle (connect/disconnect)."""

    @pytest.mark.asyncio
    async def test_connect_creates_clients(self):
        """Test that connect creates OpenAI clients."""
        provider = OpenAIASRProvider(api_key="sk-test")

        with patch("openai.AsyncOpenAI") as mock_async:
            with patch("openai.OpenAI") as mock_sync:
                mock_async_instance = MagicMock()
                mock_sync_instance = MagicMock()
                mock_async.return_value = mock_async_instance
                mock_sync.return_value = mock_sync_instance

                await provider.connect()

                assert provider.is_connected is True
                assert provider._async_client is mock_async_instance

    @pytest.mark.asyncio
    async def test_connect_from_env_var(self, monkeypatch):
        """Test connect with API key from environment."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
        provider = OpenAIASRProvider()

        with patch("openai.AsyncOpenAI") as mock_async:
            with patch("openai.OpenAI"):
                await provider.connect()

                call_kwargs = mock_async.call_args[1]
                assert call_kwargs["api_key"] == "sk-from-env"

    @pytest.mark.asyncio
    async def test_connect_raises_without_api_key(self, monkeypatch):
        """Test that connect raises error without API key."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        provider = OpenAIASRProvider()

        with pytest.raises(ValueError, match="API key is required"):
            await provider.connect()

    @pytest.mark.asyncio
    async def test_disconnect_closes_client(self):
        """Test that disconnect closes the client."""
        provider = OpenAIASRProvider(api_key="sk-test")

        mock_async_client = AsyncMock()
        provider._async_client = mock_async_client
        provider._client = MagicMock()
        provider._connected = True

        await provider.disconnect()

        mock_async_client.close.assert_called_once()
        assert provider._async_client is None
        assert provider.is_connected is False

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test async context manager."""
        provider = OpenAIASRProvider(api_key="sk-test")

        with patch("openai.AsyncOpenAI") as mock_async:
            with patch("openai.OpenAI"):
                mock_client = AsyncMock()
                mock_async.return_value = mock_client

                async with provider as p:
                    assert p.is_connected is True

                assert provider.is_connected is False


class TestOpenAIASRProviderHealthCheck:
    """Tests for health check functionality."""

    @pytest.mark.asyncio
    async def test_health_check_unhealthy_when_not_connected(self):
        """Test health check returns unhealthy when not connected."""
        provider = OpenAIASRProvider(api_key="sk-test")

        result = await provider.health_check()

        assert result.status == ProviderHealth.UNHEALTHY
        assert "not initialized" in result.message.lower()

    @pytest.mark.asyncio
    async def test_health_check_healthy_when_connected(self):
        """Test health check returns healthy when API is accessible."""
        provider = OpenAIASRProvider(api_key="sk-test")

        mock_response = MagicMock()
        mock_response.text = ""

        mock_client = AsyncMock()
        mock_client.audio.transcriptions.create = AsyncMock(return_value=mock_response)
        provider._async_client = mock_client

        result = await provider.health_check()

        assert result.status == ProviderHealth.HEALTHY
        assert result.latency_ms is not None

    @pytest.mark.asyncio
    async def test_health_check_unhealthy_on_error(self):
        """Test health check returns unhealthy on API error."""
        provider = OpenAIASRProvider(api_key="sk-test")

        mock_client = AsyncMock()
        mock_client.audio.transcriptions.create = AsyncMock(
            side_effect=Exception("API error")
        )
        provider._async_client = mock_client

        result = await provider.health_check()

        assert result.status == ProviderHealth.UNHEALTHY
        assert "API error" in result.message


class TestOpenAIASRProviderWavConversion:
    """Tests for WAV conversion utility."""

    def test_create_wav_bytes(self):
        """Test PCM to WAV conversion."""
        provider = OpenAIASRProvider(api_key="sk-test")

        # Create 1 second of silence at 16kHz mono
        pcm_data = b"\x00" * (16000 * 2)  # 16-bit = 2 bytes per sample

        wav_data = provider._create_wav_bytes(pcm_data)

        # WAV should start with RIFF header
        assert wav_data[:4] == b"RIFF"
        assert b"WAVE" in wav_data[:12]

    def test_create_wav_bytes_preserves_audio(self):
        """Test that WAV conversion preserves audio data."""
        import wave
        import io

        provider = OpenAIASRProvider(api_key="sk-test")

        # Create test PCM data
        pcm_data = b"\x01\x02" * 1000

        wav_data = provider._create_wav_bytes(pcm_data)

        # Read back and verify
        buffer = io.BytesIO(wav_data)
        with wave.open(buffer, "rb") as wav_file:
            assert wav_file.getnchannels() == 1
            assert wav_file.getsampwidth() == 2
            assert wav_file.getframerate() == 16000
            assert wav_file.readframes(1000) == pcm_data


class TestOpenAIASRProviderTranscribe:
    """Tests for transcription."""

    @pytest.mark.asyncio
    async def test_transcribe_raises_without_client(self):
        """Test transcribe raises error when not connected."""
        provider = OpenAIASRProvider(api_key="sk-test")

        with pytest.raises(RuntimeError, match="not connected"):
            await provider.transcribe(b"audio_data")

    @pytest.mark.asyncio
    async def test_transcribe_basic(self):
        """Test basic transcription."""
        provider = OpenAIASRProvider(api_key="sk-test")

        mock_response = MagicMock()
        mock_response.text = "Hello, world!"
        mock_response.language = "en"
        mock_response.duration = 1.5

        mock_client = AsyncMock()
        mock_client.audio.transcriptions.create = AsyncMock(return_value=mock_response)
        provider._async_client = mock_client

        # Create dummy audio
        audio_data = b"\x00" * (16000 * 2)  # 1 second

        result = await provider.transcribe(audio_data)

        assert isinstance(result, TranscriptionResult)
        assert result.text == "Hello, world!"
        assert result.is_final is True
        assert result.language == "en"
        assert result.end_time == 1.5

    @pytest.mark.asyncio
    async def test_transcribe_with_language(self):
        """Test transcription with language override."""
        provider = OpenAIASRProvider(api_key="sk-test", language="en")

        mock_response = MagicMock()
        mock_response.text = "Olá mundo"

        mock_client = AsyncMock()
        mock_client.audio.transcriptions.create = AsyncMock(return_value=mock_response)
        provider._async_client = mock_client

        audio_data = b"\x00" * (16000 * 2)

        await provider.transcribe(audio_data, language="pt")

        call_kwargs = mock_client.audio.transcriptions.create.call_args[1]
        assert call_kwargs["language"] == "pt"

    @pytest.mark.asyncio
    async def test_transcribe_uses_default_language(self):
        """Test transcription uses default language from config."""
        config = OpenAIASRConfig(language="de", api_key="sk-test")
        provider = OpenAIASRProvider(config=config)

        mock_response = MagicMock()
        mock_response.text = "Hallo Welt"

        mock_client = AsyncMock()
        mock_client.audio.transcriptions.create = AsyncMock(return_value=mock_response)
        provider._async_client = mock_client

        audio_data = b"\x00" * (16000 * 2)

        await provider.transcribe(audio_data)

        call_kwargs = mock_client.audio.transcriptions.create.call_args[1]
        assert call_kwargs["language"] == "de"

    @pytest.mark.asyncio
    async def test_transcribe_records_metrics(self):
        """Test that transcription records metrics."""
        provider = OpenAIASRProvider(api_key="sk-test")

        mock_response = MagicMock()
        mock_response.text = "Test"

        mock_client = AsyncMock()
        mock_client.audio.transcriptions.create = AsyncMock(return_value=mock_response)
        provider._async_client = mock_client

        audio_data = b"\x00" * (16000 * 2)
        await provider.transcribe(audio_data)

        assert provider.metrics.successful_requests == 1
        assert provider.metrics.total_requests == 1


class TestOpenAIASRProviderTranscribeStream:
    """Tests for streaming transcription."""

    @pytest.mark.asyncio
    async def test_transcribe_stream_raises_without_client(self):
        """Test transcribe_stream raises error when not connected."""
        provider = OpenAIASRProvider(api_key="sk-test")

        async def audio_gen():
            yield b"audio"

        with pytest.raises(RuntimeError, match="not connected"):
            async for _ in provider.transcribe_stream(audio_gen()):
                pass

    @pytest.mark.asyncio
    async def test_transcribe_stream_basic(self):
        """Test basic streaming transcription."""
        provider = OpenAIASRProvider(api_key="sk-test")

        mock_response = MagicMock()
        mock_response.text = "Hello, world!"
        mock_response.language = "en"
        mock_response.duration = 2.0

        mock_client = AsyncMock()
        mock_client.audio.transcriptions.create = AsyncMock(return_value=mock_response)
        provider._async_client = mock_client

        async def audio_gen():
            yield b"\x00" * (16000 * 2)  # 1 second
            yield b"\x00" * (16000 * 2)  # 1 second

        results = []
        async for result in provider.transcribe_stream(audio_gen()):
            results.append(result)

        # Should yield single final result
        assert len(results) == 1
        assert results[0].text == "Hello, world!"
        assert results[0].is_final is True

    @pytest.mark.asyncio
    async def test_transcribe_stream_empty(self):
        """Test streaming with no audio."""
        provider = OpenAIASRProvider(api_key="sk-test")

        mock_client = AsyncMock()
        provider._async_client = mock_client

        async def audio_gen():
            return
            yield  # Makes this an async generator

        results = []
        async for result in provider.transcribe_stream(audio_gen()):
            results.append(result)

        # Should yield empty result
        assert len(results) == 1
        assert results[0].text == ""
        assert results[0].confidence == 0.0


class TestOpenAIASRProviderErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_retryable_error_rate_limit(self):
        """Test rate limit error is retryable."""
        provider = OpenAIASRProvider(api_key="sk-test")

        mock_client = AsyncMock()
        mock_client.audio.transcriptions.create = AsyncMock(
            side_effect=Exception("Rate limit exceeded")
        )
        provider._async_client = mock_client

        audio_data = b"\x00" * (16000 * 2)

        with pytest.raises(RetryableError):
            await provider.transcribe(audio_data)

    @pytest.mark.asyncio
    async def test_retryable_error_timeout(self):
        """Test timeout error is retryable."""
        provider = OpenAIASRProvider(api_key="sk-test")

        mock_client = AsyncMock()
        mock_client.audio.transcriptions.create = AsyncMock(
            side_effect=Exception("Connection timeout")
        )
        provider._async_client = mock_client

        audio_data = b"\x00" * (16000 * 2)

        with pytest.raises(RetryableError):
            await provider.transcribe(audio_data)

    @pytest.mark.asyncio
    async def test_non_retryable_error_invalid_key(self):
        """Test invalid API key error is non-retryable."""
        provider = OpenAIASRProvider(api_key="sk-test")

        mock_client = AsyncMock()
        mock_client.audio.transcriptions.create = AsyncMock(
            side_effect=Exception("Invalid API key")
        )
        provider._async_client = mock_client

        audio_data = b"\x00" * (16000 * 2)

        with pytest.raises(NonRetryableError):
            await provider.transcribe(audio_data)

    @pytest.mark.asyncio
    async def test_error_records_metrics(self):
        """Test that errors are recorded in metrics."""
        provider = OpenAIASRProvider(api_key="sk-test")

        mock_client = AsyncMock()
        mock_client.audio.transcriptions.create = AsyncMock(
            side_effect=Exception("Some error")
        )
        provider._async_client = mock_client

        audio_data = b"\x00" * (16000 * 2)

        try:
            await provider.transcribe(audio_data)
        except Exception:
            pass

        assert provider.metrics.failed_requests == 1
        assert provider.metrics.last_error is not None


class TestOpenAIASRProviderVoiceRunnable:
    """Tests for VoiceRunnable interface."""

    @pytest.mark.asyncio
    async def test_ainvoke_with_bytes(self):
        """Test ainvoke with bytes input."""
        provider = OpenAIASRProvider(api_key="sk-test")

        mock_response = MagicMock()
        mock_response.text = "Hello!"

        mock_client = AsyncMock()
        mock_client.audio.transcriptions.create = AsyncMock(return_value=mock_response)
        provider._async_client = mock_client

        audio_data = b"\x00" * (16000 * 2)
        result = await provider.ainvoke(audio_data)

        assert isinstance(result, TranscriptionResult)
        assert result.text == "Hello!"

    @pytest.mark.asyncio
    async def test_ainvoke_with_async_iterator(self):
        """Test ainvoke with async iterator input."""
        provider = OpenAIASRProvider(api_key="sk-test")

        mock_response = MagicMock()
        mock_response.text = "Streaming test"

        mock_client = AsyncMock()
        mock_client.audio.transcriptions.create = AsyncMock(return_value=mock_response)
        provider._async_client = mock_client

        async def audio_gen():
            yield b"\x00" * (16000 * 2)

        result = await provider.ainvoke(audio_gen())

        assert isinstance(result, TranscriptionResult)
        assert result.text == "Streaming test"

    @pytest.mark.asyncio
    async def test_astream(self):
        """Test astream method."""
        provider = OpenAIASRProvider(api_key="sk-test")

        mock_response = MagicMock()
        mock_response.text = "Streamed result"

        mock_client = AsyncMock()
        mock_client.audio.transcriptions.create = AsyncMock(return_value=mock_response)
        provider._async_client = mock_client

        audio_data = b"\x00" * (16000 * 2)

        results = []
        async for result in provider.astream(audio_data):
            results.append(result)

        assert len(results) == 1
        assert results[0].text == "Streamed result"
