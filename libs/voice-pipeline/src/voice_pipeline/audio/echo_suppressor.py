"""Echo suppression for voice pipelines.

Prevents self-interruption loops where TTS output is picked up by the
microphone, causing the VAD to detect speech and trigger barge-in.

Two modes:
- DUCKING: Simple attenuation of mic during TTS output. Reliable but
  prevents full-duplex barge-in during playback.
- ENERGY_BASED: Compares mic input energy against expected echo energy.
  Allows barge-in when user speaks significantly louder than echo.
"""

import math
import time
from dataclasses import dataclass
from enum import Enum

import numpy as np


class EchoSuppressionMode(Enum):
    """Echo suppression operation mode."""

    NONE = "none"
    """No echo suppression (passthrough)."""

    DUCKING = "ducking"
    """Attenuate mic input during TTS output."""

    ENERGY_BASED = "energy_based"
    """Suppress based on energy comparison between input and output."""


@dataclass
class EchoSuppressionConfig:
    """Configuration for echo suppression.

    Attributes:
        mode: Suppression mode.
        ducking_attenuation_db: Attenuation applied during TTS (ducking mode).
        ducking_release_ms: Time after TTS stops before restoring mic level.
        energy_correlation_threshold: Unused currently, reserved for
            future cross-correlation AEC.
        barge_in_energy_threshold_db: Input must exceed expected echo by
            this many dB for VAD to process (energy mode).
        sample_rate: Audio sample rate in Hz.
    """

    mode: EchoSuppressionMode = EchoSuppressionMode.DUCKING
    ducking_attenuation_db: float = -30.0
    ducking_release_ms: float = 200.0
    energy_correlation_threshold: float = 0.7
    barge_in_energy_threshold_db: float = 6.0
    sample_rate: int = 16000


class EchoSuppressor:
    """Echo suppressor for voice pipeline.

    Feed TTS output via feed_output() and process mic input via
    process_input(). The should_process_vad() method indicates
    whether VAD should run on the current frame.

    Example:
        >>> suppressor = EchoSuppressor(EchoSuppressionConfig(
        ...     mode=EchoSuppressionMode.DUCKING
        ... ))
        >>> suppressor.notify_tts_start()
        >>> # During TTS playback:
        >>> processed = suppressor.process_input(mic_chunk)
        >>> if suppressor.should_process_vad():
        ...     vad_result = vad.process(processed)
        >>> suppressor.notify_tts_stop()
    """

    def __init__(self, config: EchoSuppressionConfig | None = None):
        self._config = config or EchoSuppressionConfig()
        self._mode = self._config.mode

        # TTS state
        self._tts_active = False
        self._tts_stop_time: float = 0.0

        # Energy tracking (for energy-based mode)
        self._output_rms = 0.0  # Smoothed RMS of TTS output
        self._decay_coeff = 0.95  # Exponential decay for output energy

        # Ducking
        self._ducking_gain = 10 ** (self._config.ducking_attenuation_db / 20.0)
        self._release_seconds = self._config.ducking_release_ms / 1000.0

        # Energy-based
        self._barge_in_threshold_linear = 10 ** (
            self._config.barge_in_energy_threshold_db / 20.0
        )

        # VAD gate
        self._allow_vad = True

    def feed_output(self, audio_bytes: bytes) -> None:
        """Feed TTS output audio for echo reference.

        Args:
            audio_bytes: PCM16 audio data being played back.
        """
        if self._mode == EchoSuppressionMode.NONE:
            return

        if not audio_bytes:
            return

        if self._mode == EchoSuppressionMode.ENERGY_BASED:
            samples = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            rms = float(np.sqrt(np.mean(samples ** 2)))
            # Exponential moving average
            self._output_rms = max(rms, self._output_rms * self._decay_coeff)

    def process_input(self, audio_bytes: bytes) -> bytes:
        """Process microphone input with echo suppression.

        Args:
            audio_bytes: PCM16 mic input data.

        Returns:
            Processed PCM16 audio data.
        """
        if self._mode == EchoSuppressionMode.NONE:
            return audio_bytes

        if not audio_bytes:
            return audio_bytes

        if self._mode == EchoSuppressionMode.DUCKING:
            return self._process_ducking(audio_bytes)
        elif self._mode == EchoSuppressionMode.ENERGY_BASED:
            return self._process_energy_based(audio_bytes)

        return audio_bytes

    def _process_ducking(self, audio_bytes: bytes) -> bytes:
        """Apply ducking: attenuate mic during TTS."""
        if not self._is_ducking_active():
            return audio_bytes

        samples = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)
        samples = samples * self._ducking_gain
        samples = np.clip(samples, -32768, 32767)
        return samples.astype(np.int16).tobytes()

    def _process_energy_based(self, audio_bytes: bytes) -> bytes:
        """Apply energy-based suppression."""
        if not self._tts_active:
            self._allow_vad = True
            return audio_bytes

        samples = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        input_rms = float(np.sqrt(np.mean(samples ** 2)))

        # Allow VAD only if input significantly exceeds expected echo
        if self._output_rms > 1e-10:
            ratio = input_rms / self._output_rms
            self._allow_vad = ratio >= self._barge_in_threshold_linear
        else:
            self._allow_vad = True

        return audio_bytes  # Pass through audio, only gate VAD

    def _is_ducking_active(self) -> bool:
        """Check if ducking should be applied."""
        if self._tts_active:
            return True
        # Check release period after TTS stop
        if self._tts_stop_time > 0:
            elapsed = time.monotonic() - self._tts_stop_time
            return elapsed < self._release_seconds
        return False

    def should_process_vad(self) -> bool:
        """Whether VAD should process the current frame.

        In ducking mode, always returns True (VAD sees attenuated signal).
        In energy mode, returns False when input doesn't exceed echo threshold.
        """
        if self._mode == EchoSuppressionMode.NONE:
            return True
        if self._mode == EchoSuppressionMode.DUCKING:
            return True
        return self._allow_vad

    def notify_tts_start(self) -> None:
        """Notify that TTS playback has started."""
        self._tts_active = True
        self._tts_stop_time = 0.0

    def notify_tts_stop(self) -> None:
        """Notify that TTS playback has stopped."""
        self._tts_active = False
        self._tts_stop_time = time.monotonic()

    def reset(self) -> None:
        """Reset suppressor state."""
        self._tts_active = False
        self._tts_stop_time = 0.0
        self._output_rms = 0.0
        self._allow_vad = True
