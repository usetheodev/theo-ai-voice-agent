"""Optimized audio buffers for low-latency streaming.

This module provides high-performance audio buffering using numpy:
- RingBuffer: Pre-allocated circular buffer with zero-copy operations
- BufferPool: Reuse allocated buffers to avoid allocation overhead
- Optimized audio conversion functions

For voice applications, these buffers can reduce latency by:
- Eliminating memory allocations during streaming
- Using vectorized numpy operations instead of Python loops
- Providing zero-copy views of audio data

Example:
    >>> from voice_pipeline.streaming.optimized_buffer import RingBuffer, BufferPool
    >>>
    >>> # Ring buffer for continuous audio streaming
    >>> ring = RingBuffer(sample_rate=16000, max_duration_seconds=5.0)
    >>> ring.append(audio_chunk)  # Fast append
    >>> data = ring.get_view()    # Zero-copy view
    >>>
    >>> # Buffer pool for chunk processing
    >>> pool = BufferPool(chunk_size=320, pool_size=10)
    >>> buf = pool.acquire()      # Get pre-allocated buffer
    >>> # ... use buffer ...
    >>> pool.release(buf)         # Return to pool for reuse
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Tuple

import numpy as np
from numpy.typing import NDArray


@dataclass
class RingBufferConfig:
    """Configuration for RingBuffer.

    Attributes:
        sample_rate: Audio sample rate in Hz (default 16000).
        max_duration_seconds: Maximum buffer duration (default 30.0).
        dtype: Numpy dtype for samples (default int16 for PCM16).
    """
    sample_rate: int = 16000
    max_duration_seconds: float = 30.0
    dtype: np.dtype = field(default_factory=lambda: np.dtype(np.int16))


class RingBuffer:
    """High-performance circular buffer for audio streaming.

    Uses a pre-allocated numpy array to store audio samples, avoiding
    memory allocation during streaming. Supports zero-copy views for
    reading data without copying.

    Thread-safe for single producer, single consumer pattern.

    Features:
    - Pre-allocated memory (no allocations during streaming)
    - Zero-copy views via numpy slicing
    - Automatic wraparound (circular buffer)
    - Thread-safe append and read operations

    Example:
        >>> ring = RingBuffer(sample_rate=16000, max_duration_seconds=5.0)
        >>>
        >>> # Append audio (from PCM16 bytes)
        >>> ring.append_bytes(audio_bytes)
        >>>
        >>> # Or append numpy array directly
        >>> ring.append(np.array([1, 2, 3], dtype=np.int16))
        >>>
        >>> # Get view (zero-copy)
        >>> view = ring.get_view()
        >>>
        >>> # Get copy if needed
        >>> data = ring.get_copy()
        >>>
        >>> # Clear buffer
        >>> ring.clear()
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        max_duration_seconds: float = 30.0,
        dtype: np.dtype = np.int16,
        config: Optional[RingBufferConfig] = None,
    ):
        """Initialize ring buffer.

        Args:
            sample_rate: Audio sample rate in Hz.
            max_duration_seconds: Maximum buffer duration.
            dtype: Numpy dtype for samples (default int16 for PCM16).
            config: Optional configuration object (overrides other args).
        """
        if config:
            sample_rate = config.sample_rate
            max_duration_seconds = config.max_duration_seconds
            dtype = config.dtype

        self._sample_rate = sample_rate
        self._max_duration = max_duration_seconds
        self._dtype = np.dtype(dtype)

        # Calculate buffer size
        self._max_samples = int(sample_rate * max_duration_seconds)

        # Pre-allocate buffer
        self._buffer: NDArray = np.zeros(self._max_samples, dtype=self._dtype)

        # Read and write positions
        self._write_pos = 0
        self._read_pos = 0
        self._count = 0  # Number of valid samples

        # Thread safety
        self._lock = threading.Lock()

    @property
    def sample_rate(self) -> int:
        """Audio sample rate in Hz."""
        return self._sample_rate

    @property
    def max_samples(self) -> int:
        """Maximum number of samples the buffer can hold."""
        return self._max_samples

    @property
    def max_duration_seconds(self) -> float:
        """Maximum buffer duration in seconds."""
        return self._max_duration

    @property
    def count(self) -> int:
        """Current number of valid samples in buffer."""
        with self._lock:
            return self._count

    @property
    def duration_seconds(self) -> float:
        """Current buffer duration in seconds."""
        with self._lock:
            return self._count / self._sample_rate

    @property
    def is_empty(self) -> bool:
        """Whether buffer is empty."""
        with self._lock:
            return self._count == 0

    @property
    def is_full(self) -> bool:
        """Whether buffer is at maximum capacity."""
        with self._lock:
            return self._count >= self._max_samples

    @property
    def available_space(self) -> int:
        """Number of samples that can be added before overflow."""
        with self._lock:
            return self._max_samples - self._count

    def append(self, samples: NDArray) -> int:
        """Append samples to buffer.

        If buffer would overflow, oldest samples are discarded.

        Args:
            samples: Numpy array of samples (will be cast to buffer dtype).

        Returns:
            Number of samples actually written.
        """
        if len(samples) == 0:
            return 0

        # Ensure correct dtype
        if samples.dtype != self._dtype:
            samples = samples.astype(self._dtype)

        n = len(samples)

        with self._lock:
            # If more samples than buffer size, only keep latest
            if n >= self._max_samples:
                samples = samples[-self._max_samples:]
                n = self._max_samples
                self._buffer[:] = samples
                self._write_pos = 0
                self._read_pos = 0
                self._count = n
                return n

            # Check if we need to discard old data
            overflow = max(0, self._count + n - self._max_samples)
            if overflow > 0:
                self._read_pos = (self._read_pos + overflow) % self._max_samples
                self._count -= overflow

            # Write data (may need to wrap)
            end_pos = self._write_pos + n

            if end_pos <= self._max_samples:
                # No wrap needed
                self._buffer[self._write_pos:end_pos] = samples
            else:
                # Wrap around
                first_part = self._max_samples - self._write_pos
                self._buffer[self._write_pos:] = samples[:first_part]
                self._buffer[:n - first_part] = samples[first_part:]

            self._write_pos = end_pos % self._max_samples
            self._count += n

            return n

    def append_bytes(self, audio_bytes: bytes) -> int:
        """Append PCM16 audio bytes to buffer.

        Args:
            audio_bytes: PCM16 audio data (little-endian).

        Returns:
            Number of samples written.
        """
        if len(audio_bytes) == 0:
            return 0

        # Convert bytes to numpy array (zero-copy via frombuffer)
        samples = np.frombuffer(audio_bytes, dtype=np.int16)
        return self.append(samples)

    def get_view(self) -> NDArray:
        """Get a view of the buffer contents.

        WARNING: This may return a copy if data wraps around the buffer.
        For guaranteed zero-copy, use get_contiguous_views().

        Returns:
            Numpy array with buffer contents.
        """
        with self._lock:
            if self._count == 0:
                return np.array([], dtype=self._dtype)

            # Check if data is contiguous
            end_pos = (self._read_pos + self._count) % self._max_samples

            if end_pos > self._read_pos or end_pos == 0:
                # Contiguous - can return view
                return self._buffer[self._read_pos:self._read_pos + self._count]
            else:
                # Wrapped - need to concatenate
                first_part = self._buffer[self._read_pos:]
                second_part = self._buffer[:end_pos]
                return np.concatenate([first_part, second_part])

    def get_contiguous_views(self) -> Tuple[NDArray, Optional[NDArray]]:
        """Get zero-copy views of buffer contents.

        If data wraps around, returns two views. Otherwise returns
        one view and None.

        Returns:
            Tuple of (first_view, second_view_or_none).
        """
        with self._lock:
            if self._count == 0:
                return np.array([], dtype=self._dtype), None

            end_pos = (self._read_pos + self._count) % self._max_samples

            if end_pos > self._read_pos or end_pos == 0:
                # Contiguous
                return self._buffer[self._read_pos:self._read_pos + self._count], None
            else:
                # Wrapped
                return self._buffer[self._read_pos:], self._buffer[:end_pos]

    def get_copy(self) -> NDArray:
        """Get a copy of buffer contents.

        Always returns a new array, safe to modify.

        Returns:
            Numpy array copy of buffer contents.
        """
        view = self.get_view()
        return view.copy()

    def get_bytes(self) -> bytes:
        """Get buffer contents as PCM16 bytes.

        Returns:
            PCM16 audio data (little-endian).
        """
        return self.get_view().tobytes()

    def consume(self, n_samples: int) -> NDArray:
        """Consume and return samples from buffer.

        Args:
            n_samples: Number of samples to consume.

        Returns:
            Numpy array with consumed samples.
        """
        with self._lock:
            n = min(n_samples, self._count)
            if n == 0:
                return np.array([], dtype=self._dtype)

            end_pos = (self._read_pos + n) % self._max_samples

            if end_pos > self._read_pos or end_pos == 0:
                result = self._buffer[self._read_pos:self._read_pos + n].copy()
            else:
                first_part = self._buffer[self._read_pos:]
                second_part = self._buffer[:end_pos]
                result = np.concatenate([first_part, second_part])

            self._read_pos = end_pos
            self._count -= n

            return result

    def consume_bytes(self, n_samples: int) -> bytes:
        """Consume and return samples as PCM16 bytes.

        Args:
            n_samples: Number of samples to consume.

        Returns:
            PCM16 audio data (little-endian).
        """
        return self.consume(n_samples).tobytes()

    def clear(self) -> None:
        """Clear the buffer."""
        with self._lock:
            self._write_pos = 0
            self._read_pos = 0
            self._count = 0

    def peek(self, n_samples: int) -> NDArray:
        """Peek at samples without consuming.

        Args:
            n_samples: Number of samples to peek.

        Returns:
            Numpy array with samples (copy).
        """
        with self._lock:
            n = min(n_samples, self._count)
            if n == 0:
                return np.array([], dtype=self._dtype)

            end_pos = (self._read_pos + n) % self._max_samples

            if end_pos > self._read_pos or end_pos == 0:
                return self._buffer[self._read_pos:self._read_pos + n].copy()
            else:
                first_part = self._buffer[self._read_pos:]
                second_part = self._buffer[:end_pos]
                return np.concatenate([first_part, second_part])


