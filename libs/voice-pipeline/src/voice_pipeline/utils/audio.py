"""Audio processing utilities."""

import math
from typing import Optional


def pcm16_to_float(audio_bytes: bytes) -> list[float]:
    """Convert PCM16 audio bytes to float samples.

    Args:
        audio_bytes: PCM16 audio data (little-endian).

    Returns:
        List of float samples in range [-1.0, 1.0].
    """
    samples = []
    for i in range(0, len(audio_bytes), 2):
        if i + 1 < len(audio_bytes):
            # Little-endian 16-bit signed
            sample = int.from_bytes(audio_bytes[i:i+2], byteorder='little', signed=True)
            samples.append(sample / 32768.0)
    return samples


def float_to_pcm16(samples: list[float]) -> bytes:
    """Convert float samples to PCM16 audio bytes.

    Args:
        samples: Float samples in range [-1.0, 1.0].

    Returns:
        PCM16 audio data (little-endian).
    """
    result = bytearray()
    for sample in samples:
        # Clamp to valid range
        clamped = max(-1.0, min(1.0, sample))
        # Convert to 16-bit signed integer
        value = int(clamped * 32767)
        result.extend(value.to_bytes(2, byteorder='little', signed=True))
    return bytes(result)


def calculate_rms(audio_bytes: bytes) -> float:
    """Calculate RMS (Root Mean Square) of audio.

    Args:
        audio_bytes: PCM16 audio data.

    Returns:
        RMS value in range [0.0, 1.0].
    """
    samples = pcm16_to_float(audio_bytes)
    if not samples:
        return 0.0

    sum_squares = sum(s * s for s in samples)
    return math.sqrt(sum_squares / len(samples))


def calculate_db(audio_bytes: bytes, reference: float = 1.0) -> float:
    """Calculate decibels from RMS.

    Args:
        audio_bytes: PCM16 audio data.
        reference: Reference level (default 1.0 for full scale).

    Returns:
        Level in dB (negative values, -inf for silence).
    """
    rms = calculate_rms(audio_bytes)
    if rms <= 0:
        return float('-inf')
    return 20 * math.log10(rms / reference)


def resample_audio(
    audio_bytes: bytes,
    source_rate: int,
    target_rate: int,
) -> bytes:
    """Simple audio resampling using linear interpolation.

    For production use, consider using a proper resampling library
    like librosa or scipy for better quality.

    Args:
        audio_bytes: PCM16 audio data.
        source_rate: Source sample rate in Hz.
        target_rate: Target sample rate in Hz.

    Returns:
        Resampled PCM16 audio data.
    """
    if source_rate == target_rate:
        return audio_bytes

    samples = pcm16_to_float(audio_bytes)
    if not samples:
        return b""

    # Calculate ratio
    ratio = source_rate / target_rate
    new_length = int(len(samples) / ratio)

    # Linear interpolation
    resampled = []
    for i in range(new_length):
        pos = i * ratio
        idx = int(pos)
        frac = pos - idx

        if idx + 1 < len(samples):
            value = samples[idx] * (1 - frac) + samples[idx + 1] * frac
        else:
            value = samples[-1]
        resampled.append(value)

    return float_to_pcm16(resampled)
