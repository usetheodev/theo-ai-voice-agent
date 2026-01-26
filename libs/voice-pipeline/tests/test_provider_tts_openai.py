"""Tests for OpenAI TTS provider."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from voice_pipeline.interfaces.tts import AudioChunk
from voice_pipeline.providers.base import (
    HealthCheckResult,
    ProviderHealth,
    RetryableError,
    NonRetryableError,
)
from voice_pipeline.providers.tts import OpenAITTSProvider, OpenAITTSConfig


class TestOpenAITTSConfig:
    """Tests for OpenAITTSConfig."""

    def test_default_values(self):
        """Test default configuration values."""
        config = OpenAITTSConfig()

        assert config.model == "tts-1"
        assert config.voice == "alloy"
        assert config.speed == 1.0
        assert config.response_format == "pcm"
        assert config.api_key is None

    def test_custom_values(self):
        """Test custom configuration values."""
        config = OpenAITTSConfig(
            model="tts-1-hd",
            voice="nova",
            speed=1.25,
            response_format="mp3",
            api_key="sk-test",
        )

        assert config.model == "tts-1-hd"
        assert config.voice == "nova"
        assert config.speed == 1.25
        assert config.response_format == "mp3"
        assert config.api_key == "sk-test"


class TestOpenAITTSProviderInit:
    """Tests for OpenAITTSProvider initialization."""

    def test_default_initialization(self):
        """Test provider with default config."""
        provider = OpenAITTSProvider()

        assert provider.provider_name == "openai-tts"
        assert provider.name == "OpenAITTS"
        assert provider._tts_config.model == "tts-1"
        assert provider._tts_config.voice == "alloy"
        assert provider.is_connected is False

    def test_initialization_with_config(self):
        """Test provider with custom config."""
        config = OpenAITTSConfig(model="tts-1-hd", voice="echo")
        provider = OpenAITTSProvider(config=config)

        assert provider._tts_config.model == "tts-1-hd"
        assert provider._tts_config.voice == "echo"

    def test_initialization_with_shortcuts(self):
        """Test provider with shortcut parameters."""
        provider = OpenAITTSProvider(
            model="tts-1-hd",
            voice="nova",
            api_key="sk-shortcut",
            speed=1.5,
        )

        assert provider._tts_config.model == "tts-1-hd"
        assert provider._tts_config.voice == "nova"
        assert provider._tts_config.api_key == "sk-shortcut"
        assert provider._tts_config.speed == 1.5

    def test_shortcuts_override_config(self):
        """Test that shortcuts override config values."""
        config = OpenAITTSConfig(model="tts-1", voice="alloy")
        provider = OpenAITTSProvider(
            config=config,
            model="tts-1-hd",
            voice="fable",
        )

        assert provider._tts_config.model == "tts-1-hd"
        assert provider._tts_config.voice == "fable"

    def test_sample_rate(self):
        """Test sample rate property."""
        provider = OpenAITTSProvider()
        assert provider.sample_rate == 24000

    def test_channels(self):
        """Test channels property."""
        provider = OpenAITTSProvider()
        assert provider.channels == 1

    def test_repr(self):
        """Test string representation."""
        provider = OpenAITTSProvider(model="tts-1-hd", voice="nova")
        repr_str = repr(provider)

        assert "OpenAITTSProvider" in repr_str
        assert "tts-1-hd" in repr_str
        assert "nova" in repr_str
        assert "connected=False" in repr_str


class TestOpenAITTSProviderLifecycle:
    """Tests for provider lifecycle (connect/disconnect)."""

    @pytest.mark.asyncio
    async def test_connect_creates_clients(self):
        """Test that connect creates OpenAI clients."""
        provider = OpenAITTSProvider(api_key="sk-test")

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
        provider = OpenAITTSProvider()

        with patch("openai.AsyncOpenAI") as mock_async:
            with patch("openai.OpenAI"):
                await provider.connect()

                call_kwargs = mock_async.call_args[1]
                assert call_kwargs["api_key"] == "sk-from-env"

    @pytest.mark.asyncio
    async def test_connect_raises_without_api_key(self, monkeypatch):
        """Test that connect raises error without API key."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        provider = OpenAITTSProvider()

        with pytest.raises(ValueError, match="API key is required"):
            await provider.connect()

    @pytest.mark.asyncio
    async def test_disconnect_closes_client(self):
        """Test that disconnect closes the client."""
        provider = OpenAITTSProvider(api_key="sk-test")

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
        provider = OpenAITTSProvider(api_key="sk-test")

        with patch("openai.AsyncOpenAI") as mock_async:
            with patch("openai.OpenAI"):
                mock_client = AsyncMock()
                mock_async.return_value = mock_client

                async with provider as p:
                    assert p.is_connected is True

                assert provider.is_connected is False


