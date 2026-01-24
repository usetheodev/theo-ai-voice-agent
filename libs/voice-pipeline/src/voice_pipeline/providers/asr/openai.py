"""OpenAI ASR (Whisper) provider.

OpenAI's Whisper API for automatic speech recognition.
Supports multiple languages and response formats.

Reference: https://platform.openai.com/docs/guides/speech-to-text
"""

import io
import os
import time
import wave
from dataclasses import dataclass
from typing import AsyncIterator, Literal, Optional

from voice_pipeline.interfaces.asr import ASRInterface, TranscriptionResult
from voice_pipeline.providers.base import (
    BaseProvider,
    HealthCheckResult,
    ProviderConfig,
    ProviderHealth,
    RetryableError,
    NonRetryableError,
)


# Available response formats
WhisperResponseFormat = Literal["json", "text", "srt", "verbose_json", "vtt"]


@dataclass
class OpenAIASRConfig(ProviderConfig):
    """Configuration for OpenAI ASR (Whisper) provider.

    Attributes:
        model: Whisper model (whisper-1).
        language: Default language code (ISO-639-1).
        response_format: Response format from Whisper API.
        temperature: Sampling temperature for decoding.
        sample_rate: Input audio sample rate in Hz.
        api_key: OpenAI API key. Falls back to OPENAI_API_KEY env var.

    Example:
        >>> config = OpenAIASRConfig(
        ...     language="en",
        ...     temperature=0.0,
        ... )
        >>> asr = OpenAIASRProvider(config=config)
    """

    model: str = "whisper-1"
    """Whisper model (currently only whisper-1 available)."""

    language: Optional[str] = None
    """Default language code (ISO-639-1). None for auto-detection."""

    response_format: WhisperResponseFormat = "verbose_json"
    """Response format from API."""

    temperature: float = 0.0
    """Sampling temperature (0.0 for deterministic)."""

    sample_rate: int = 16000
    """Input audio sample rate in Hz."""

    prompt: Optional[str] = None
    """Optional prompt to guide transcription style."""


