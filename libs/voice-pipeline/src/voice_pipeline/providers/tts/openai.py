"""OpenAI TTS provider.

OpenAI's Text-to-Speech API for high-quality voice synthesis.
Supports multiple voices and two quality levels.

Reference: https://platform.openai.com/docs/guides/text-to-speech
"""

import os
import time
from dataclasses import dataclass
from typing import AsyncIterator, Literal, Optional

from voice_pipeline.interfaces.tts import AudioChunk, TTSInterface
from voice_pipeline.providers.base import (
    BaseProvider,
    HealthCheckResult,
    ProviderConfig,
    ProviderHealth,
    RetryableError,
    NonRetryableError,
)


# Available voices
OpenAIVoice = Literal["alloy", "echo", "fable", "onyx", "nova", "shimmer"]

# Available models
OpenAITTSModel = Literal["tts-1", "tts-1-hd"]

# Available output formats
OpenAITTSFormat = Literal["mp3", "opus", "aac", "flac", "wav", "pcm"]


@dataclass
class OpenAITTSConfig(ProviderConfig):
    """Configuration for OpenAI TTS provider.

    Attributes:
        model: TTS model to use (tts-1 or tts-1-hd).
        voice: Default voice to use.
        speed: Default speech speed (0.25 to 4.0).
        response_format: Audio output format.
        api_key: OpenAI API key. Falls back to OPENAI_API_KEY env var.

    Example:
        >>> config = OpenAITTSConfig(
        ...     model="tts-1-hd",
        ...     voice="nova",
        ...     speed=1.1,
        ... )
        >>> tts = OpenAITTSProvider(config=config)
    """

    model: OpenAITTSModel = "tts-1"
    """TTS model (tts-1 for speed, tts-1-hd for quality)."""

    voice: OpenAIVoice = "alloy"
    """Default voice (alloy, echo, fable, onyx, nova, shimmer)."""

    speed: float = 1.0
    """Default speech speed (0.25 to 4.0)."""

    response_format: OpenAITTSFormat = "pcm"
    """Audio output format (pcm for raw audio, mp3, opus, etc.)."""


