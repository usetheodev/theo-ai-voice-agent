"""ASR (Automatic Speech Recognition) interface."""

from abc import abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator, Optional, Union

from voice_pipeline.runnable import RunnableConfig, VoiceRunnable


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


# Tipo de entrada para ASR: bytes ou AsyncIterator de bytes
ASRInput = Union[bytes, AsyncIterator[bytes]]


class ASRInterface(VoiceRunnable[ASRInput, TranscriptionResult]):
    """Interface for ASR providers.

    Implementations should convert audio to text, supporting both
    batch and streaming modes.

    This interface extends VoiceRunnable, allowing composition with
    the | operator:
        >>> chain = asr | llm | tts
        >>> result = await chain.ainvoke(audio_bytes)

    Example implementation:
        class MyASR(ASRInterface):
            async def transcribe_stream(self, audio_stream, language=None):
                async for chunk in audio_stream:
                    result = process_audio(chunk)
                    yield TranscriptionResult(text=result, is_final=True)
    """

    name: str = "ASR"

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

    # ==================== VoiceRunnable Implementation ====================

    async def ainvoke(
        self,
        input: ASRInput,
        config: Optional[RunnableConfig] = None,
    ) -> TranscriptionResult:
        """Execute ASR on input audio.

        This is the VoiceRunnable interface method that enables
        composition with the | operator.

        Args:
            input: Audio bytes or async iterator of audio chunks.
            config: Optional configuration with callbacks.

        Returns:
            Final transcription result.
        """
        # Extrai language da config se disponível
        language = None
        if config and config.configurable:
            language = config.configurable.get("language")

        if isinstance(input, bytes):
            return await self.transcribe(input, language)
        else:
            # input é AsyncIterator[bytes]
            final_result = TranscriptionResult(text="", is_final=True)
            async for result in self.transcribe_stream(input, language):
                if result.is_final:
                    final_result = result
            return final_result

    async def astream(
        self,
        input: ASRInput,
        config: Optional[RunnableConfig] = None,
    ) -> AsyncIterator[TranscriptionResult]:
        """Stream transcription results.

        Args:
            input: Audio bytes or async iterator of audio chunks.
            config: Optional configuration.

        Yields:
            TranscriptionResult objects (partial and final).
        """
        language = None
        if config and config.configurable:
            language = config.configurable.get("language")

        if isinstance(input, bytes):
            async def audio_generator():
                yield input
            audio_stream = audio_generator()
        else:
            audio_stream = input

        async for result in self.transcribe_stream(audio_stream, language):
            yield result