class BufferPool:
    """Pool of pre-allocated buffers for reuse.

    Reduces allocation overhead by reusing buffers. Useful for
    processing audio in fixed-size chunks.

    Thread-safe for multi-threaded access.

    Example:
        >>> pool = BufferPool(chunk_size=320, pool_size=10)
        >>>
        >>> # Acquire buffer
        >>> buf = pool.acquire()
        >>> buf[:] = audio_data  # Use buffer
        >>>
        >>> # Return to pool
        >>> pool.release(buf)
        >>>
        >>> # Or use context manager
        >>> with pool.acquire_context() as buf:
        ...     buf[:] = audio_data
    """

    def __init__(
        self,
        chunk_size: int = 320,
        pool_size: int = 10,
        dtype: np.dtype = np.int16,
    ):
        """Initialize buffer pool.

        Args:
            chunk_size: Size of each buffer in samples.
            pool_size: Number of buffers to pre-allocate.
            dtype: Numpy dtype for buffers.
        """
        self._chunk_size = chunk_size
        self._pool_size = pool_size
        self._dtype = np.dtype(dtype)

        # Pre-allocate buffers
        self._pool: deque[NDArray] = deque()
        for _ in range(pool_size):
            self._pool.append(np.zeros(chunk_size, dtype=dtype))

        # Track buffers in use
        self._in_use = 0
        self._total_allocated = pool_size

        # Thread safety
        self._lock = threading.Lock()

    @property
    def chunk_size(self) -> int:
        """Size of each buffer in samples."""
        return self._chunk_size

    @property
    def pool_size(self) -> int:
        """Initial pool size."""
        return self._pool_size

    @property
    def available(self) -> int:
        """Number of buffers available in pool."""
        with self._lock:
            return len(self._pool)

    @property
    def in_use(self) -> int:
        """Number of buffers currently in use."""
        with self._lock:
            return self._in_use

    @property
    def total_allocated(self) -> int:
        """Total number of buffers allocated (including overflow)."""
        with self._lock:
            return self._total_allocated

    def acquire(self) -> NDArray:
        """Acquire a buffer from pool.

        If pool is empty, allocates a new buffer.

        Returns:
            Numpy array buffer (contents undefined, may need clearing).
        """
        with self._lock:
            if self._pool:
                buf = self._pool.popleft()
            else:
                # Pool exhausted, allocate new
                buf = np.zeros(self._chunk_size, dtype=self._dtype)
                self._total_allocated += 1

            self._in_use += 1
            return buf

    def acquire_zeroed(self) -> NDArray:
        """Acquire a zeroed buffer from pool.

        Returns:
            Numpy array buffer filled with zeros.
        """
        buf = self.acquire()
        buf.fill(0)
        return buf

    def release(self, buf: NDArray) -> None:
        """Return buffer to pool.

        Args:
            buf: Buffer to return (must have correct size).
        """
        if len(buf) != self._chunk_size:
            # Wrong size, don't return to pool
            return

        with self._lock:
            self._pool.append(buf)
            self._in_use -= 1

    def acquire_context(self):
        """Context manager for automatic buffer release.

        Example:
            >>> with pool.acquire_context() as buf:
            ...     buf[:] = data
        """
        return _BufferContext(self)

    def clear(self) -> None:
        """Clear pool and release all buffers."""
        with self._lock:
            self._pool.clear()
            self._in_use = 0

    def resize(self, new_pool_size: int) -> None:
        """Resize pool to new size.

        Args:
            new_pool_size: New pool size.
        """
        with self._lock:
            current_size = len(self._pool)

            if new_pool_size > current_size:
                # Add more buffers
                for _ in range(new_pool_size - current_size):
                    self._pool.append(np.zeros(self._chunk_size, dtype=self._dtype))
                    self._total_allocated += 1
            elif new_pool_size < current_size:
                # Remove buffers
                for _ in range(current_size - new_pool_size):
                    if self._pool:
                        self._pool.pop()

            self._pool_size = new_pool_size


