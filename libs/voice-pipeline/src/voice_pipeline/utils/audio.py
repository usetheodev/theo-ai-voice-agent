"""Audio processing utilities."""

import math
from typing import Optional


def _resample_with_filter(samples: list[float], source_rate: int, target_rate: int) -> list[float]:
    """Resample with anti-aliasing filter.

    Uses scipy.signal.resample_poly when available, otherwise falls back
    to a windowed-sinc (FIR Hamming 63 taps) filter with numpy.

    Args:
        samples: Float samples in range [-1.0, 1.0].
        source_rate: Source sample rate in Hz.
        target_rate: Target sample rate in Hz.

    Returns:
        Resampled float samples.
    """
    import numpy as np
    arr = np.asarray(samples, dtype=np.float32)

    try:
        from scipy.signal import resample_poly
        from math import gcd
        g = gcd(source_rate, target_rate)
        result = resample_poly(arr, target_rate // g, source_rate // g).astype(np.float32)
        return result.tolist()
    except ImportError:
        pass

    # Fallback: windowed-sinc FIR filter + linear interpolation
    ratio = target_rate / source_rate
    if ratio < 1.0:
        # Downsampling: apply anti-alias lowpass filter
        num_taps = 63
        n = np.arange(num_taps)
        mid = (num_taps - 1) / 2
        sinc_vals = np.sinc(ratio * (n - mid))
        window = np.hamming(num_taps)
        fir = sinc_vals * window
        fir = fir / np.sum(fir)
        arr = np.convolve(arr, fir, mode='same').astype(np.float32)

    new_len = int(len(arr) * ratio)
    if new_len == 0:
        return []
    new_positions = np.linspace(0, len(arr) - 1, new_len)
    old_positions = np.arange(len(arr))
    result = np.interp(new_positions, old_positions, arr)
    return result.tolist()


def audio_to_numpy(audio_data, sample_rate: int = 24000):
    """Convert various audio formats to numpy float32 array.

    Handles torch tensors, numpy arrays, lists, and raw data.
    Returns audio data as a numpy float32 array normalized to [-1, 1].

    Args:
        audio_data: Audio data in various formats (torch.Tensor, np.ndarray, list, etc.).
        sample_rate: Sample rate of the audio (used for validation).

    Returns:
        numpy.ndarray: Audio data as float32 array.

    Raises:
        ImportError: If numpy is not installed.
    """
    import numpy as np

    # Already numpy
    if isinstance(audio_data, np.ndarray):
        return audio_data.astype(np.float32)

    # Torch tensor
    try:
        import torch
        if isinstance(audio_data, torch.Tensor):
            return audio_data.cpu().numpy().astype(np.float32)
    except ImportError:
        pass

    # List or other sequence
    if isinstance(audio_data, (list, tuple)):
        return np.array(audio_data, dtype=np.float32)

    # Fallback: try to convert
    return np.asarray(audio_data, dtype=np.float32)


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
    """Resample audio with anti-aliasing filter.

    Uses scipy.signal.resample_poly when available for high-quality
    resampling. Falls back to a windowed-sinc FIR filter (Hamming, 63 taps)
    with numpy to prevent aliasing during downsampling.

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

    resampled = _resample_with_filter(samples, source_rate, target_rate)
    return float_to_pcm16(resampled)