class TestOpenAITTSProviderHealthCheck:
    """Tests for health check functionality."""

    @pytest.mark.asyncio
    async def test_health_check_unhealthy_when_not_connected(self):
        """Test health check returns unhealthy when not connected."""
        provider = OpenAITTSProvider(api_key="sk-test")

        result = await provider.health_check()

        assert result.status == ProviderHealth.UNHEALTHY
        assert "not initialized" in result.message.lower()

    @pytest.mark.asyncio
    async def test_health_check_healthy_when_connected(self):
        """Test health check returns healthy when API is accessible."""
        provider = OpenAITTSProvider(api_key="sk-test")

        mock_response = MagicMock()
        mock_response.read.return_value = b"audio_data"

        mock_client = AsyncMock()
        mock_client.audio.speech.create = AsyncMock(return_value=mock_response)
        provider._async_client = mock_client

        result = await provider.health_check()

        assert result.status == ProviderHealth.HEALTHY
        assert result.latency_ms is not None

    @pytest.mark.asyncio
    async def test_health_check_unhealthy_on_error(self):
        """Test health check returns unhealthy on API error."""
        provider = OpenAITTSProvider(api_key="sk-test")

        mock_client = AsyncMock()
        mock_client.audio.speech.create = AsyncMock(
            side_effect=Exception("API error")
        )
        provider._async_client = mock_client

        result = await provider.health_check()

        assert result.status == ProviderHealth.UNHEALTHY
        assert "API error" in result.message


class TestOpenAITTSProviderSynthesize:
    """Tests for text synthesis."""

    @pytest.mark.asyncio
    async def test_synthesize_raises_without_client(self):
        """Test synthesize raises error when not connected."""
        provider = OpenAITTSProvider(api_key="sk-test")

        with pytest.raises(RuntimeError, match="not connected"):
            await provider.synthesize("Hello")

    @pytest.mark.asyncio
    async def test_synthesize_basic(self):
        """Test basic synthesis."""
        provider = OpenAITTSProvider(api_key="sk-test")

        mock_response = MagicMock()
        mock_response.read.return_value = b"audio_data_here"

        mock_client = AsyncMock()
        mock_client.audio.speech.create = AsyncMock(return_value=mock_response)
        provider._async_client = mock_client

        result = await provider.synthesize("Hello, world!")

        assert result == b"audio_data_here"

        # Check API call
        call_kwargs = mock_client.audio.speech.create.call_args[1]
        assert call_kwargs["input"] == "Hello, world!"
        assert call_kwargs["model"] == "tts-1"
        assert call_kwargs["voice"] == "alloy"
        assert call_kwargs["speed"] == 1.0

    @pytest.mark.asyncio
    async def test_synthesize_with_voice_override(self):
        """Test synthesis with voice override."""
        provider = OpenAITTSProvider(api_key="sk-test", voice="alloy")

        mock_response = MagicMock()
        mock_response.read.return_value = b"audio_data"

        mock_client = AsyncMock()
        mock_client.audio.speech.create = AsyncMock(return_value=mock_response)
        provider._async_client = mock_client

        await provider.synthesize("Test", voice="nova")

        call_kwargs = mock_client.audio.speech.create.call_args[1]
        assert call_kwargs["voice"] == "nova"

    @pytest.mark.asyncio
    async def test_synthesize_with_speed(self):
        """Test synthesis with speed parameter."""
        provider = OpenAITTSProvider(api_key="sk-test")

        mock_response = MagicMock()
        mock_response.read.return_value = b"audio_data"

        mock_client = AsyncMock()
        mock_client.audio.speech.create = AsyncMock(return_value=mock_response)
        provider._async_client = mock_client

        await provider.synthesize("Test", speed=1.5)

        call_kwargs = mock_client.audio.speech.create.call_args[1]
        assert call_kwargs["speed"] == 1.5

    @pytest.mark.asyncio
    async def test_synthesize_records_metrics(self):
        """Test that synthesis records metrics."""
        provider = OpenAITTSProvider(api_key="sk-test")

        mock_response = MagicMock()
        mock_response.read.return_value = b"audio_data"

        mock_client = AsyncMock()
        mock_client.audio.speech.create = AsyncMock(return_value=mock_response)
        provider._async_client = mock_client

        await provider.synthesize("Test")

        assert provider.metrics.successful_requests == 1
        assert provider.metrics.total_requests == 1


