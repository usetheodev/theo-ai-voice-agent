"""Tests for Deepgram ASR provider.

Tests cover:
- Configuration
- API key handling
- WebSocket URL building
- Streaming transcription (mocked)
- Error handling
"""

import asyncio
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from voice_pipeline.providers.asr.deepgram import (
    DeepgramASRProvider,
    DeepgramASRConfig,
    DeepgramASR,
)
from voice_pipeline.interfaces.asr import TranscriptionResult


# =============================================================================
# Configuration Tests
# =============================================================================


class TestDeepgramASRConfig:
    """Tests for DeepgramASRConfig."""

    def test_default_values(self):
        """Test default configuration values."""
        config = DeepgramASRConfig()

        assert config.model == "nova-2"
        assert config.language == "en-US"
        assert config.sample_rate == 16000
        assert config.encoding == "linear16"
        assert config.channels == 1
        assert config.punctuate is True
        assert config.smart_format is True
        assert config.interim_results is True
        assert config.endpointing == 300

    def test_custom_values(self):
        """Test custom configuration values."""
        config = DeepgramASRConfig(
            model="nova-2-phonecall",
            language="pt-BR",
            sample_rate=8000,
            diarize=True,
            interim_results=False,
        )

        assert config.model == "nova-2-phonecall"
        assert config.language == "pt-BR"
        assert config.sample_rate == 8000
        assert config.diarize is True
        assert config.interim_results is False


# =============================================================================
# Provider Initialization Tests
# =============================================================================


class TestDeepgramASRProviderInit:
    """Tests for DeepgramASRProvider initialization."""

    def test_default_initialization(self):
        """Test default initialization."""
        provider = DeepgramASRProvider()

        assert provider.provider_name == "deepgram"
        assert provider.name == "DeepgramASR"
        assert provider._asr_config.model == "nova-2"

    def test_initialization_with_config(self):
        """Test initialization with config object."""
        config = DeepgramASRConfig(
            model="nova",
            language="es",
        )
        provider = DeepgramASRProvider(config=config)

        assert provider._asr_config.model == "nova"
        assert provider._asr_config.language == "es"

    def test_initialization_with_shortcuts(self):
        """Test initialization with shortcut parameters."""
        provider = DeepgramASRProvider(
            model="enhanced",
            language="fr",
            interim_results=False,
        )

        assert provider._asr_config.model == "enhanced"
        assert provider._asr_config.language == "fr"
        assert provider._asr_config.interim_results is False

    def test_alias(self):
        """Test DeepgramASR alias."""
        assert DeepgramASR is DeepgramASRProvider


# =============================================================================
# API Key Tests
# =============================================================================