class _BufferContext:
    """Context manager for BufferPool."""

    def __init__(self, pool: BufferPool):
        self._pool = pool
        self._buf: Optional[NDArray] = None

    def __enter__(self) -> NDArray:
        self._buf = self._pool.acquire()
        return self._buf

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._buf is not None:
            self._pool.release(self._buf)
            self._buf = None
        return False


# =============================================================================
# Optimized Audio Functions (numpy-based)
# =============================================================================


def pcm16_to_float_np(audio_bytes: bytes) -> NDArray[np.float32]:
    """Convert PCM16 bytes to float32 array (optimized).

    Uses numpy for fast vectorized conversion.

    Args:
        audio_bytes: PCM16 audio data (little-endian).

    Returns:
        Float32 array in range [-1.0, 1.0].
    """
    if len(audio_bytes) == 0:
        return np.array([], dtype=np.float32)

    # Zero-copy view of bytes as int16
    samples = np.frombuffer(audio_bytes, dtype=np.int16)

    # Vectorized conversion to float
    return samples.astype(np.float32) / 32768.0


def float_to_pcm16_np(samples: NDArray[np.float32]) -> bytes:
    """Convert float32 array to PCM16 bytes (optimized).

    Uses numpy for fast vectorized conversion.

    Args:
        samples: Float32 array in range [-1.0, 1.0].

    Returns:
        PCM16 audio data (little-endian).
    """
    if len(samples) == 0:
        return b""

    # Clip and convert
    clipped = np.clip(samples, -1.0, 1.0)
    pcm16 = (clipped * 32767).astype(np.int16)

    return pcm16.tobytes()