class OpenAIASRProvider(BaseProvider, ASRInterface):
    """OpenAI ASR provider using Whisper.

    Uses OpenAI's Whisper API for speech-to-text transcription.
    Note: OpenAI's Whisper API is batch-only (not streaming).

    Features:
    - Multiple language support
    - Automatic language detection
    - Timestamps in verbose_json mode
    - Word-level timing (with verbose_json)

    Example:
        >>> asr = OpenAIASRProvider(
        ...     language="en",
        ...     api_key="sk-...",
        ... )
        >>> await asr.connect()
        >>>
        >>> # Transcribe audio
        >>> result = await asr.transcribe(audio_bytes)
        >>> print(result.text)
        >>>
        >>> # Or use with pipeline
        >>> chain = asr | llm | tts
        >>> await chain.ainvoke(audio_bytes)

    Attributes:
        provider_name: "openai-asr"
        name: "OpenAIASR" (for VoiceRunnable)
    """

    provider_name: str = "openai-asr"
    name: str = "OpenAIASR"

    def __init__(
        self,
        config: Optional[OpenAIASRConfig] = None,
        model: Optional[str] = None,
        language: Optional[str] = None,
        api_key: Optional[str] = None,
        **kwargs,
    ):
        """Initialize OpenAI ASR provider.

        Args:
            config: Full configuration object.
            model: Whisper model (shortcut).
            language: Default language (shortcut).
            api_key: OpenAI API key (shortcut).
            **kwargs: Additional configuration options.
        """
        # Build config from parameters
        if config is None:
            config = OpenAIASRConfig()

        # Apply shortcuts
        if model is not None:
            config.model = model
        if language is not None:
            config.language = language
        if api_key is not None:
            config.api_key = api_key

        super().__init__(config=config, **kwargs)

        self._asr_config: OpenAIASRConfig = config
        self._client = None
        self._async_client = None

    @property
    def sample_rate(self) -> int:
        """Expected input sample rate."""
        return self._asr_config.sample_rate

    async def connect(self) -> None:
        """Initialize OpenAI client."""
        await super().connect()

        try:
            from openai import AsyncOpenAI, OpenAI
        except ImportError:
            raise ImportError(
                "openai is required for OpenAI ASR. "
                "Install with: pip install openai"
            )

        # Get API key
        api_key = self._asr_config.api_key or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError(
                "OpenAI API key is required. "
                "Set OPENAI_API_KEY environment variable or pass api_key parameter."
            )

        # Build client kwargs
        client_kwargs = {"api_key": api_key}

        if self._asr_config.api_base:
            client_kwargs["base_url"] = self._asr_config.api_base

        if self._asr_config.timeout:
            client_kwargs["timeout"] = self._asr_config.timeout

        # Create clients
        self._client = OpenAI(**client_kwargs)
        self._async_client = AsyncOpenAI(**client_kwargs)

    async def disconnect(self) -> None:
        """Close OpenAI client."""
        if self._async_client:
            await self._async_client.close()
        self._async_client = None
        self._client = None
        await super().disconnect()

    async def _do_health_check(self) -> HealthCheckResult:
        """Check if OpenAI Whisper API is accessible."""
        if self._async_client is None:
            return HealthCheckResult(
                status=ProviderHealth.UNHEALTHY,
                message="Client not initialized. Call connect() first.",
            )

        try:
            # Create minimal audio for test (1 second of silence)
            test_audio = self._create_wav_bytes(b"\x00" * (self._asr_config.sample_rate * 2))

            # Test API call
            response = await self._async_client.audio.transcriptions.create(
                model=self._asr_config.model,
                file=("test.wav", test_audio, "audio/wav"),
            )

            return HealthCheckResult(
                status=ProviderHealth.HEALTHY,
                message=f"OpenAI Whisper API accessible. Model: {self._asr_config.model}",
                details={"model": self._asr_config.model},
            )

        except Exception as e:
            return HealthCheckResult(
                status=ProviderHealth.UNHEALTHY,
                message=f"OpenAI Whisper API error: {e}",
            )

    def _create_wav_bytes(self, pcm_data: bytes) -> bytes:
        """Convert PCM16 data to WAV format.

        Args:
            pcm_data: Raw PCM16 audio data.

        Returns:
            WAV-formatted audio data.
        """
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)  # Mono
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(self._asr_config.sample_rate)
            wav_file.writeframes(pcm_data)
        buffer.seek(0)
        return buffer.read()

    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        language: Optional[str] = None,
    ) -> AsyncIterator[TranscriptionResult]:
        """Transcribe audio stream.

        Note: OpenAI Whisper API is batch-only, so this collects all audio
        and transcribes at once. For true streaming, use a different provider.

        Args:
            audio_stream: Async iterator of audio chunks (PCM16, mono).
            language: Optional language code (overrides default).

        Yields:
            TranscriptionResult (single final result).
        """
        if self._async_client is None:
            raise RuntimeError("Client not connected. Call connect() first.")

        # Collect all audio chunks
        audio_chunks = []
        async for chunk in audio_stream:
            audio_chunks.append(chunk)

        if not audio_chunks:
            yield TranscriptionResult(
                text="",
                is_final=True,
                confidence=0.0,
            )
            return

        # Combine audio data
        audio_data = b"".join(audio_chunks)

        # Convert to WAV format
        wav_data = self._create_wav_bytes(audio_data)

        # Transcribe
        effective_language = language or self._asr_config.language

        start_time = time.perf_counter()

        try:
            # Build request kwargs
            request_kwargs = {
                "model": self._asr_config.model,
                "file": ("audio.wav", wav_data, "audio/wav"),
                "response_format": self._asr_config.response_format,
                "temperature": self._asr_config.temperature,
            }

            if effective_language:
                request_kwargs["language"] = effective_language

            if self._asr_config.prompt:
                request_kwargs["prompt"] = self._asr_config.prompt

            response = await self._async_client.audio.transcriptions.create(
                **request_kwargs
            )

            latency_ms = (time.perf_counter() - start_time) * 1000
            self._metrics.record_success(latency_ms)

            # Parse response based on format
            if self._asr_config.response_format == "verbose_json":
                text = response.text
                detected_language = getattr(response, "language", None)
                duration = getattr(response, "duration", None)

                yield TranscriptionResult(
                    text=text,
                    is_final=True,
                    confidence=1.0,  # Whisper doesn't provide confidence
                    language=detected_language,
                    start_time=0.0 if duration else None,
                    end_time=duration,
                )
            elif self._asr_config.response_format == "json":
                text = response.text
                yield TranscriptionResult(
                    text=text,
                    is_final=True,
                    confidence=1.0,
                )
            else:
                # text, srt, vtt formats return string directly
                text = response if isinstance(response, str) else str(response)
                yield TranscriptionResult(
                    text=text,
                    is_final=True,
                    confidence=1.0,
                )

        except Exception as e:
            self._metrics.record_failure(str(e))
            self._handle_error(e)
            raise

    async def transcribe(
        self,
        audio_data: bytes,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe complete audio data.

        Args:
            audio_data: Complete audio data (PCM16, mono).
            language: Optional language code.

        Returns:
            Final transcription result.
        """
        if self._async_client is None:
            raise RuntimeError("Client not connected. Call connect() first.")

        # Convert to WAV format
        wav_data = self._create_wav_bytes(audio_data)

        effective_language = language or self._asr_config.language

        start_time = time.perf_counter()

        try:
            request_kwargs = {
                "model": self._asr_config.model,
                "file": ("audio.wav", wav_data, "audio/wav"),
                "response_format": self._asr_config.response_format,
                "temperature": self._asr_config.temperature,
            }

            if effective_language:
                request_kwargs["language"] = effective_language

            if self._asr_config.prompt:
                request_kwargs["prompt"] = self._asr_config.prompt

            response = await self._async_client.audio.transcriptions.create(
                **request_kwargs
            )

            latency_ms = (time.perf_counter() - start_time) * 1000
            self._metrics.record_success(latency_ms)

            # Parse response
            if self._asr_config.response_format in ("verbose_json", "json"):
                text = response.text
                detected_language = getattr(response, "language", None)
                duration = getattr(response, "duration", None)

                return TranscriptionResult(
                    text=text,
                    is_final=True,
                    confidence=1.0,
                    language=detected_language,
                    start_time=0.0 if duration else None,
                    end_time=duration,
                )
            else:
                text = response if isinstance(response, str) else str(response)
                return TranscriptionResult(
                    text=text,
                    is_final=True,
                    confidence=1.0,
                )

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
            f"OpenAIASRProvider("
            f"model={self._asr_config.model!r}, "
            f"language={self._asr_config.language!r}, "
            f"connected={self._connected})"
        )
