"""
RNNoise Noise Suppression Filter

Recurrent Neural Network for audio noise reduction.
Removes background noise (keyboard, AC, traffic, etc) while preserving speech.

Features:
- RNN-based noise suppression (Xiph.org RNNoise)
- Automatic resampling (input sample_rate <-> 48kHz)
- Real-time processing with buffering
- Toggle enable/disable at runtime

Technical Details:
- RNNoise requires 48kHz (480 samples = 10ms frames)
- Returns speech probability per frame (0.0-1.0)
- Output: denoised audio in original sample rate

Pattern: Pipecat AI RNNoiseFilter (filters/rnnoise_filter.py)
Library: pyrnnoise (pip install pyrnnoise)
"""

import logging
import numpy as np
from typing import Optional

# RNNoise (optional dependency - graceful fallback)
try:
    from pyrnnoise import RNNoise
    RNNOISE_AVAILABLE = True
except ImportError:
    RNNoise = None
    RNNOISE_AVAILABLE = False


class RNNoiseFilter:
    """
    RNNoise Noise Suppression Filter

    Removes background noise using Xiph.org RNNoise (RNN-based).

    Usage:
        filter = RNNoiseFilter()
        await filter.start(sample_rate=8000)

        # Process audio frames
        clean_audio = await filter.filter(noisy_audio)

        # Toggle filtering
        filter.set_enabled(False)  # Bypass filter

        # Cleanup
        await filter.stop()

    Note: RNNoise always operates at 48kHz internally.
          Automatic resampling is applied if input != 48kHz.
    """

    def __init__(self, resampler_quality: str = "QQ"):
        """
        Initialize RNNoise filter.

        Args:
            resampler_quality: SOXR quality ("VHQ", "HQ", "MQ", "LQ", "QQ")
                              "QQ" = Quick (lowest latency, recommended for real-time)
        """
        self.logger = logging.getLogger("ai-voice-agent.audio.filters.rnnoise")

        self._filtering = True
        self._sample_rate = 0
        self._rnnoise = None
        self._rnnoise_ready = False
        self._resampler_in = None
        self._resampler_out = None
        self._resampler_quality = resampler_quality

        # Statistics
        self.total_frames = 0
        self.speech_frames = 0
        self.noise_frames = 0
        self.avg_speech_prob = 0.0

        if not RNNOISE_AVAILABLE:
            self.logger.warning(
                "RNNoise not available (pip install pyrnnoise). "
                "Filter will bypass audio without processing."
            )

    async def start(self, sample_rate: int):
        """
        Initialize filter with transport's sample rate.

        Args:
            sample_rate: Input audio sample rate (Hz)
        """
        self._sample_rate = sample_rate

        if not RNNOISE_AVAILABLE:
            self.logger.warning("RNNoise not available - filter disabled")
            self._rnnoise_ready = False
            return

        try:
            # RNNoise always requires 48kHz
            self._rnnoise = RNNoise(sample_rate=48000)
            self._rnnoise_ready = True

            self.logger.info(f"✅ RNNoise initialized (48kHz)")

        except Exception as e:
            self.logger.error(f"Failed to initialize RNNoise: {e}")
            self._rnnoise_ready = False
            return

        # Setup resampling if needed (input_rate <-> 48kHz)
        if self._sample_rate != 48000:
            self.logger.info(
                f"RNNoise filter enabling resampling: {self._sample_rate} Hz <-> 48000 Hz"
            )
            try:
                # Import SOXR resampler (will be implemented in task 3)
                from ..resamplers import SOXRStreamResampler

                self._resampler_in = SOXRStreamResampler(quality=self._resampler_quality)
                self._resampler_out = SOXRStreamResampler(quality=self._resampler_quality)

                self.logger.info(f"✅ SOXR resampler ready (quality={self._resampler_quality})")

            except ImportError as e:
                self.logger.error(
                    f"Could not import SOXRStreamResampler: {e}. "
                    f"RNNoise requires 48kHz but input is {self._sample_rate} Hz. "
                    f"Install soxr: pip install soxr"
                )
                self._rnnoise_ready = False

    async def stop(self):
        """Clean up RNNoise engine when stopping."""
        self._rnnoise = None
        self._rnnoise_ready = False
        self._resampler_in = None
        self._resampler_out = None

        self.logger.info("RNNoise filter stopped")

    def set_enabled(self, enabled: bool):
        """
        Enable or disable filtering at runtime.

        Args:
            enabled: True to enable, False to bypass
        """
        self._filtering = enabled
        status = "enabled" if enabled else "disabled"
        self.logger.info(f"RNNoise filter {status}")

    async def filter(self, audio: bytes) -> bytes:
        """
        Apply RNNoise noise suppression to audio data.

        Buffers incoming audio and processes it in chunks that match RNNoise's
        required frame length (480 samples at 48kHz = 10ms).

        Args:
            audio: Raw audio data as bytes (16-bit signed integers, mono)

        Returns:
            Noise-suppressed audio data as bytes (same format as input)
        """
        # Bypass if not ready or disabled
        if not self._rnnoise_ready or not self._filtering:
            return audio

        # Empty audio check
        if len(audio) == 0:
            return b""

        # Step 1: Resample input to 48kHz (if needed)
        in_audio = audio
        if self._sample_rate != 48000 and self._resampler_in:
            in_audio = await self._resampler_in.resample(audio, self._sample_rate, 48000)

        if len(in_audio) == 0:
            return b""

        # Step 2: Convert bytes to numpy array (int16)
        audio_samples = np.frombuffer(in_audio, dtype=np.int16)

        # Step 3: Process through RNNoise
        # denoise_chunk yields (speech_prob, denoised_frame) tuples
        # denoised_frame is float32 normalized to [-1.0, 1.0]
        filtered_frames = []
        speech_probs = []

        for speech_prob, denoised_frame in self._rnnoise.denoise_chunk(audio_samples):
            # Convert float32 [-1.0, 1.0] to int16 [-32768, 32767]
            if np.issubdtype(denoised_frame.dtype, np.floating):
                denoised_int16 = (denoised_frame * 32767).astype(np.int16)
            else:
                denoised_int16 = denoised_frame.astype(np.int16)

            # Handle shape (pyrnnoise returns (channels, samples), e.g. (1, 480))
            # We want flat array for mono
            if denoised_int16.ndim > 1:
                denoised_int16 = denoised_int16.squeeze()

            filtered_frames.append(denoised_int16)
            speech_probs.append(speech_prob)

        # Step 4: Combine all processed frames
        if not filtered_frames:
            # Still buffering (RNNoise needs 480 samples = 10ms @ 48kHz)
            return b""

        filtered_audio = np.concatenate(filtered_frames).tobytes()

        # Update statistics
        self.total_frames += len(filtered_frames)
        avg_prob = np.mean(speech_probs)
        self.avg_speech_prob = (
            (self.avg_speech_prob * (self.total_frames - len(filtered_frames)) +
             sum(speech_probs)) / self.total_frames
        )

        if avg_prob > 0.5:
            self.speech_frames += len(filtered_frames)
        else:
            self.noise_frames += len(filtered_frames)

        # Step 5: Resample output back to original sample rate (if needed)
        if self._sample_rate != 48000 and self._resampler_out:
            return await self._resampler_out.resample(filtered_audio, 48000, self._sample_rate)

        return filtered_audio

    def get_stats(self) -> dict:
        """
        Get filter statistics.

        Returns:
            Dict with processing metrics
        """
        return {
            'enabled': self._filtering,
            'ready': self._rnnoise_ready,
            'sample_rate': self._sample_rate,
            'total_frames': self.total_frames,
            'speech_frames': self.speech_frames,
            'noise_frames': self.noise_frames,
            'avg_speech_prob': self.avg_speech_prob,
            'speech_ratio': (
                self.speech_frames / self.total_frames
                if self.total_frames > 0 else 0.0
            ),
        }