class OpenAITTSProvider(BaseProvider, TTSInterface):
    """OpenAI TTS provider.

    Uses OpenAI's Text-to-Speech API for voice synthesis.
    Supports streaming for low-latency voice applications.

    Features:
    - 6 distinct voices
    - Two quality levels (tts-1 and tts-1-hd)
    - Speed control (0.25x to 4x)
    - Multiple output formats

    Voices:
    - alloy: Neutral, balanced
    - echo: Soft, warm
    - fable: Narrative, expressive
    - onyx: Deep, authoritative
    - nova: Friendly, conversational
    - shimmer: Bright, energetic

    Example:
        >>> tts = OpenAITTSProvider(
        ...     voice="nova",
        ...     api_key="sk-...",
        ... )
        >>> await tts.connect()
        >>>
        >>> # Synthesize complete text
        >>> audio = await tts.synthesize("Hello, how are you?")
        >>>
        >>> # Or stream from text stream
        >>> async for chunk in tts.synthesize_stream(text_stream):
        ...     play_audio(chunk.data)

    Attributes:
        provider_name: "openai-tts"
        name: "OpenAITTS" (for VoiceRunnable)
    """

    provider_name: str = "openai-tts"
    name: str = "OpenAITTS"

    def __init__(
        self,
        config: Optional[OpenAITTSConfig] = None,
        model: Optional[str] = None,
        voice: Optional[str] = None,
        api_key: Optional[str] = None,
        speed: Optional[float] = None,
        **kwargs,
    ):
        """Initialize OpenAI TTS provider.

        Args:
            config: Full configuration object.
            model: TTS model (shortcut).
            voice: Default voice (shortcut).
            api_key: OpenAI API key (shortcut).
            speed: Default speed (shortcut).
            **kwargs: Additional configuration options.
        """
        # Build config from parameters
        if config is None:
            config = OpenAITTSConfig()

        # Apply shortcuts
        if model is not None:
            config.model = model
        if voice is not None:
            config.voice = voice
        if api_key is not None:
            config.api_key = api_key
        if speed is not None:
            config.speed = speed

        super().__init__(config=config, **kwargs)

        self._tts_config: OpenAITTSConfig = config
        self._client = None
        self._async_client = None

    @property
    def sample_rate(self) -> int:
        """Sample rate of output audio.

        OpenAI TTS outputs 24kHz audio.
        """
        return 24000

    @property
    def channels(self) -> int:
        """Number of audio channels (mono)."""
        return 1

    async def connect(self) -> None:
        """Initialize OpenAI client."""
        await super().connect()

        try:
            from openai import AsyncOpenAI, OpenAI
        except ImportError:
            raise ImportError(
                "openai is required for OpenAI TTS. "
                "Install with: pip install openai"
            )

        # Get API key
        api_key = self._tts_config.api_key or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError(
                "OpenAI API key is required. "
                "Set OPENAI_API_KEY environment variable or pass api_key parameter."
            )

        # Build client kwargs
        client_kwargs = {"api_key": api_key}

        if self._tts_config.api_base:
            client_kwargs["base_url"] = self._tts_config.api_base

        if self._tts_config.timeout:
            client_kwargs["timeout"] = self._tts_config.timeout

        # Create clients
        self._client = OpenAI(**client_kwargs)
        self._async_client = AsyncOpenAI(**client_kwargs)

    async def disconnect(self) -> None:
        """Close OpenAI client."""
        if self._async_client:
            await self._async_client.close()
        self._async_client = None
        self._client = None
        self._is_warmed_up = False
        await super().disconnect()

    async def warmup(self, text: Optional[str] = None) -> float:
        """Pre-warm the OpenAI TTS connection.

        For cloud APIs like OpenAI, warmup primarily ensures the connection
        is established and the first request is complete. This can help
        reduce latency on subsequent requests due to connection reuse.

        Args:
            text: Custom warmup text. Defaults to "Hello."

        Returns:
            Warmup time in milliseconds.

        Example:
            >>> tts = OpenAITTSProvider(voice="nova", api_key="sk-...")
            >>> await tts.connect()
            >>> warmup_ms = await tts.warmup()
            >>> print(f"OpenAI TTS warmed up in {warmup_ms:.1f}ms")
        """
        if self._async_client is None:
            raise RuntimeError("Client not connected. Call connect() first.")

        warmup_text = text or "Hello."

        start = time.perf_counter()

        # Make a minimal synthesis request to warm up the connection
        _ = await self.synthesize(warmup_text)

        elapsed_ms = (time.perf_counter() - start) * 1000
        self._is_warmed_up = True

        return elapsed_ms

    async def _do_health_check(self) -> HealthCheckResult:
        """Check if OpenAI TTS API is accessible."""
        if self._async_client is None:
            return HealthCheckResult(
                status=ProviderHealth.UNHEALTHY,
                message="Client not initialized. Call connect() first.",
            )

        try:
            # Make a minimal API call
            response = await self._async_client.audio.speech.create(
                model=self._tts_config.model,
                voice=self._tts_config.voice,
                input="test",
                response_format="pcm",
            )

            # Read the response to ensure it worked
            _ = response.read()

            return HealthCheckResult(
                status=ProviderHealth.HEALTHY,
                message=f"OpenAI TTS API accessible. Model: {self._tts_config.model}",
                details={"model": self._tts_config.model, "voice": self._tts_config.voice},
            )

        except Exception as e:
            return HealthCheckResult(
                status=ProviderHealth.UNHEALTHY,
                message=f"OpenAI TTS API error: {e}",
            )

    async def synthesize_stream(
        self,
        text_stream: AsyncIterator[str],
        voice: Optional[str] = None,
        speed: float = 1.0,
        **kwargs,
    ) -> AsyncIterator[AudioChunk]:
        """Synthesize audio from text stream.

        Processes each text chunk (sentence) and yields audio chunks.

        Args:
            text_stream: Async iterator of text chunks (usually sentences).
            voice: Voice identifier (overrides default).
            speed: Speech speed multiplier (0.25 to 4.0).
            **kwargs: Additional parameters (model, response_format).

        Yields:
            AudioChunk objects with synthesized audio.

        Raises:
            RuntimeError: If client is not connected.
        """
        if self._async_client is None:
            raise RuntimeError("Client not connected. Call connect() first.")

        # Use config defaults if not specified
        effective_voice = voice or self._tts_config.voice
        effective_speed = speed or self._tts_config.speed
        model = kwargs.get("model", self._tts_config.model)
        response_format = kwargs.get("response_format", self._tts_config.response_format)

        async for text in text_stream:
            if not text or not text.strip():
                continue

            start_time = time.perf_counter()

            try:
                response = await self._async_client.audio.speech.create(
                    model=model,
                    voice=effective_voice,
                    input=text,
                    speed=effective_speed,
                    response_format=response_format,
                )

                # Read audio data
                audio_data = response.read()

                latency_ms = (time.perf_counter() - start_time) * 1000
                self._metrics.record_success(latency_ms)

                # Calculate duration
                if response_format == "pcm":
                    # PCM16 mono at 24kHz: 2 bytes per sample
                    samples = len(audio_data) // 2
                    duration_ms = (samples / self.sample_rate) * 1000
                else:
                    duration_ms = None

                yield AudioChunk(
                    data=audio_data,
                    sample_rate=self.sample_rate,
                    channels=self.channels,
                    format=response_format,
                    duration_ms=duration_ms,
                )

            except Exception as e:
                self._metrics.record_failure(str(e))
                self._handle_error(e)
                raise

    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        speed: float = 1.0,
        **kwargs,
    ) -> bytes:
        """Synthesize complete audio from text.

        Args:
            text: Text to synthesize.
            voice: Voice identifier (overrides default).
            speed: Speech speed multiplier (0.25 to 4.0).
            **kwargs: Additional parameters.

        Returns:
            Complete audio data.
        """
        if self._async_client is None:
            raise RuntimeError("Client not connected. Call connect() first.")

        effective_voice = voice or self._tts_config.voice
        effective_speed = speed or self._tts_config.speed
        model = kwargs.get("model", self._tts_config.model)
        response_format = kwargs.get("response_format", self._tts_config.response_format)

        start_time = time.perf_counter()

        try:
            response = await self._async_client.audio.speech.create(
                model=model,
                voice=effective_voice,
                input=text,
                speed=effective_speed,
                response_format=response_format,
            )

            audio_data = response.read()

            latency_ms = (time.perf_counter() - start_time) * 1000
            self._metrics.record_success(latency_ms)

            return audio_data

        except Exception as e:
            self._metrics.record_failure(str(e))
            self._handle_error(e)
            raise

    def _handle_error(self, error: Exception) -> None:
        """Convert OpenAI errors to provider errors.

        Args:
            error: Original exception.

        Raises:
            RetryableError: For transient errors.
            NonRetryableError: For permanent errors.
        """
        error_str = str(error).lower()

        # Retryable errors
        if any(x in error_str for x in [
            "rate limit",
            "timeout",
            "connection",
            "server error",
            "503",
            "502",
            "500",
            "overloaded",
        ]):
            raise RetryableError(str(error)) from error

        # Non-retryable errors
        if any(x in error_str for x in [
            "invalid api key",
            "authentication",
            "401",
            "403",
            "invalid",
            "not found",
            "404",
        ]):
            raise NonRetryableError(str(error)) from error

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"OpenAITTSProvider("
            f"model={self._tts_config.model!r}, "
            f"voice={self._tts_config.voice!r}, "
            f"connected={self._connected})"
        )