def calculate_rms_np(audio_bytes: bytes) -> float:
    """Calculate RMS of PCM16 audio (optimized).

    Args:
        audio_bytes: PCM16 audio data.

    Returns:
        RMS value in range [0.0, 1.0].
    """
    if len(audio_bytes) == 0:
        return 0.0

    samples = pcm16_to_float_np(audio_bytes)
    return float(np.sqrt(np.mean(samples ** 2)))


def calculate_rms_from_array(samples: NDArray) -> float:
    """Calculate RMS from numpy array.

    Args:
        samples: Audio samples (any dtype, will be converted to float).

    Returns:
        RMS value.
    """
    if len(samples) == 0:
        return 0.0

    float_samples = samples.astype(np.float64)

    # Normalize if int16
    if samples.dtype == np.int16:
        float_samples = float_samples / 32768.0

    return float(np.sqrt(np.mean(float_samples ** 2)))


def calculate_db_np(audio_bytes: bytes, reference: float = 1.0) -> float:
    """Calculate decibels from PCM16 audio (optimized).

    Args:
        audio_bytes: PCM16 audio data.
        reference: Reference level (default 1.0 for full scale).

    Returns:
        Level in dB (negative values, -inf for silence).
    """
    rms = calculate_rms_np(audio_bytes)
    if rms <= 0:
        return float('-inf')
    return float(20 * np.log10(rms / reference))