# Test function
async def test_rnnoise_filter():
    """Test RNNoise filter with synthetic audio"""
    import numpy as np

    print("\n=== RNNoise Filter Test ===\n")

    # Create filter
    filter = RNNoiseFilter()
    await filter.start(sample_rate=8000)

    if not filter._rnnoise_ready:
        print("❌ RNNoise not ready (missing dependencies)")
        return

    # Generate test audio (1 second @ 8kHz)
    sample_rate = 8000
    duration = 1.0
    num_samples = int(sample_rate * duration)

    # Clean speech: 440 Hz tone
    t = np.linspace(0, duration, num_samples)
    clean_signal = (np.sin(2 * np.pi * 440 * t) * 10000).astype(np.int16)

    # Add noise
    noise = (np.random.randn(num_samples) * 2000).astype(np.int16)
    noisy_signal = clean_signal + noise

    print(f"Input: {num_samples} samples @ {sample_rate} Hz")
    print(f"Clean RMS: {np.sqrt(np.mean(clean_signal**2)):.1f}")
    print(f"Noisy RMS: {np.sqrt(np.mean(noisy_signal**2)):.1f}")

    # Process through filter
    filtered_audio = await filter.filter(noisy_signal.tobytes())

    if filtered_audio:
        filtered_signal = np.frombuffer(filtered_audio, dtype=np.int16)
        print(f"Filtered RMS: {np.sqrt(np.mean(filtered_signal**2)):.1f}")
        print(f"\n✅ RNNoise filter working!")
    else:
        print("⚠️  Still buffering (need more audio)")

    # Stats
    print(f"\nStats: {filter.get_stats()}")

    await filter.stop()


if __name__ == '__main__':
    import asyncio
    asyncio.run(test_rnnoise_filter())
