"""Energy-based VAD Provider.

Simple voice activity detection based on audio energy.
No external dependencies required.
"""

import logging
import math
import struct
from typing import Optional

from ..base import VADProvider, VADResult

logger = logging.getLogger(__name__)


class EnergyVAD(VADProvider):
    """Energy-based Voice Activity Detection.

    Simple VAD that detects speech based on audio energy levels.
    No ML model required - works with any audio input.

    Usage:
        provider = EnergyVAD(
            threshold=0.02,  # Energy threshold
            min_speech_duration_ms=200,
        )

        result = await provider.process(audio_chunk)
    """

    def __init__(
        self,
        api_base: str = "",
        threshold: float = 0.02,  # RMS energy threshold
        min_speech_duration_ms: int = 200,
        min_silence_duration_ms: int = 300,
        smoothing_window: int = 5,  # Number of frames to smooth
        **kwargs,
    ):
        """Initialize Energy VAD provider.

        Args:
            api_base: Not used (always local).
            threshold: RMS energy threshold (0-1).
            min_speech_duration_ms: Minimum speech duration.
            min_silence_duration_ms: Minimum silence to end speech.
            smoothing_window: Number of frames for smoothing.
        """
        super().__init__(
            api_base=api_base,
            threshold=threshold,
            min_speech_duration_ms=min_speech_duration_ms,
            min_silence_duration_ms=min_silence_duration_ms,
            **kwargs,
        )

        self.smoothing_window = smoothing_window

        # State
        self._energy_history: list[float] = []
        self._speech_start: Optional[float] = None
        self._last_speech_time: float = 0.0
        self._sample_count: int = 0
        self._is_speaking: bool = False

    @property
    def name(self) -> str:
        return "energy"

    def _calculate_rms(self, audio_chunk: bytes) -> float:
        """Calculate RMS (Root Mean Square) energy of audio.

        Args:
            audio_chunk: PCM16 audio bytes.

        Returns:
            RMS energy normalized to 0-1.
        """
        if len(audio_chunk) < 2:
            return 0.0

        # Unpack PCM16 samples
        num_samples = len(audio_chunk) // 2
        samples = struct.unpack(f"<{num_samples}h", audio_chunk)

        if not samples:
            return 0.0

        # Calculate RMS
        sum_squares = sum(s * s for s in samples)
        rms = math.sqrt(sum_squares / num_samples)

        # Normalize to 0-1 (max PCM16 value is 32767)
        return rms / 32768.0

    def _smooth_energy(self, energy: float) -> float:
        """Apply smoothing to energy values.

        Args:
            energy: Current frame energy.

        Returns:
            Smoothed energy value.
        """
        self._energy_history.append(energy)

        # Keep only recent history
        if len(self._energy_history) > self.smoothing_window:
            self._energy_history.pop(0)

        # Return average
        return sum(self._energy_history) / len(self._energy_history)

    async def process(
        self,
        audio_chunk: bytes,
        sample_rate: int = 16000,
    ) -> VADResult:
        """Process audio chunk and detect voice activity.

        Args:
            audio_chunk: Raw PCM16 audio bytes.
            sample_rate: Audio sample rate.

        Returns:
            VAD result with speech detection.
        """
        # Calculate energy
        raw_energy = self._calculate_rms(audio_chunk)
        smoothed_energy = self._smooth_energy(raw_energy)

        # Determine if speech
        is_above_threshold = smoothed_energy >= self.threshold

        # Track timing
        num_samples = len(audio_chunk) // 2
        chunk_duration_ms = (num_samples / sample_rate) * 1000
        current_time = self._sample_count / sample_rate
        self._sample_count += num_samples

        # State machine for speech detection
        if is_above_threshold:
            if not self._is_speaking:
                # Potential start of speech
                if self._speech_start is None:
                    self._speech_start = current_time

                # Check if we've had enough continuous speech
                speech_duration_ms = (current_time - self._speech_start) * 1000
                if speech_duration_ms >= self.min_speech_duration_ms:
                    self._is_speaking = True

            self._last_speech_time = current_time

        else:
            if self._is_speaking:
                # Check if silence is long enough to end speech
                silence_duration_ms = (current_time - self._last_speech_time) * 1000
                if silence_duration_ms >= self.min_silence_duration_ms:
                    self._is_speaking = False
                    self._speech_start = None

            elif self._speech_start is not None:
                # Check if initial speech attempt timed out
                silence_duration_ms = (current_time - self._last_speech_time) * 1000
                if silence_duration_ms >= self.min_silence_duration_ms:
                    self._speech_start = None

        return VADResult(
            is_speech=self._is_speaking or (
                self._speech_start is not None and is_above_threshold
            ),
            confidence=min(1.0, smoothed_energy / self.threshold) if is_above_threshold else 0.0,
            start_time=self._speech_start,
            end_time=current_time if self._is_speaking else None,
        )

    def reset(self) -> None:
        """Reset VAD state for new utterance."""
        self._energy_history.clear()
        self._speech_start = None
        self._last_speech_time = 0.0
        self._sample_count = 0
        self._is_speaking = False
