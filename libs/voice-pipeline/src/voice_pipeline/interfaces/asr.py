"""ASR (Automatic Speech Recognition) interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator, Optional


@dataclass
class TranscriptionResult:
    """Result from ASR transcription."""

    text: str
    """Transcribed text."""

    is_final: bool
    """Whether this is a final result or partial."""

    confidence: float = 1.0
    """Confidence score (0.0 to 1.0)."""

    language: Optional[str] = None
    """Detected language code."""

    start_time: Optional[float] = None
    """Start time in seconds (if available)."""

    end_time: Optional[float] = None
    """End time in seconds (if available)."""


class ASRInterface(ABC):
    """Interface for ASR providers.

    Implementations should convert audio to text, supporting both
    batch and streaming modes.

    Example:
        class MyASR(ASRInterface):
            async def transcribe_stream(self, audio_stream, language=None):
                async for chunk in audio_stream:
                    result = process_audio(chunk)
                    yield TranscriptionResult(text=result, is_final=True)
    """

    @abstractmethod
    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        language: Optional[str] = None,
    ) -> AsyncIterator[TranscriptionResult]:
        """Transcribe audio stream.

        Args:
            audio_stream: Async iterator of audio chunks (PCM16, mono).
            language: Optional language code (e.g., "en", "pt-BR").

        Yields:
            TranscriptionResult objects (partial and final).
        """
        pass

    async def transcribe(
        self,
        audio_data: bytes,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe complete audio data.

        Default implementation collects stream results.

        Args:
            audio_data: Complete audio data (PCM16, mono).
            language: Optional language code.

        Returns:
            Final transcription result.
        """
        async def audio_generator():
            yield audio_data

        final_result = TranscriptionResult(text="", is_final=True)

        async for result in self.transcribe_stream(audio_generator(), language):
            if result.is_final:
                final_result = result

        return final_result
