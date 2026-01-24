"""TTS (Text-to-Speech) interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator, Optional


@dataclass
class AudioChunk:
    """Audio chunk from TTS synthesis."""

    data: bytes
    """Audio data (PCM16 by default)."""

    sample_rate: int = 24000
    """Sample rate in Hz."""

    channels: int = 1
    """Number of audio channels."""

    format: str = "pcm16"
    """Audio format (pcm16, opus, etc.)."""

    duration_ms: Optional[float] = None
    """Duration in milliseconds (if known)."""


class TTSInterface(ABC):
    """Interface for TTS providers.

    Implementations should convert text to audio, supporting
    streaming for low-latency voice applications.

    Example:
        class MyTTS(TTSInterface):
            async def synthesize_stream(self, text_stream, voice=None):
                async for sentence in text_stream:
                    audio = await tts_api(sentence)
                    yield AudioChunk(data=audio, sample_rate=24000)
    """

    @abstractmethod
    async def synthesize_stream(
        self,
        text_stream: AsyncIterator[str],
        voice: Optional[str] = None,
        speed: float = 1.0,
        **kwargs,
    ) -> AsyncIterator[AudioChunk]:
        """Synthesize audio from text stream.

        Args:
            text_stream: Async iterator of text chunks (usually sentences).
            voice: Voice identifier.
            speed: Speech speed multiplier (0.5 to 2.0).
            **kwargs: Additional provider-specific parameters.

        Yields:
            AudioChunk objects with synthesized audio.
        """
        pass

    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        speed: float = 1.0,
        **kwargs,
    ) -> bytes:
        """Synthesize complete audio from text.

        Default implementation collects stream results.

        Args:
            text: Text to synthesize.
            voice: Voice identifier.
            speed: Speech speed multiplier.
            **kwargs: Additional parameters.

        Returns:
            Complete audio data.
        """
        async def text_generator():
            yield text

        chunks = []
        async for chunk in self.synthesize_stream(
            text_generator(),
            voice=voice,
            speed=speed,
            **kwargs,
        ):
            chunks.append(chunk.data)

        return b"".join(chunks)
