"""Base interfaces for all providers.

All providers are HTTP/WebSocket clients that call external APIs.
For local execution, run compatible API servers.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional


# =============================================================================
# DATA TYPES
# =============================================================================

@dataclass
class TranscriptionResult:
    """Result from ASR transcription."""
    text: str
    is_final: bool
    confidence: float = 1.0
    language: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    words: Optional[list[dict]] = None  # Word-level timestamps


@dataclass
class LLMResponse:
    """Response chunk from LLM."""
    text: str
    is_complete: bool
    finish_reason: Optional[str] = None
    usage: Optional[dict] = None


@dataclass
class AudioChunk:
    """Audio chunk from TTS."""
    data: bytes
    sample_rate: int = 24000
    channels: int = 1
    format: str = "pcm16"  # pcm16, mp3, opus
    is_final: bool = False


@dataclass
class VADResult:
    """Result from Voice Activity Detection."""
    is_speech: bool
    confidence: float = 1.0
    start_time: Optional[float] = None
    end_time: Optional[float] = None


# =============================================================================
# PROVIDER BASE CLASS
# =============================================================================

class BaseProvider(ABC):
    """Base class for all providers."""

    def __init__(
        self,
        api_base: str,
        api_key: Optional[str] = None,
        timeout: float = 30.0,
        **kwargs,
    ):
        """Initialize provider.

        Args:
            api_base: Base URL for the API.
            api_key: Optional API key for authentication.
            timeout: Request timeout in seconds.
        """
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.extra_config = kwargs

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name (e.g., 'openai', 'deepgram')."""
        pass

    @property
    def is_available(self) -> bool:
        """Check if provider is configured and available."""
        return bool(self.api_base)

    def _get_headers(self) -> dict[str, str]:
        """Get common headers for requests."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers


# =============================================================================
# ASR PROVIDER
# =============================================================================

class ASRProvider(BaseProvider):
    """Interface for ASR (Speech-to-Text) providers.

    Implementations should call external APIs (Deepgram, OpenAI Whisper, etc.).
    For local: run faster-whisper-server or whisper.cpp server.
    """

    @property
    @abstractmethod
    def supports_streaming(self) -> bool:
        """Whether provider supports real-time streaming transcription."""
        pass

    @abstractmethod
    async def transcribe(
        self,
        audio_data: bytes,
        language: Optional[str] = None,
        **kwargs,
    ) -> TranscriptionResult:
        """Transcribe complete audio file.

        Args:
            audio_data: Audio bytes (WAV, MP3, etc.).
            language: Optional language hint.

        Returns:
            Transcription result.
        """
        pass

    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        language: Optional[str] = None,
        **kwargs,
    ) -> AsyncIterator[TranscriptionResult]:
        """Transcribe audio in real-time streaming.

        Args:
            audio_stream: Async iterator of audio chunks.
            language: Optional language hint.

        Yields:
            Partial and final transcription results.
        """
        # Default: collect all audio and transcribe at end
        chunks = []
        async for chunk in audio_stream:
            chunks.append(chunk)

        if chunks:
            result = await self.transcribe(b"".join(chunks), language, **kwargs)
            yield result


# =============================================================================
# LLM PROVIDER
# =============================================================================

class LLMProvider(BaseProvider):
    """Interface for LLM providers.

    Implementations should call external APIs (OpenAI, Groq, Anthropic, etc.).
    For local: run Ollama, vLLM, or llama.cpp server.
    """

    @property
    @abstractmethod
    def supports_streaming(self) -> bool:
        """Whether provider supports streaming token generation."""
        pass

    @abstractmethod
    async def generate(
        self,
        messages: list[dict[str, str]],
        system_prompt: Optional[str] = None,
        max_tokens: int = 256,
        temperature: float = 0.7,
        **kwargs,
    ) -> LLMResponse:
        """Generate complete response.

        Args:
            messages: Conversation history [{"role": "user", "content": "..."}].
            system_prompt: Optional system prompt.
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature.

        Returns:
            Complete LLM response.
        """
        pass

    @abstractmethod
    async def generate_stream(
        self,
        messages: list[dict[str, str]],
        system_prompt: Optional[str] = None,
        max_tokens: int = 256,
        temperature: float = 0.7,
        **kwargs,
    ) -> AsyncIterator[LLMResponse]:
        """Generate response with streaming.

        Args:
            messages: Conversation history.
            system_prompt: Optional system prompt.
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature.

        Yields:
            Response chunks as they're generated.
        """
        pass


# =============================================================================
# TTS PROVIDER
# =============================================================================

class TTSProvider(BaseProvider):
    """Interface for TTS (Text-to-Speech) providers.

    Implementations should call external APIs (ElevenLabs, OpenAI TTS, etc.).
    For local: run Piper HTTP server or Coqui server.
    """

    @property
    @abstractmethod
    def supports_streaming(self) -> bool:
        """Whether provider supports streaming audio generation."""
        pass

    @property
    @abstractmethod
    def available_voices(self) -> list[str]:
        """List of available voice IDs."""
        pass

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        **kwargs,
    ) -> AudioChunk:
        """Synthesize complete text to audio.

        Args:
            text: Text to synthesize.
            voice: Voice ID to use.

        Returns:
            Complete audio data.
        """
        pass

    async def synthesize_stream(
        self,
        text: str,
        voice: Optional[str] = None,
        **kwargs,
    ) -> AsyncIterator[AudioChunk]:
        """Synthesize text with streaming audio output.

        Args:
            text: Text to synthesize.
            voice: Voice ID to use.

        Yields:
            Audio chunks as they're generated.
        """
        # Default: synthesize all and return as single chunk
        result = await self.synthesize(text, voice, **kwargs)
        result.is_final = True
        yield result


# =============================================================================
# VAD PROVIDER
# =============================================================================

class VADProvider(BaseProvider):
    """Interface for VAD (Voice Activity Detection) providers.

    VAD is typically local (Silero is ~1MB) but can also be API-based.
    """

    def __init__(
        self,
        api_base: str = "",  # VAD often runs locally
        threshold: float = 0.5,
        min_speech_duration_ms: int = 250,
        min_silence_duration_ms: int = 100,
        **kwargs,
    ):
        """Initialize VAD provider.

        Args:
            api_base: Base URL if using API-based VAD.
            threshold: Speech detection threshold (0-1).
            min_speech_duration_ms: Minimum speech duration to detect.
            min_silence_duration_ms: Minimum silence to end speech.
        """
        super().__init__(api_base, **kwargs)
        self.threshold = threshold
        self.min_speech_duration_ms = min_speech_duration_ms
        self.min_silence_duration_ms = min_silence_duration_ms

    @abstractmethod
    async def process(
        self,
        audio_chunk: bytes,
        sample_rate: int = 16000,
    ) -> VADResult:
        """Process audio chunk and detect voice activity.

        Args:
            audio_chunk: Raw PCM audio bytes.
            sample_rate: Audio sample rate.

        Returns:
            VAD result with speech detection.
        """
        pass

    @abstractmethod
    def reset(self) -> None:
        """Reset VAD state for new utterance."""
        pass
