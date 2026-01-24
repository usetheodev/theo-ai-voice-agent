"""VAD (Voice Activity Detection) interface."""

from abc import abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import AsyncIterator, Optional, Union

from voice_pipeline.runnable import RunnableConfig, VoiceRunnable


class SpeechState(Enum):
    """Speech activity state."""

    SILENCE = "silence"
    """No speech detected."""

    SPEECH = "speech"
    """Speech detected."""

    UNCERTAIN = "uncertain"
    """Uncertain (transitioning)."""


@dataclass
class VADEvent:
    """Event from VAD processing."""

    is_speech: bool
    """Whether speech was detected."""

    confidence: float = 1.0
    """Confidence score (0.0 to 1.0)."""

    state: SpeechState = SpeechState.SILENCE
    """Current speech state."""

    speech_start_ms: Optional[float] = None
    """Speech start time in milliseconds (if detected)."""

    speech_end_ms: Optional[float] = None
    """Speech end time in milliseconds (if detected)."""


# Tipo de entrada para VAD
# - bytes (chunk de áudio)
# - tuple (audio_bytes, sample_rate)
# - dict com 'audio' ou 'data' e opcionalmente 'sample_rate'
VADInput = Union[bytes, tuple[bytes, int], dict]


class VADInterface(VoiceRunnable[VADInput, VADEvent]):
    """Interface for VAD providers.

    Implementations should detect speech activity in audio,
    returning events for speech start/end.

    This interface extends VoiceRunnable, allowing composition with
    the | operator for preprocessing pipelines.

    Example implementation:
        class MyVAD(VADInterface):
            async def process(self, audio_chunk, sample_rate):
                prob = detect_speech(audio_chunk)
                return VADEvent(
                    is_speech=prob > 0.5,
                    confidence=prob,
                    state=SpeechState.SPEECH if prob > 0.5 else SpeechState.SILENCE,
                )
    """

    name: str = "VAD"

    @abstractmethod
    async def process(
        self,
        audio_chunk: bytes,
        sample_rate: int,
    ) -> VADEvent:
        """Process audio chunk for voice activity.

        Args:
            audio_chunk: Audio data (PCM16, mono).
            sample_rate: Sample rate in Hz.

        Returns:
            VADEvent with speech detection result.
        """
        pass

    def reset(self) -> None:
        """Reset VAD state.

        Called when conversation turn ends or barge-in occurs.
        Override if your implementation maintains state.
        """
        pass

    @property
    def frame_size_ms(self) -> int:
        """Preferred frame size in milliseconds.

        Override to specify optimal chunk size for this VAD.
        Default is 30ms which works for most implementations.
        """
        return 30

    # ==================== VoiceRunnable Implementation ====================

    def _extract_input(
        self, input: VADInput, config: Optional[RunnableConfig]
    ) -> tuple[bytes, int]:
        """Extract audio bytes and sample rate from various input formats.

        Args:
            input: Various input formats.
            config: Optional configuration.

        Returns:
            Tuple of (audio_bytes, sample_rate).
        """
        # Default sample rate
        default_sample_rate = 16000

        # Tenta extrair sample_rate da config
        if config and config.configurable:
            default_sample_rate = config.configurable.get(
                "sample_rate", default_sample_rate
            )

        if isinstance(input, bytes):
            return input, default_sample_rate
        elif isinstance(input, tuple) and len(input) == 2:
            return input[0], input[1]
        elif isinstance(input, dict):
            audio = input.get("audio") or input.get("data") or input.get("chunk")
            if audio is None:
                raise ValueError("Dict input must have 'audio', 'data', or 'chunk' key")
            sample_rate = input.get("sample_rate", default_sample_rate)
            return audio, sample_rate
        else:
            raise TypeError(f"Unsupported VAD input type: {type(input)}")

    async def ainvoke(
        self,
        input: VADInput,
        config: Optional[RunnableConfig] = None,
    ) -> VADEvent:
        """Execute VAD on input audio chunk.

        This is the VoiceRunnable interface method that enables
        composition with the | operator.

        Args:
            input: Audio bytes, tuple (bytes, sample_rate), or dict.
            config: Optional configuration with callbacks.

        Returns:
            VADEvent with speech detection result.
        """
        audio_chunk, sample_rate = self._extract_input(input, config)
        return await self.process(audio_chunk, sample_rate)

    async def astream(
        self,
        input: VADInput,
        config: Optional[RunnableConfig] = None,
    ) -> AsyncIterator[VADEvent]:
        """Process single chunk and yield result.

        For continuous VAD, use process_stream() if available.

        Args:
            input: Audio chunk.
            config: Optional configuration.

        Yields:
            VADEvent from processing.
        """
        yield await self.ainvoke(input, config)

    async def process_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        sample_rate: int = 16000,
    ) -> AsyncIterator[VADEvent]:
        """Process a stream of audio chunks.

        Useful for continuous VAD processing.

        Args:
            audio_stream: Async iterator of audio chunks.
            sample_rate: Sample rate of the audio.

        Yields:
            VADEvent for each processed chunk.
        """
        async for chunk in audio_stream:
            yield await self.process(chunk, sample_rate)