def _resample_np_with_filter(
    samples: NDArray[np.float32],
    source_rate: int,
    target_rate: int,
) -> NDArray[np.float32]:
    """Resample float32 array with anti-aliasing filter.

    Uses scipy.signal.resample_poly when available, otherwise falls
    back to windowed-sinc FIR filter (Hamming, 63 taps) + interpolation.

    Args:
        samples: Float32 audio samples.
        source_rate: Source sample rate in Hz.
        target_rate: Target sample rate in Hz.

    Returns:
        Resampled float32 array.
    """
    try:
        from scipy.signal import resample_poly
        from math import gcd
        g = gcd(source_rate, target_rate)
        return resample_poly(samples, target_rate // g, source_rate // g).astype(np.float32)
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
        samples = np.convolve(samples, fir, mode='same').astype(np.float32)

    new_len = int(len(samples) * ratio)
    if new_len == 0:
        return np.array([], dtype=np.float32)
    new_positions = np.linspace(0, len(samples) - 1, new_len)
    old_positions = np.arange(len(samples))
    return np.interp(new_positions, old_positions, samples).astype(np.float32)


def resample_audio_np(
    audio_bytes: bytes,
    source_rate: int,
    target_rate: int,
) -> bytes:
    """Resample PCM16 audio with anti-aliasing filter (optimized).

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

    if len(audio_bytes) == 0:
        return b""

    # Convert to numpy float32
    samples = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)

    # Resample with anti-aliasing
    resampled = _resample_np_with_filter(samples, source_rate, target_rate)

    if len(resampled) == 0:
        return b""

    # Convert back to PCM16
    return resampled.astype(np.int16).tobytes()


def mix_audio_np(
    audio1: bytes,
    audio2: bytes,
    weight1: float = 1.0,
    weight2: float = 1.0,
) -> bytes:
    """Mix two PCM16 audio streams.

    Args:
        audio1: First PCM16 audio stream.
        audio2: Second PCM16 audio stream.
        weight1: Weight for first stream (default 1.0).
        weight2: Weight for second stream (default 1.0).

    Returns:
        Mixed PCM16 audio (length of longer input).
    """
    if len(audio1) == 0:
        return audio2
    if len(audio2) == 0:
        return audio1

    samples1 = np.frombuffer(audio1, dtype=np.int16).astype(np.float32)
    samples2 = np.frombuffer(audio2, dtype=np.int16).astype(np.float32)

    # Pad shorter array
    max_len = max(len(samples1), len(samples2))
    if len(samples1) < max_len:
        samples1 = np.pad(samples1, (0, max_len - len(samples1)))
    if len(samples2) < max_len:
        samples2 = np.pad(samples2, (0, max_len - len(samples2)))

    # Mix with weights
    mixed = samples1 * weight1 + samples2 * weight2

    # Clip and convert
    mixed = np.clip(mixed, -32768, 32767)
    return mixed.astype(np.int16).tobytes()


def apply_gain_np(audio_bytes: bytes, gain_db: float) -> bytes:
    """Apply gain to PCM16 audio.

    Args:
        audio_bytes: PCM16 audio data.
        gain_db: Gain in decibels (positive = louder, negative = quieter).

    Returns:
        Adjusted PCM16 audio data.
    """
    if len(audio_bytes) == 0 or gain_db == 0:
        return audio_bytes

    samples = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)

    # Convert dB to linear gain
    linear_gain = 10 ** (gain_db / 20)

    # Apply gain
    samples = samples * linear_gain

    # Clip and convert
    samples = np.clip(samples, -32768, 32767)
    return samples.astype(np.int16).tobytes()


def normalize_audio_np(audio_bytes: bytes, target_db: float = -3.0) -> bytes:
    """Normalize PCM16 audio to target level.

    Args:
        audio_bytes: PCM16 audio data.
        target_db: Target peak level in dB (default -3.0).

    Returns:
        Normalized PCM16 audio data.
    """
    if len(audio_bytes) == 0:
        return audio_bytes

    samples = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)

    # Find current peak
    peak = np.max(np.abs(samples))
    if peak == 0:
        return audio_bytes

    # Calculate required gain
    target_peak = 32768 * (10 ** (target_db / 20))
    gain = target_peak / peak

    # Apply gain
    samples = samples * gain

    # Clip and convert
    samples = np.clip(samples, -32768, 32767)
    return samples.astype(np.int16).tobytes()
