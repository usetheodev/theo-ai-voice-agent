"""
SOXR Audio Resampler - High-quality sample rate conversion

SoX Resampler (SOXR) library for professional audio resampling.
Superior quality compared to audioop.ratecv.

Features:
- Very High Quality (VHQ) resampling
- Stream support (maintains state between chunks)
- No clicks at chunk boundaries
- Automatic state clearing after silence

Technical Details:
- Library: libsoxr (SoX Resampler)
- Quality: VHQ (Very High Quality) - default
- Latency: ~2-5ms additional latency
- Use cases:
  * Real-time streaming (8kHz → 16kHz for ASR)
  * High-quality audio processing
  * Podcast/music production

Pattern: Pipecat AI SOXRStreamAudioResampler (resamplers/soxr_stream_resampler.py)
Library: soxr (pip install soxr)
"""

import logging
import time
from typing import Optional
import numpy as np

# SOXR (optional dependency - graceful fallback)
try:
    import soxr
    SOXR_AVAILABLE = True
except ImportError:
    soxr = None
    SOXR_AVAILABLE = False


# Clear stream state after inactivity (prevents accumulated state growth)
CLEAR_STREAM_AFTER_SECS = 0.2


class SOXRStreamResampler:
    """
    SOXR Stream Audio Resampler

    High-quality audio resampling using SoX Resampler library.
    Maintains internal state for seamless chunk processing.

    Usage:
        resampler = SOXRStreamResampler(quality="VHQ")

        # Resample audio chunks
        output = await resampler.resample(audio, in_rate=8000, out_rate=16000)

    Quality Options:
        - "VHQ": Very High Quality (default, best for speech)
        - "HQ": High Quality
        - "MQ": Medium Quality
        - "LQ": Low Quality
        - "QQ": Quick Quality (fastest, lowest latency)

    Note: Resampler is stateful - do NOT change sample rates between calls.
    """

    def __init__(self, quality: str = "VHQ"):
        """
        Initialize SOXR resampler.

        Args:
            quality: Resampling quality ("VHQ", "HQ", "MQ", "LQ", "QQ")
                    "VHQ" = Very High Quality (recommended for speech)
                    "QQ" = Quick Quality (lowest latency for real-time)
        """
        self.logger = logging.getLogger("ai-voice-agent.audio.resamplers.soxr")

        self.quality = quality
        self._in_rate: Optional[float] = None
        self._out_rate: Optional[float] = None
        self._last_resample_time: float = 0
        self._soxr_stream: Optional[soxr.ResampleStream] = None

        if not SOXR_AVAILABLE:
            self.logger.warning(
                "SOXR not available (pip install soxr). "
                "Resampler will not work."
            )

    def _initialize(self, in_rate: float, out_rate: float):
        """
        Initialize SOXR stream with specific sample rates.

        Args:
            in_rate: Input sample rate (Hz)
            out_rate: Output sample rate (Hz)
        """
        if not SOXR_AVAILABLE:
            raise ImportError("soxr not available. Install: pip install soxr")

        self._in_rate = in_rate
        self._out_rate = out_rate
        self._last_resample_time = time.time()

        # Create SOXR stream (stateful resampler)
        self._soxr_stream = soxr.ResampleStream(
            in_rate=in_rate,
            out_rate=out_rate,
            num_channels=1,  # Mono audio
            quality=self.quality,
            dtype="int16"
        )

        self.logger.info(
            f"✅ SOXR resampler initialized: {in_rate} Hz → {out_rate} Hz "
            f"(quality={self.quality})"
        )

    def _maybe_clear_internal_state(self):
        """
        Clear resampler state after inactivity.

        Prevents accumulated state from growing unbounded.
        """
        current_time = time.time()
        time_since_last = current_time - self._last_resample_time

        # Clear state if inactive for > 200ms
        if time_since_last > CLEAR_STREAM_AFTER_SECS:
            if self._soxr_stream:
                self._soxr_stream.clear()
                self.logger.debug("SOXR stream state cleared (inactivity)")

        self._last_resample_time = current_time

    def _maybe_initialize_stream(self, in_rate: int, out_rate: int):
        """
        Initialize stream if needed, or clear state if inactive.

        Args:
            in_rate: Input sample rate (Hz)
            out_rate: Output sample rate (Hz)
        """
        if self._soxr_stream is None:
            self._initialize(in_rate, out_rate)
        else:
            self._maybe_clear_internal_state()

        # Validate sample rates haven't changed
        if self._in_rate != in_rate or self._out_rate != out_rate:
            raise ValueError(
                f"SOXRStreamResampler cannot change sample rates after initialization. "
                f"Expected {self._in_rate}→{self._out_rate}, got {in_rate}→{out_rate}. "
                f"Create a new resampler instance instead."
            )

    async def resample(self, audio: bytes, in_rate: int, out_rate: int) -> bytes:
        """
        Resample audio data to different sample rate.

        Args:
            audio: Input audio data as raw bytes (16-bit signed, mono)
            in_rate: Original sample rate (Hz)
            out_rate: Target sample rate (Hz)

        Returns:
            Resampled audio data as raw bytes (16-bit signed, mono)
        """
        # No-op if sample rates are the same
        if in_rate == out_rate:
            return audio

        # Empty audio check
        if len(audio) == 0:
            return b""

        if not SOXR_AVAILABLE:
            self.logger.error("SOXR not available - cannot resample")
            return audio

        # Initialize or validate stream
        self._maybe_initialize_stream(in_rate, out_rate)

        # Convert bytes to numpy array
        audio_data = np.frombuffer(audio, dtype=np.int16)

        # Resample using SOXR stream
        resampled_audio = self._soxr_stream.resample_chunk(audio_data)

        # Convert back to bytes
        result = resampled_audio.astype(np.int16).tobytes()

        return result

    def reset(self):
        """Reset resampler state (clear accumulated history)"""
        if self._soxr_stream:
            self._soxr_stream.clear()
            self.logger.debug("SOXR stream reset")

    def get_stats(self) -> dict:
        """
        Get resampler statistics.

        Returns:
            Dict with resampler configuration
        """
        return {
            'available': SOXR_AVAILABLE,
            'quality': self.quality,
            'in_rate': self._in_rate,
            'out_rate': self._out_rate,
            'initialized': self._soxr_stream is not None,
        }


