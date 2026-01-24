"""TTS (Text-to-Speech) interface."""

from abc import abstractmethod
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional, Union

from voice_pipeline.runnable import RunnableConfig, VoiceRunnable


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


# Tipo de entrada para TTS
# - string direta
# - AsyncIterator de strings (para streaming de sentenças)
# - LLMChunk (extrai .text)
# - dict com 'text' ou 'content'
TTSInput = Union[str, AsyncIterator[str], Any]


class TTSInterface(VoiceRunnable[TTSInput, AudioChunk]):
    """Interface for TTS providers.

    Implementations should convert text to audio, supporting
    streaming for low-latency voice applications.

    This interface extends VoiceRunnable, allowing composition with
    the | operator:
        >>> chain = asr | llm | tts
        >>> result = await chain.ainvoke(audio_bytes)

    Example implementation:
        class MyTTS(TTSInterface):
            async def synthesize_stream(self, text_stream, voice=None):
                async for sentence in text_stream:
                    audio = await tts_api(sentence)
                    yield AudioChunk(data=audio, sample_rate=24000)

    Warmup:
        TTS models often have significant cold-start latency on the
        first synthesis call. Use warmup() to pre-load the model:

        >>> tts = MyTTS()
        >>> await tts.connect()
        >>> await tts.warmup()  # Pre-load model, eliminate cold start
        >>> audio = await tts.synthesize("Hello!")  # Fast!
    """

    name: str = "TTS"

    # Warmup configuration
    _warmup_text: str = "Hello."
    _is_warmed_up: bool = False

    async def warmup(self, text: Optional[str] = None) -> float:
        """Pre-load the TTS model to eliminate cold-start latency.

        This method synthesizes a short dummy text to ensure the model
        is fully loaded into memory. Call this after connect() and
        before the first real synthesis to avoid latency spikes.

        Args:
            text: Custom warmup text. Defaults to "Hello."

        Returns:
            Warmup time in milliseconds.

        Example:
            >>> tts = KokoroTTS(voice="af_bella")
            >>> await tts.connect()
            >>> warmup_ms = await tts.warmup()
            >>> print(f"Warmed up in {warmup_ms:.1f}ms")
            >>> # First real synthesis is now fast
            >>> audio = await tts.synthesize("How can I help?")
        """
        import time

        warmup_text = text or self._warmup_text

        start = time.perf_counter()

        # Synthesize dummy text (discard result)
        _ = await self.synthesize(warmup_text)

        elapsed_ms = (time.perf_counter() - start) * 1000
        self._is_warmed_up = True

        return elapsed_ms

    @property
    def is_warmed_up(self) -> bool:
        """Check if the TTS model has been warmed up.

        Returns:
            True if warmup() has been called successfully.
        """
        return self._is_warmed_up

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

    # ==================== VoiceRunnable Implementation ====================

    def _extract_text(self, input: TTSInput) -> str:
        """Extract text from various input formats.

        Args:
            input: Various input formats.

        Returns:
            Text string.
        """
        if isinstance(input, str):
            return input
        elif isinstance(input, dict):
            if "text" in input:
                return input["text"]
            elif "content" in input:
                return input["content"]
            else:
                return str(input)
        elif hasattr(input, "text"):
            # LLMChunk ou similar
            return input.text
        elif hasattr(input, "content"):
            return input.content
        else:
            return str(input)

    def _get_kwargs(self, config: Optional[RunnableConfig]) -> dict[str, Any]:
        """Extract TTS kwargs from config.

        Args:
            config: Optional configuration.

        Returns:
            Dictionary of kwargs.
        """
        kwargs: dict[str, Any] = {}

        if config and config.configurable:
            if "voice" in config.configurable:
                kwargs["voice"] = config.configurable["voice"]
            if "speed" in config.configurable:
                kwargs["speed"] = config.configurable["speed"]

        return kwargs

    async def ainvoke(
        self,
        input: TTSInput,
        config: Optional[RunnableConfig] = None,
    ) -> AudioChunk:
        """Execute TTS on input text.

        This is the VoiceRunnable interface method that enables
        composition with the | operator.

        Args:
            input: Text string, LLMChunk, or dict with text.
            config: Optional configuration with callbacks.

        Returns:
            AudioChunk with complete synthesized audio.
        """
        kwargs = self._get_kwargs(config)

        # Verifica se input é um async iterator (stream de strings)
        if hasattr(input, "__anext__"):
            # É um AsyncIterator[str]
            chunks = []
            async for chunk in self.synthesize_stream(input, **kwargs):
                chunks.append(chunk.data)
            return AudioChunk(
                data=b"".join(chunks),
                sample_rate=24000,
                channels=1,
                format="pcm16",
            )

        # Input é um valor único
        text = self._extract_text(input)
        audio_data = await self.synthesize(text, **kwargs)
        return AudioChunk(
            data=audio_data,
            sample_rate=24000,
            channels=1,
            format="pcm16",
        )

    async def astream(
        self,
        input: TTSInput,
        config: Optional[RunnableConfig] = None,
    ) -> AsyncIterator[AudioChunk]:
        """Stream TTS audio chunks.

        Args:
            input: Text string, LLMChunk, or dict with text.
            config: Optional configuration.

        Yields:
            AudioChunk objects with synthesized audio.
        """
        kwargs = self._get_kwargs(config)

        # Verifica se input é um async iterator (stream de strings)
        if hasattr(input, "__anext__"):
            # É um AsyncIterator[str]
            async for chunk in self.synthesize_stream(input, **kwargs):
                yield chunk
            return

        # Input é um valor único - cria generator
        text = self._extract_text(input)

        async def text_generator():
            yield text

        async for chunk in self.synthesize_stream(text_generator(), **kwargs):
            yield chunk
