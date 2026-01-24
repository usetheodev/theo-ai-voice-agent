"""VAD (Voice Activity Detection) interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional


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


class VADInterface(ABC):
    """Interface for VAD providers.

    Implementations should detect speech activity in audio,
    returning events for speech start/end.

    Example:
        class MyVAD(VADInterface):
            async def process(self, audio_chunk, sample_rate):
                prob = detect_speech(audio_chunk)
                return VADEvent(
                    is_speech=prob > 0.5,
                    confidence=prob,
                    state=SpeechState.SPEECH if prob > 0.5 else SpeechState.SILENCE,
                )
    """

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