# Test function
async def test_soxr_resampler():
    """Test SOXR resampler with synthetic audio"""
    import numpy as np

    print("\n=== SOXR Resampler Test ===\n")

    if not SOXR_AVAILABLE:
        print("❌ SOXR not available (pip install soxr)")
        return

    # Create resampler
    resampler = SOXRStreamResampler(quality="VHQ")

    # Generate test audio (1 second @ 8kHz)
    in_rate = 8000
    out_rate = 16000
    duration = 1.0

    num_samples_in = int(in_rate * duration)
    t_in = np.linspace(0, duration, num_samples_in)

    # Generate 440 Hz tone
    audio_in = (np.sin(2 * np.pi * 440 * t_in) * 10000).astype(np.int16)

    print(f"Input: {num_samples_in} samples @ {in_rate} Hz")

    # Resample
    audio_out = await resampler.resample(audio_in.tobytes(), in_rate, out_rate)

    audio_out_array = np.frombuffer(audio_out, dtype=np.int16)
    num_samples_out = len(audio_out_array)

    print(f"Output: {num_samples_out} samples @ {out_rate} Hz")
    print(f"Expected: {int(num_samples_in * out_rate / in_rate)} samples")

    # Verify output length
    expected_samples = int(num_samples_in * out_rate / in_rate)
    tolerance = 10  # Allow small variance due to filter delay

    if abs(num_samples_out - expected_samples) <= tolerance:
        print("✅ SOXR resampler working correctly!")
    else:
        print(f"⚠️  Output length mismatch (got {num_samples_out}, expected ~{expected_samples})")

    # Stats
    print(f"\nStats: {resampler.get_stats()}")


if __name__ == '__main__':
    import asyncio
    asyncio.run(test_soxr_resampler())
