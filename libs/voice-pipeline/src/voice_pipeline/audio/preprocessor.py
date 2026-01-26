"""Audio preprocessor with AGC (Automatic Gain Control) and Noise Gate.

Normalizes microphone input levels to compensate for differences between
devices (e.g., laptop mic at -50dB vs headset at -20dB).

AGC uses an envelope follower with fast attack / slow release to avoid
"pumping" artifacts. The noise gate zeroes samples below a threshold,
with a hold timer to prevent chattering.
"""

import math
from dataclasses import dataclass

import numpy as np


@dataclass
class AudioPreprocessorConfig:
    """Configuration for the audio preprocessor.

    Attributes:
        enable_agc: Enable Automatic Gain Control.
        agc_target_db: Target output level in dBFS.
        agc_max_gain_db: Maximum gain that can be applied.
        agc_attack_time_s: Attack time (fast ramp up). Default: 10ms.
        agc_release_time_s: Release time (slow ramp down). Default: 300ms.
        enable_noise_gate: Enable noise gate.
        noise_gate_threshold_db: Gate opens above this level.
        noise_gate_hold_time_ms: Hold gate open for this duration after
            signal drops below threshold (prevents chattering).
        sample_rate: Audio sample rate in Hz.
    """

    enable_agc: bool = True
    agc_target_db: float = -20.0
    agc_max_gain_db: float = 30.0
    agc_attack_time_s: float = 0.01
    agc_release_time_s: float = 0.3
    enable_noise_gate: bool = True
    noise_gate_threshold_db: float = -50.0
    noise_gate_hold_time_ms: float = 100.0
    sample_rate: int = 16000


class AudioPreprocessor:
    """Audio preprocessor with AGC and noise gate.

    Processes raw PCM16 audio bytes and returns preprocessed bytes.
    Maintains internal state (envelope, hold timer) across calls
    for smooth, artifact-free processing.

    Example:
        >>> config = AudioPreprocessorConfig(agc_target_db=-20.0)
        >>> preprocessor = AudioPreprocessor(config)
        >>> processed = preprocessor.process(raw_audio_bytes)
    """

    def __init__(self, config: AudioPreprocessorConfig | None = None):
        self._config = config or AudioPreprocessorConfig()

        # AGC state: envelope follower
        self._envelope = 0.0  # Current signal envelope (linear)
        self._current_gain = 1.0  # Current applied gain (linear)

        # Pre-compute AGC constants
        sr = self._config.sample_rate
        self._attack_coeff = 1.0 - math.exp(-1.0 / (self._config.agc_attack_time_s * sr))
        self._release_coeff = 1.0 - math.exp(-1.0 / (self._config.agc_release_time_s * sr))
        self._target_linear = 10 ** (self._config.agc_target_db / 20.0)
        self._max_gain_linear = 10 ** (self._config.agc_max_gain_db / 20.0)

        # Noise gate state
        self._gate_threshold_linear = 10 ** (self._config.noise_gate_threshold_db / 20.0)
        self._gate_open = False
        self._gate_hold_samples = int(
            self._config.noise_gate_hold_time_ms / 1000.0 * sr
        )
        self._gate_hold_counter = 0

    def process(self, audio_bytes: bytes) -> bytes:
        """Process audio through AGC and noise gate.

        Args:
            audio_bytes: PCM16 audio data (little-endian, mono).

        Returns:
            Processed PCM16 audio data.
        """
        if not audio_bytes:
            return audio_bytes

        samples = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

        if self._config.enable_noise_gate:
            samples = self._apply_noise_gate(samples)

        if self._config.enable_agc:
            samples = self._apply_agc(samples)

        # Convert back to PCM16
        clipped = np.clip(samples, -1.0, 1.0)
        return (clipped * 32767).astype(np.int16).tobytes()

    def _apply_agc(self, samples: np.ndarray) -> np.ndarray:
        """Apply Automatic Gain Control using envelope follower.

        Uses exponential envelope follower with different attack/release
        coefficients to track the signal level smoothly.

        Args:
            samples: Float32 audio samples in [-1.0, 1.0].

        Returns:
            Gain-adjusted samples.
        """
        output = np.empty_like(samples)
        envelope = self._envelope
        current_gain = self._current_gain

        attack = self._attack_coeff
        release = self._release_coeff
        target = self._target_linear
        max_gain = self._max_gain_linear

        for i in range(len(samples)):
            abs_sample = abs(samples[i])

            # Envelope follower
            if abs_sample > envelope:
                envelope += attack * (abs_sample - envelope)
            else:
                envelope += release * (abs_sample - envelope)

            # Compute desired gain
            if envelope > 1e-10:
                desired_gain = target / envelope
                desired_gain = min(desired_gain, max_gain)
            else:
                desired_gain = current_gain  # Hold gain during silence

            # Smooth gain transition
            if desired_gain > current_gain:
                current_gain += attack * (desired_gain - current_gain)
            else:
                current_gain += release * (desired_gain - current_gain)

            output[i] = samples[i] * current_gain

        self._envelope = envelope
        self._current_gain = current_gain
        return output

    def _apply_noise_gate(self, samples: np.ndarray) -> np.ndarray:
        """Apply noise gate with hold timer.

        Zeroes samples below the threshold. The hold timer keeps the
        gate open briefly after the signal drops, preventing chattering
        on signal edges.

        Args:
            samples: Float32 audio samples in [-1.0, 1.0].

        Returns:
            Gated samples.
        """
        output = np.empty_like(samples)
        gate_open = self._gate_open
        hold_counter = self._gate_hold_counter
        threshold = self._gate_threshold_linear
        hold_samples = self._gate_hold_samples

        for i in range(len(samples)):
            abs_sample = abs(samples[i])

            if abs_sample >= threshold:
                gate_open = True
                hold_counter = hold_samples
            elif hold_counter > 0:
                hold_counter -= 1
            else:
                gate_open = False

            output[i] = samples[i] if gate_open else 0.0

        self._gate_open = gate_open
        self._gate_hold_counter = hold_counter
        return output

    def reset(self) -> None:
        """Reset preprocessor state."""
        self._envelope = 0.0
        self._current_gain = 1.0
        self._gate_open = False
        self._gate_hold_counter = 0

    @property
    def current_gain_db(self) -> float:
        """Current applied gain in dB."""
        if self._current_gain <= 0:
            return float('-inf')
        return 20 * math.log10(self._current_gain)

    @property
    def current_level_db(self) -> float:
        """Current signal level (envelope) in dBFS."""
        if self._envelope <= 0:
            return float('-inf')
        return 20 * math.log10(self._envelope)