def _make_streaming_mock_client(*audio_chunks_list):
    """Create a mock client that simulates with_streaming_response.

    Args:
        audio_chunks_list: For each text input, a list of bytes chunks
                          to yield via aiter_bytes. If a single bytes is
                          given, it is wrapped in a list.
    """
    call_count = 0

    class MockStreamingResponse:
        def __init__(self, chunks):
            self._chunks = chunks

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def aiter_bytes(self, chunk_size=None):
            for chunk in self._chunks:
                yield chunk

    class MockStreamingCreate:
        def create(self_, **kwargs):
            """Returns an async context manager (not a coroutine)."""
            nonlocal call_count
            idx = min(call_count, len(audio_chunks_list) - 1)
            chunks = audio_chunks_list[idx]
            if isinstance(chunks, bytes):
                chunks = [chunks]
            call_count += 1
            return MockStreamingResponse(chunks)

    mock_client = AsyncMock()
    mock_client.audio.speech.with_streaming_response = MockStreamingCreate()
    return mock_client


class TestOpenAITTSProviderSynthesizeStream:
    """Tests for streaming synthesis."""

    @pytest.mark.asyncio
    async def test_synthesize_stream_raises_without_client(self):
        """Test synthesize_stream raises error when not connected."""
        provider = OpenAITTSProvider(api_key="sk-test")

        async def text_gen():
            yield "Hello"

        with pytest.raises(RuntimeError, match="not connected"):
            async for _ in provider.synthesize_stream(text_gen()):
                pass

    @pytest.mark.asyncio
    async def test_synthesize_stream_basic(self):
        """Test basic streaming synthesis with real HTTP streaming."""
        provider = OpenAITTSProvider(api_key="sk-test")

        provider._async_client = _make_streaming_mock_client(
            [b"audio_data"],
            [b"audio_data"],
        )

        async def text_gen():
            yield "Hello."
            yield "World."

        chunks = []
        async for chunk in provider.synthesize_stream(text_gen()):
            chunks.append(chunk)

        assert len(chunks) == 2
        for chunk in chunks:
            assert isinstance(chunk, AudioChunk)
            assert chunk.data == b"audio_data"
            assert chunk.sample_rate == 24000
            assert chunk.channels == 1

    @pytest.mark.asyncio
    async def test_synthesize_stream_multiple_chunks_per_sentence(self):
        """Test that multiple audio chunks are emitted per sentence."""
        provider = OpenAITTSProvider(api_key="sk-test")

        provider._async_client = _make_streaming_mock_client(
            [b"chunk1", b"chunk2", b"chunk3"],
        )

        async def text_gen():
            yield "Hello world."

        chunks = []
        async for chunk in provider.synthesize_stream(text_gen()):
            chunks.append(chunk)

        assert len(chunks) == 3
        assert chunks[0].data == b"chunk1"
        assert chunks[1].data == b"chunk2"
        assert chunks[2].data == b"chunk3"

    @pytest.mark.asyncio
    async def test_synthesize_stream_skips_empty(self):
        """Test that stream skips empty text."""
        provider = OpenAITTSProvider(api_key="sk-test")

        provider._async_client = _make_streaming_mock_client(
            [b"audio_data"],
            [b"audio_data"],
        )

        async def text_gen():
            yield "Hello."
            yield ""  # Empty - should be skipped
            yield "   "  # Whitespace - should be skipped
            yield "World."

        chunks = []
        async for chunk in provider.synthesize_stream(text_gen()):
            chunks.append(chunk)

        assert len(chunks) == 2  # Only non-empty texts


class TestOpenAITTSProviderErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_retryable_error_rate_limit(self):
        """Test rate limit error is retryable."""
        provider = OpenAITTSProvider(api_key="sk-test")

        mock_client = AsyncMock()
        mock_client.audio.speech.create = AsyncMock(
            side_effect=Exception("Rate limit exceeded")
        )
        provider._async_client = mock_client

        with pytest.raises(RetryableError):
            await provider.synthesize("Test")

    @pytest.mark.asyncio
    async def test_retryable_error_timeout(self):
        """Test timeout error is retryable."""
        provider = OpenAITTSProvider(api_key="sk-test")

        mock_client = AsyncMock()
        mock_client.audio.speech.create = AsyncMock(
            side_effect=Exception("Connection timeout")
        )
        provider._async_client = mock_client

        with pytest.raises(RetryableError):
            await provider.synthesize("Test")

    @pytest.mark.asyncio
    async def test_non_retryable_error_invalid_key(self):
        """Test invalid API key error is non-retryable."""
        provider = OpenAITTSProvider(api_key="sk-test")

        mock_client = AsyncMock()
        mock_client.audio.speech.create = AsyncMock(
            side_effect=Exception("Invalid API key")
        )
        provider._async_client = mock_client

        with pytest.raises(NonRetryableError):
            await provider.synthesize("Test")

    @pytest.mark.asyncio
    async def test_error_records_metrics(self):
        """Test that errors are recorded in metrics."""
        provider = OpenAITTSProvider(api_key="sk-test")

        mock_client = AsyncMock()
        mock_client.audio.speech.create = AsyncMock(
            side_effect=Exception("Some error")
        )
        provider._async_client = mock_client

        try:
            await provider.synthesize("Test")
        except Exception:
            pass

        assert provider.metrics.failed_requests == 1
        assert provider.metrics.last_error is not None


class TestOpenAITTSProviderVoiceRunnable:
    """Tests for VoiceRunnable interface."""

    @pytest.mark.asyncio
    async def test_ainvoke_with_string(self):
        """Test ainvoke with string input."""
        provider = OpenAITTSProvider(api_key="sk-test")

        mock_response = MagicMock()
        mock_response.read.return_value = b"audio_data"

        mock_client = AsyncMock()
        mock_client.audio.speech.create = AsyncMock(return_value=mock_response)
        provider._async_client = mock_client

        result = await provider.ainvoke("Hello, world!")

        assert isinstance(result, AudioChunk)
        assert result.data == b"audio_data"

    @pytest.mark.asyncio
    async def test_ainvoke_with_dict(self):
        """Test ainvoke with dict input."""
        provider = OpenAITTSProvider(api_key="sk-test")

        mock_response = MagicMock()
        mock_response.read.return_value = b"audio_data"

        mock_client = AsyncMock()
        mock_client.audio.speech.create = AsyncMock(return_value=mock_response)
        provider._async_client = mock_client

        result = await provider.ainvoke({"text": "Hello"})

        assert isinstance(result, AudioChunk)

    @pytest.mark.asyncio
    async def test_ainvoke_with_async_iterator(self):
        """Test ainvoke with async iterator input."""
        provider = OpenAITTSProvider(api_key="sk-test")

        # ainvoke with async iterator goes through synthesize_stream (streaming)
        provider._async_client = _make_streaming_mock_client(
            [b"audio_data"],
            [b"audio_data"],
        )
        # Also need create for non-streaming paths
        mock_response = MagicMock()
        mock_response.read.return_value = b"audio_data"
        provider._async_client.audio.speech.create = AsyncMock(return_value=mock_response)

        async def text_gen():
            yield "Hello."
            yield "World."

        result = await provider.ainvoke(text_gen())

        assert isinstance(result, AudioChunk)
        # Should have concatenated audio from both chunks
        assert result.data == b"audio_dataaudio_data"

    @pytest.mark.asyncio
    async def test_astream(self):
        """Test astream method."""
        provider = OpenAITTSProvider(api_key="sk-test")

        provider._async_client = _make_streaming_mock_client(
            [b"audio_chunk"],
        )

        chunks = []
        async for chunk in provider.astream("Hello, world!"):
            chunks.append(chunk)

        assert len(chunks) == 1
        assert chunks[0].data == b"audio_chunk"
