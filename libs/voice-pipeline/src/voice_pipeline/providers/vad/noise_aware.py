"""Noise-aware VAD wrapper with automatic noise floor calibration.

Wraps any VADInterface and automatically adjusts the detection threshold
based on ambient noise level. Uses decorator pattern — the wrapped VAD
handles actual speech detection, while this wrapper manages calibration
and threshold adjustment.

During the first few seconds (calibration period), the wrapper collects
RMS statistics and estimates the noise floor. The threshold is then
adjusted to ensure reliable detection above the noise.
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from voice_pipeline.interfaces.vad import VADEvent, VADInterface

logger = logging.getLogger(__name__)


@dataclass
class NoiseFloorConfig:
    """Configuration for noise-aware VAD wrapper.

    Attributes:
        calibration_duration_s: Duration of initial calibration in seconds.
        min_threshold: Minimum allowed threshold.
        max_threshold: Maximum allowed threshold.
        base_threshold: Default threshold before calibration.
        noise_multiplier: How many times above noise floor for threshold.
        auto_calibrate: If True, calibrate automatically on first frames.
    """

    calibration_duration_s: float = 2.5
    min_threshold: float = 0.3
    max_threshold: float = 0.85
    base_threshold: float = 0.5
    noise_multiplier: float = 3.0
    auto_calibrate: bool = True


class NoiseAwareVAD(VADInterface):
    """Noise-aware VAD wrapper with automatic calibration.

    Wraps an existing VAD provider and adjusts its threshold based
    on ambient noise floor estimation. Uses decorator pattern.

    Example:
        >>> inner_vad = SileroVADProvider()
        >>> vad = NoiseAwareVAD(inner_vad, NoiseFloorConfig(
        ...     calibration_duration_s=2.0,
        ...     noise_multiplier=3.0,
        ... ))
        >>> # First 2 seconds calibrate automatically
        >>> event = await vad.process(audio_chunk, 16000)
    """

    name: str = "NoiseAwareVAD"

    def __init__(
        self,
        inner_vad: VADInterface,
        config: NoiseFloorConfig | None = None,
    ):
        self._inner = inner_vad
        self._config = config or NoiseFloorConfig()

        # Calibration state
        self._calibration_rms_values: list[float] = []
        self._calibration_samples_collected: int = 0
        self._is_calibrated = False

        # Computed values
        self._noise_floor_rms: float = 0.0
        self._adjusted_threshold: float = self._config.base_threshold

    async def process(
        self,
        audio_chunk: bytes,
        sample_rate: int,
    ) -> VADEvent:
        """Process audio chunk with noise-aware threshold.

        During calibration period, collects noise statistics.
        After calibration, delegates to inner VAD with adjusted threshold.

        Args:
            audio_chunk: PCM16 audio data.
            sample_rate: Sample rate in Hz.

        Returns:
            VADEvent from inner VAD.
        """
        # Auto-calibration: collect noise during initial frames
        if self._config.auto_calibrate and not self._is_calibrated:
            calibration_samples_needed = int(
                self._config.calibration_duration_s * sample_rate
            )
            chunk_samples = len(audio_chunk) // 2  # PCM16 = 2 bytes/sample

            # Compute RMS of this chunk
            if len(audio_chunk) >= 2:
                samples = np.frombuffer(audio_chunk, dtype=np.int16).astype(np.float32) / 32768.0
                rms = float(np.sqrt(np.mean(samples ** 2)))
                self._calibration_rms_values.append(rms)

            self._calibration_samples_collected += chunk_samples

            if self._calibration_samples_collected >= calibration_samples_needed:
                self._finalize_calibration()

        # Delegate to inner VAD
        return await self._inner.process(audio_chunk, sample_rate)

    def _finalize_calibration(self) -> None:
        """Compute noise floor and adjust threshold."""
        if not self._calibration_rms_values:
            self._is_calibrated = True
            return

        values = self._calibration_rms_values
        mean_rms = sum(values) / len(values)
        if len(values) > 1:
            variance = sum((v - mean_rms) ** 2 for v in values) / len(values)
            stddev = variance ** 0.5
        else:
            stddev = 0.0

        self._noise_floor_rms = mean_rms + stddev

        # Compute adjusted threshold
        new_threshold = (
            self._config.base_threshold
            + self._noise_floor_rms * self._config.noise_multiplier
        )
        self._adjusted_threshold = max(
            self._config.min_threshold,
            min(self._config.max_threshold, new_threshold),
        )

        # Try to set threshold on inner VAD if it supports it
        if hasattr(self._inner, 'set_threshold'):
            self._inner.set_threshold(self._adjusted_threshold)

        self._is_calibrated = True
        logger.info(
            f"Noise calibration complete: floor_rms={self._noise_floor_rms:.4f}, "
            f"adjusted_threshold={self._adjusted_threshold:.3f}"
        )

    async def calibrate(
        self,
        audio_chunks: list[bytes],
        sample_rate: int,
    ) -> float:
        """Manually calibrate noise floor from audio chunks.

        Args:
            audio_chunks: List of PCM16 audio chunks (ambient noise).
            sample_rate: Sample rate in Hz.

        Returns:
            Adjusted threshold value.
        """
        self._calibration_rms_values.clear()
        self._calibration_samples_collected = 0

        for chunk in audio_chunks:
            if len(chunk) >= 2:
                samples = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
                rms = float(np.sqrt(np.mean(samples ** 2)))
                self._calibration_rms_values.append(rms)
                self._calibration_samples_collected += len(chunk) // 2

        self._finalize_calibration()
        return self._adjusted_threshold

    def reset_calibration(self) -> None:
        """Reset calibration state for re-calibration."""
        self._calibration_rms_values.clear()
        self._calibration_samples_collected = 0
        self._is_calibrated = False
        self._noise_floor_rms = 0.0
        self._adjusted_threshold = self._config.base_threshold

    def reset(self) -> None:
        """Reset inner VAD state (does not reset calibration)."""
        self._inner.reset()

    @property
    def noise_floor_rms(self) -> float:
        """Estimated noise floor RMS level."""
        return self._noise_floor_rms

    @property
    def adjusted_threshold(self) -> float:
        """Current adjusted threshold."""
        return self._adjusted_threshold

    @property
    def is_calibrated(self) -> bool:
        """Whether calibration is complete."""
        return self._is_calibrated

    @property
    def frame_size_ms(self) -> int:
        """Delegate to inner VAD."""
        return self._inner.frame_size_ms
