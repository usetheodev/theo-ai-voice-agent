"""
Comfort Noise Generator (CNG)

Generates low-amplitude white noise during processing silence,
preventing the "dead line" sensation when the AI is thinking.

The noise is generated at -60dBFS by default, which is barely
perceptible but enough to signal that the call is still active.

Implementation: pre-generates a pool of random frames at init
to avoid np.random calls in the real-time audio callback.
"""

import logging
import threading
from typing import Optional

import numpy as np

from config import AUDIO_CONFIG

logger = logging.getLogger("media-server.comfort-noise")

# Config defaults
COMFORT_NOISE_ENABLED = True
COMFORT_NOISE_DBFS = -60.0


class ComfortNoiseGenerator:
    """
    Generates comfort noise frames for playback during processing silence.

    Pre-generates a pool of random frames at init to avoid
    per-frame np.random overhead in the PJSIP callback thread.

    Thread-safe: can be started/stopped from any thread.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_duration_ms: int = 20,
        dbfs: float = COMFORT_NOISE_DBFS,
        pool_size: int = 50,
        enabled: bool = COMFORT_NOISE_ENABLED,
    ):
        self._sample_rate = sample_rate
        self._frame_duration_ms = frame_duration_ms
        self._dbfs = dbfs
        self._enabled = enabled
        self._active = False
        self._lock = threading.Lock()

        # Frame size in bytes (16-bit PCM)
        self._frame_samples = int(sample_rate * frame_duration_ms / 1000)
        self._frame_bytes = self._frame_samples * 2

        # Pre-generate pool of noise frames
        self._pool: list[bytes] = []
        self._pool_index = 0

        if enabled:
            self._generate_pool(pool_size)
            logger.info(
                f"ComfortNoiseGenerator: {pool_size} frames @ {dbfs}dBFS, "
                f"{sample_rate}Hz, {frame_duration_ms}ms"
            )

    def _generate_pool(self, pool_size: int):
        """Pre-generate pool of random noise frames."""
        # Convert dBFS to linear amplitude
        # dBFS = 20 * log10(amplitude / max_amplitude)
        # amplitude = max_amplitude * 10^(dBFS/20)
        max_amplitude = 32767  # 16-bit signed
        amplitude = max_amplitude * (10 ** (self._dbfs / 20))

        for _ in range(pool_size):
            # Generate white noise in [-amplitude, amplitude]
            noise = np.random.uniform(
                -amplitude, amplitude, self._frame_samples
            ).astype(np.int16)
            self._pool.append(noise.tobytes())

    def start(self):
        """Start generating comfort noise."""
        if not self._enabled:
            return
        with self._lock:
            self._active = True
            logger.debug("Comfort noise started")

    def stop(self):
        """Stop generating comfort noise."""
        with self._lock:
            self._active = False
            logger.debug("Comfort noise stopped")

    @property
    def is_active(self) -> bool:
        """Check if comfort noise is currently active."""
        return self._active and self._enabled

    def get_frame(self) -> Optional[bytes]:
        """Get next comfort noise frame.

        Returns None if not active. Thread-safe.
        Called from the PJSIP audio callback thread.
        """
        if not self._active or not self._enabled or not self._pool:
            return None

        with self._lock:
            if not self._active:
                return None
            frame = self._pool[self._pool_index]
            self._pool_index = (self._pool_index + 1) % len(self._pool)
            return frame
