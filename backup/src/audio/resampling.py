"""
Audio Resampling Utilities

Provides high-quality audio resampling using scipy.signal.resample
Commonly used for converting between TTS output rate (24kHz) and codec rate (8kHz)
"""

import logging
import numpy as np
from scipy import signal
from typing import Union


logger = logging.getLogger("ai-voice-agent.audio.resampling")


def resample_audio(audio: Union[np.ndarray, bytes],
                   from_rate: int,
                   to_rate: int,
                   dtype: type = np.int16) -> np.ndarray:
    """
    Resample audio to different sample rate

    Args:
        audio: Audio data as numpy array or bytes (16-bit PCM)
        from_rate: Source sample rate (Hz)
        to_rate: Target sample rate (Hz)
        dtype: Output dtype (default: np.int16)

    Returns:
        Resampled audio as numpy array

    Examples:
        # Resample from 24kHz (Kokoro TTS) to 8kHz (G.711 codec)
        audio_8k = resample_audio(audio_24k, from_rate=24000, to_rate=8000)

        # Resample from bytes
        pcm_bytes = ...  # 16-bit PCM at 24kHz
        audio_8k = resample_audio(pcm_bytes, from_rate=24000, to_rate=8000)
    """
    try:
        # Convert bytes to numpy if needed
        if isinstance(audio, bytes):
            audio = np.frombuffer(audio, dtype=np.int16)

        # Validate input
        if not isinstance(audio, np.ndarray):
            raise ValueError(f"Audio must be numpy array or bytes, got {type(audio)}")

        if from_rate <= 0 or to_rate <= 0:
            raise ValueError(f"Sample rates must be positive: from={from_rate}, to={to_rate}")

        # If rates are the same, return as-is
        if from_rate == to_rate:
            return audio.astype(dtype)

        # Calculate target number of samples
        ratio = to_rate / from_rate
        num_samples = int(len(audio) * ratio)

        logger.debug(f"Resampling: {len(audio)} samples @ {from_rate}Hz → {num_samples} samples @ {to_rate}Hz")

        # Perform resampling using scipy (high quality)
        resampled = signal.resample(audio, num_samples)

        # Clip and convert to target dtype
        if dtype == np.int16:
            resampled = np.clip(resampled, -32768, 32767).astype(np.int16)
        elif dtype == np.float32:
            # Normalize to [-1.0, 1.0] if input was int16
            if audio.dtype == np.int16:
                resampled = resampled / 32768.0
            resampled = resampled.astype(np.float32)
        else:
            resampled = resampled.astype(dtype)

        return resampled

    except Exception as e:
        logger.error(f"Resampling error: {e}", exc_info=True)
        raise


def resample_to_bytes(audio: Union[np.ndarray, bytes],
                      from_rate: int,
                      to_rate: int) -> bytes:
    """
    Resample audio and return as 16-bit PCM bytes

    Args:
        audio: Audio data as numpy array or bytes
        from_rate: Source sample rate (Hz)
        to_rate: Target sample rate (Hz)

    Returns:
        Resampled audio as bytes (16-bit PCM little-endian)

    Example:
        # Resample Kokoro TTS output (24kHz) to G.711 codec rate (8kHz)
        pcm_8k_bytes = resample_to_bytes(audio_24k, from_rate=24000, to_rate=8000)
    """
    resampled = resample_audio(audio, from_rate, to_rate, dtype=np.int16)
    return resampled.tobytes()


def calculate_duration(samples: int, sample_rate: int) -> float:
    """
    Calculate audio duration in seconds

    Args:
        samples: Number of samples
        sample_rate: Sample rate (Hz)

    Returns:
        Duration in seconds
    """
    return samples / sample_rate if sample_rate > 0 else 0.0


def test_resampling():
    """Test resampling with synthetic audio"""
    # Generate 1 second of test audio at 24kHz (sine wave 440 Hz)
    sample_rate_in = 24000
    sample_rate_out = 8000
    duration = 1.0
    frequency = 440

    t = np.linspace(0, duration, int(sample_rate_in * duration))
    audio_24k = (np.sin(2 * np.pi * frequency * t) * 32767 * 0.5).astype(np.int16)

    print(f"Original: {len(audio_24k)} samples @ {sample_rate_in}Hz ({calculate_duration(len(audio_24k), sample_rate_in):.2f}s)")

    # Resample to 8kHz
    audio_8k = resample_audio(audio_24k, from_rate=24000, to_rate=8000)

    print(f"Resampled: {len(audio_8k)} samples @ {sample_rate_out}Hz ({calculate_duration(len(audio_8k), sample_rate_out):.2f}s)")
    print(f"Expected samples: {int(len(audio_24k) * 8000 / 24000)} (ratio: {8000/24000:.3f})")

    # Test bytes conversion
    audio_8k_bytes = resample_to_bytes(audio_24k, from_rate=24000, to_rate=8000)
    print(f"Bytes output: {len(audio_8k_bytes)} bytes ({len(audio_8k_bytes)/2} samples)")


if __name__ == '__main__':
    test_resampling()