class TestDeepgramAPIKey:
    """Tests for API key handling."""

    def test_api_key_from_config(self):
        """Test API key from config."""
        provider = DeepgramASRProvider(api_key="test-key-123")

        api_key = provider._get_api_key()
        assert api_key == "test-key-123"

    def test_api_key_from_environment(self):
        """Test API key from environment variable."""
        with patch.dict(os.environ, {"DEEPGRAM_API_KEY": "env-key-456"}):
            provider = DeepgramASRProvider()
            api_key = provider._get_api_key()
            assert api_key == "env-key-456"

    def test_api_key_missing_raises_error(self):
        """Test that missing API key raises error."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove DEEPGRAM_API_KEY if it exists
            os.environ.pop("DEEPGRAM_API_KEY", None)

            provider = DeepgramASRProvider()

            with pytest.raises(ValueError, match="API key not found"):
                provider._get_api_key()


# =============================================================================
# WebSocket URL Tests
# =============================================================================


class TestDeepgramWebSocketURL:
    """Tests for WebSocket URL building."""

    def test_basic_url(self):
        """Test basic URL construction."""
        provider = DeepgramASRProvider(api_key="test")
        url = provider._build_websocket_url()

        assert url.startswith("wss://api.deepgram.com/v1/listen")
        assert "model=nova-2" in url
        assert "language=en-US" in url
        assert "encoding=linear16" in url
        assert "sample_rate=16000" in url

    def test_url_with_features(self):
        """Test URL with optional features."""
        provider = DeepgramASRProvider(
            api_key="test",
            diarize=True,
            interim_results=True,
            smart_format=True,
        )
        url = provider._build_websocket_url()

        assert "diarize=true" in url
        assert "interim_results=true" in url
        assert "smart_format=true" in url

    def test_url_with_keywords(self):
        """Test URL with keywords."""
        config = DeepgramASRConfig(
            keywords=["voice", "pipeline", "agent"],
        )
        provider = DeepgramASRProvider(config=config, api_key="test")
        url = provider._build_websocket_url()

        assert "keywords=voice" in url
        assert "keywords=pipeline" in url
        assert "keywords=agent" in url


# =============================================================================
# Provider Lifecycle Tests
# =============================================================================


class TestDeepgramASRProviderLifecycle:
    """Tests for provider lifecycle (connect/disconnect)."""

    @pytest.mark.asyncio
    async def test_connect_validates_api_key(self):
        """Test that connect validates API key."""
        provider = DeepgramASRProvider(api_key="test-key")

        await provider.connect()

        assert provider._api_key == "test-key"
        assert provider._connected is True

    @pytest.mark.asyncio
    async def test_disconnect_clears_state(self):
        """Test that disconnect clears state."""
        provider = DeepgramASRProvider(api_key="test-key")
        await provider.connect()

        await provider.disconnect()

        assert provider._api_key is None
        assert provider._connected is False


# =============================================================================
# Streaming Tests (Mocked)
# =============================================================================


class TestDeepgramStreaming:
    """Tests for streaming transcription (mocked WebSocket)."""

    @pytest.mark.asyncio
    async def test_transcribe_stream_requires_connection(self):
        """Test that transcribe_stream requires connection."""
        provider = DeepgramASRProvider(api_key="test-key")
        # Not connected

        async def audio_stream():
            yield b"\x00" * 320

        with pytest.raises(RuntimeError, match="Not connected"):
            async for _ in provider.transcribe_stream(audio_stream()):
                pass

    @pytest.mark.asyncio
    async def test_transcribe_stream_interface(self):
        """Test that transcribe_stream has correct interface."""
        provider = DeepgramASRProvider(api_key="test-key")
        await provider.connect()

        # The method should exist and accept async iterator
        assert hasattr(provider, "transcribe_stream")
        assert callable(provider.transcribe_stream)

        # Method signature should accept audio_stream and optional language
        import inspect
        sig = inspect.signature(provider.transcribe_stream)
        params = list(sig.parameters.keys())
        assert "audio_stream" in params
        assert "language" in params

    @pytest.mark.asyncio
    async def test_transcribe_combines_final_results(self):
        """Test that transcribe combines all final results."""
        provider = DeepgramASRProvider(api_key="test-key")
        await provider.connect()

        # Mock transcribe_stream to return results
        async def mock_transcribe_stream(audio_stream, language=None):
            yield TranscriptionResult(text="Hello", is_final=True, confidence=0.9)
            yield TranscriptionResult(text="world", is_final=True, confidence=0.95)

        with patch.object(provider, "transcribe_stream", mock_transcribe_stream):
            result = await provider.transcribe(b"\x00" * 1000)

        assert result.text == "Hello world"
        assert result.is_final is True


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestDeepgramErrorHandling:
    """Tests for error handling."""

    def test_retryable_errors(self):
        """Test that transient errors are marked as retryable."""
        provider = DeepgramASRProvider(api_key="test")

        retryable_errors = [
            "Connection timeout",
            "Network error",
            "Rate limit exceeded",
            "503 Service Unavailable",
        ]

        from voice_pipeline.providers.base import RetryableError

        for error_msg in retryable_errors:
            with pytest.raises(RetryableError):
                provider._handle_error(Exception(error_msg))

    def test_non_retryable_errors(self):
        """Test that permanent errors are marked as non-retryable."""
        provider = DeepgramASRProvider(api_key="test")

        non_retryable_errors = [
            "Invalid API key",
            "Unauthorized",
            "401 Authentication failed",
            "403 Forbidden",
        ]

        from voice_pipeline.providers.base import NonRetryableError

        for error_msg in non_retryable_errors:
            with pytest.raises(NonRetryableError):
                provider._handle_error(Exception(error_msg))


# =============================================================================
# Repr Tests
# =============================================================================


class TestDeepgramRepr:
    """Tests for string representation."""

    def test_repr(self):
        """Test __repr__ output."""
        provider = DeepgramASRProvider(
            model="nova-2",
            language="pt-BR",
            interim_results=True,
        )

        repr_str = repr(provider)

        assert "DeepgramASRProvider" in repr_str
        assert "nova-2" in repr_str
        assert "pt-BR" in repr_str
        assert "interim_results=True" in repr_str


# =============================================================================
# Integration with VoiceAgentBuilder Tests
# =============================================================================


class TestDeepgramBuilderIntegration:
    """Tests for integration with VoiceAgentBuilder."""

    def test_builder_accepts_deepgram(self):
        """Test that builder accepts deepgram as ASR provider."""
        from voice_pipeline.agents.base import VoiceAgentBuilder

        builder = VoiceAgentBuilder()

        # Should not raise
        builder.asr("deepgram", api_key="test-key", language="pt-BR")

        assert builder._asr_provider == "deepgram"
        assert builder._asr_kwargs["api_key"] == "test-key"
        assert builder._asr_kwargs["language"] == "pt-BR"
