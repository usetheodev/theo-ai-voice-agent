"""
Audio Resampling Utilities

Provides high-quality audio resampling using scipy.signal.resample
Commonly used for converting between TTS output rate (24kHz) and codec rate (8kHz)
"""

import numpy as np
from scipy import signal
from typing import Union

from ..common.logging import get_logger

logger = get_logger('audio.resampling')


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

        logger.debug("Resampling audio",
                    from_samples=len(audio),
                    from_rate=from_rate,
                    to_samples=num_samples,
                    to_rate=to_rate)

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
        logger.error("Resampling error", error=str(e))
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
