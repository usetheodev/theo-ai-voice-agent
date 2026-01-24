"""Tests for optimized audio buffers.

Tests cover:
- RingBuffer: circular buffer with zero-copy operations
- BufferPool: buffer reuse for reduced allocations
- Optimized audio functions: numpy-based conversions
"""

import numpy as np
import pytest

from voice_pipeline.streaming.optimized_buffer import (
    RingBuffer,
    RingBufferConfig,
    BufferPool,
    pcm16_to_float_np,
    float_to_pcm16_np,
    calculate_rms_np,
    calculate_rms_from_array,
    calculate_db_np,
    resample_audio_np,
    mix_audio_np,
    apply_gain_np,
    normalize_audio_np,
)


# =============================================================================
# RingBuffer Tests
# =============================================================================


class TestRingBuffer:
    """Tests for RingBuffer."""

    def test_init_default(self):
        """Test default initialization."""
        ring = RingBuffer()

        assert ring.sample_rate == 16000
        assert ring.max_duration_seconds == 30.0
        assert ring.max_samples == 16000 * 30
        assert ring.count == 0
        assert ring.is_empty
        assert not ring.is_full

    def test_init_custom(self):
        """Test custom initialization."""
        ring = RingBuffer(sample_rate=8000, max_duration_seconds=5.0)

        assert ring.sample_rate == 8000
        assert ring.max_samples == 8000 * 5
        assert ring.max_duration_seconds == 5.0

    def test_init_from_config(self):
        """Test initialization from config."""
        config = RingBufferConfig(
            sample_rate=44100,
            max_duration_seconds=10.0,
        )
        ring = RingBuffer(config=config)

        assert ring.sample_rate == 44100
        assert ring.max_duration_seconds == 10.0

    def test_append_samples(self):
        """Test appending numpy array samples."""
        ring = RingBuffer(sample_rate=16000, max_duration_seconds=1.0)
        samples = np.array([1, 2, 3, 4, 5], dtype=np.int16)

        written = ring.append(samples)

        assert written == 5
        assert ring.count == 5
        assert not ring.is_empty

    def test_append_bytes(self):
        """Test appending PCM16 bytes."""
        ring = RingBuffer()
        # Create PCM16 bytes (5 samples)
        samples = np.array([100, 200, 300, 400, 500], dtype=np.int16)
        audio_bytes = samples.tobytes()

        written = ring.append_bytes(audio_bytes)

        assert written == 5
        assert ring.count == 5

    def test_get_view(self):
        """Test getting view of buffer contents."""
        ring = RingBuffer()
        samples = np.array([1, 2, 3, 4, 5], dtype=np.int16)
        ring.append(samples)

        view = ring.get_view()

        assert len(view) == 5
        np.testing.assert_array_equal(view, samples)

    def test_get_copy(self):
        """Test getting copy of buffer contents."""
        ring = RingBuffer()
        samples = np.array([1, 2, 3, 4, 5], dtype=np.int16)
        ring.append(samples)

        copy = ring.get_copy()

        # Modify copy
        copy[0] = 999

        # Original should be unchanged
        view = ring.get_view()
        assert view[0] == 1

    def test_get_bytes(self):
        """Test getting buffer as PCM16 bytes."""
        ring = RingBuffer()
        original = np.array([1, 2, 3, 4, 5], dtype=np.int16)
        ring.append(original)

        result_bytes = ring.get_bytes()
        result = np.frombuffer(result_bytes, dtype=np.int16)

        np.testing.assert_array_equal(result, original)

    def test_consume(self):
        """Test consuming samples from buffer."""
        ring = RingBuffer()
        samples = np.array([1, 2, 3, 4, 5], dtype=np.int16)
        ring.append(samples)

        consumed = ring.consume(3)

        assert len(consumed) == 3
        np.testing.assert_array_equal(consumed, [1, 2, 3])
        assert ring.count == 2

    def test_consume_bytes(self):
        """Test consuming samples as bytes."""
        ring = RingBuffer()
        samples = np.array([1, 2, 3, 4, 5], dtype=np.int16)
        ring.append(samples)

        consumed = ring.consume_bytes(3)
        result = np.frombuffer(consumed, dtype=np.int16)

        np.testing.assert_array_equal(result, [1, 2, 3])
        assert ring.count == 2

    def test_peek(self):
        """Test peeking without consuming."""
        ring = RingBuffer()
        samples = np.array([1, 2, 3, 4, 5], dtype=np.int16)
        ring.append(samples)

        peeked = ring.peek(3)

        np.testing.assert_array_equal(peeked, [1, 2, 3])
        assert ring.count == 5  # Not consumed

    def test_clear(self):
        """Test clearing buffer."""
        ring = RingBuffer()
        samples = np.array([1, 2, 3, 4, 5], dtype=np.int16)
        ring.append(samples)

        ring.clear()

        assert ring.count == 0
        assert ring.is_empty

    def test_circular_wraparound(self):
        """Test circular buffer wraparound."""
        # Small buffer for easy testing
        ring = RingBuffer(sample_rate=10, max_duration_seconds=1.0)  # 10 samples max

        # Fill buffer
        samples1 = np.array([1, 2, 3, 4, 5, 6, 7, 8], dtype=np.int16)
        ring.append(samples1)
        assert ring.count == 8

        # Add more (should wrap and discard old)
        samples2 = np.array([10, 11, 12, 13, 14], dtype=np.int16)
        ring.append(samples2)

        assert ring.count == 10  # Max capacity

        # Should have latest 10 samples
        view = ring.get_view()
        assert len(view) == 10

        # Oldest data should be discarded
        # [4, 5, 6, 7, 8, 10, 11, 12, 13, 14]
        assert 1 not in view  # 1 was discarded
        assert 14 in view  # Latest is present

    def test_overflow_discards_oldest(self):
        """Test that overflow discards oldest samples."""
        ring = RingBuffer(sample_rate=5, max_duration_seconds=1.0)  # 5 samples max

        # Add 3 samples
        ring.append(np.array([1, 2, 3], dtype=np.int16))
        assert ring.count == 3

        # Add 4 more (total 7, but max is 5)
        ring.append(np.array([4, 5, 6, 7], dtype=np.int16))
        assert ring.count == 5

        view = ring.get_view()
        # Should have [3, 4, 5, 6, 7] (oldest 1, 2 discarded)
        np.testing.assert_array_equal(view, [3, 4, 5, 6, 7])

    def test_duration_seconds(self):
        """Test duration calculation."""
        ring = RingBuffer(sample_rate=16000, max_duration_seconds=1.0)

        # Add 8000 samples = 0.5 seconds
        samples = np.zeros(8000, dtype=np.int16)
        ring.append(samples)

        assert ring.duration_seconds == pytest.approx(0.5, rel=1e-6)

    def test_available_space(self):
        """Test available space calculation."""
        ring = RingBuffer(sample_rate=100, max_duration_seconds=1.0)  # 100 samples max

        assert ring.available_space == 100

        ring.append(np.zeros(30, dtype=np.int16))
        assert ring.available_space == 70

    def test_is_full(self):
        """Test is_full property."""
        ring = RingBuffer(sample_rate=10, max_duration_seconds=1.0)

        assert not ring.is_full

        ring.append(np.zeros(10, dtype=np.int16))
        assert ring.is_full

    def test_empty_operations(self):
        """Test operations on empty buffer."""
        ring = RingBuffer()

        assert ring.is_empty
        assert ring.count == 0
        assert len(ring.get_view()) == 0
        assert len(ring.consume(10)) == 0
        assert ring.consume_bytes(10) == b""

    def test_get_contiguous_views(self):
        """Test getting contiguous views."""
        ring = RingBuffer(sample_rate=10, max_duration_seconds=1.0)

        # Add samples (no wrap)
        ring.append(np.array([1, 2, 3, 4, 5], dtype=np.int16))

        view1, view2 = ring.get_contiguous_views()
        assert view2 is None  # No wrap
        np.testing.assert_array_equal(view1, [1, 2, 3, 4, 5])


# =============================================================================
# BufferPool Tests
# =============================================================================


class TestBufferPool:
    """Tests for BufferPool."""

    def test_init_default(self):
        """Test default initialization."""
        pool = BufferPool()

        assert pool.chunk_size == 320
        assert pool.pool_size == 10
        assert pool.available == 10
        assert pool.in_use == 0

    def test_init_custom(self):
        """Test custom initialization."""
        pool = BufferPool(chunk_size=512, pool_size=5)

        assert pool.chunk_size == 512
        assert pool.pool_size == 5
        assert pool.available == 5

    def test_acquire(self):
        """Test acquiring buffer from pool."""
        pool = BufferPool(chunk_size=100, pool_size=3)

        buf = pool.acquire()

        assert len(buf) == 100
        assert pool.available == 2
        assert pool.in_use == 1

    def test_acquire_zeroed(self):
        """Test acquiring zeroed buffer."""
        pool = BufferPool(chunk_size=100, pool_size=3)

        buf = pool.acquire_zeroed()

        assert len(buf) == 100
        assert np.all(buf == 0)

    def test_release(self):
        """Test releasing buffer back to pool."""
        pool = BufferPool(chunk_size=100, pool_size=3)

        buf = pool.acquire()
        assert pool.available == 2

        pool.release(buf)
        assert pool.available == 3
        assert pool.in_use == 0

    def test_acquire_context(self):
        """Test context manager for buffer."""
        pool = BufferPool(chunk_size=100, pool_size=3)

        with pool.acquire_context() as buf:
            assert len(buf) == 100
            assert pool.in_use == 1

        # Should be released after context
        assert pool.in_use == 0

    def test_pool_exhaustion_creates_new(self):
        """Test that exhausting pool creates new buffers."""
        pool = BufferPool(chunk_size=100, pool_size=2)

        buf1 = pool.acquire()
        buf2 = pool.acquire()
        assert pool.available == 0

        # Pool exhausted, should create new
        buf3 = pool.acquire()

        assert len(buf3) == 100
        assert pool.total_allocated == 3  # More than initial

    def test_release_wrong_size_ignored(self):
        """Test that wrong-size buffers are not returned to pool."""
        pool = BufferPool(chunk_size=100, pool_size=3)

        wrong_size_buf = np.zeros(50, dtype=np.int16)
        pool.release(wrong_size_buf)

        assert pool.available == 3  # Unchanged

    def test_clear(self):
        """Test clearing pool."""
        pool = BufferPool(chunk_size=100, pool_size=3)

        pool.acquire()
        pool.clear()

        assert pool.available == 0
        assert pool.in_use == 0

    def test_resize_grow(self):
        """Test growing pool."""
        pool = BufferPool(chunk_size=100, pool_size=3)

        pool.resize(5)

        assert pool.available == 5

    def test_resize_shrink(self):
        """Test shrinking pool."""
        pool = BufferPool(chunk_size=100, pool_size=5)

        pool.resize(2)

        assert pool.available == 2


# =============================================================================
# Optimized Audio Functions Tests
# =============================================================================


class TestPCM16ToFloatNP:
    """Tests for pcm16_to_float_np."""

    def test_empty_input(self):
        """Test with empty input."""
        result = pcm16_to_float_np(b"")
        assert len(result) == 0

    def test_basic_conversion(self):
        """Test basic conversion."""
        # Max positive value
        samples = np.array([32767], dtype=np.int16)
        result = pcm16_to_float_np(samples.tobytes())

        assert len(result) == 1
        assert result[0] == pytest.approx(1.0, rel=1e-4)

    def test_negative_values(self):
        """Test negative value conversion."""
        samples = np.array([-32768], dtype=np.int16)
        result = pcm16_to_float_np(samples.tobytes())

        assert result[0] == pytest.approx(-1.0, rel=1e-4)

    def test_zero(self):
        """Test zero value."""
        samples = np.array([0], dtype=np.int16)
        result = pcm16_to_float_np(samples.tobytes())

        assert result[0] == 0.0


class TestFloatToPCM16NP:
    """Tests for float_to_pcm16_np."""

    def test_empty_input(self):
        """Test with empty input."""
        result = float_to_pcm16_np(np.array([], dtype=np.float32))
        assert result == b""

    def test_basic_conversion(self):
        """Test basic conversion."""
        samples = np.array([1.0], dtype=np.float32)
        result = float_to_pcm16_np(samples)

        result_int = np.frombuffer(result, dtype=np.int16)[0]
        assert result_int == 32767

    def test_clipping(self):
        """Test that values are clipped."""
        samples = np.array([2.0, -2.0], dtype=np.float32)
        result = float_to_pcm16_np(samples)

        result_int = np.frombuffer(result, dtype=np.int16)
        assert result_int[0] == 32767  # Clipped to max
        # Note: -1.0 * 32767 = -32767, not -32768
        assert result_int[1] == -32767  # Clipped to min (symmetric)

    def test_roundtrip(self):
        """Test conversion roundtrip."""
        original = np.array([0.5, -0.5, 0.0], dtype=np.float32)
        pcm16 = float_to_pcm16_np(original)
        back = pcm16_to_float_np(pcm16)

        np.testing.assert_array_almost_equal(original, back, decimal=4)


class TestCalculateRMSNP:
    """Tests for calculate_rms_np."""

    def test_empty_input(self):
        """Test with empty input."""
        result = calculate_rms_np(b"")
        assert result == 0.0

    def test_silence(self):
        """Test with silence."""
        samples = np.zeros(100, dtype=np.int16)
        result = calculate_rms_np(samples.tobytes())

        assert result == 0.0

    def test_full_scale(self):
        """Test with full scale signal."""
        # DC signal at max
        samples = np.full(100, 32767, dtype=np.int16)
        result = calculate_rms_np(samples.tobytes())

        assert result == pytest.approx(1.0, rel=1e-4)

    def test_sine_wave(self):
        """Test with sine wave."""
        # Sine wave RMS should be peak / sqrt(2)
        t = np.linspace(0, 2 * np.pi, 1000)
        sine = (np.sin(t) * 32767).astype(np.int16)
        result = calculate_rms_np(sine.tobytes())

        expected = 1.0 / np.sqrt(2)
        assert result == pytest.approx(expected, rel=0.01)


class TestCalculateRMSFromArray:
    """Tests for calculate_rms_from_array."""

    def test_empty_input(self):
        """Test with empty input."""
        result = calculate_rms_from_array(np.array([]))
        assert result == 0.0

    def test_int16_input(self):
        """Test with int16 input."""
        samples = np.full(100, 32767, dtype=np.int16)
        result = calculate_rms_from_array(samples)

        assert result == pytest.approx(1.0, rel=1e-4)

    def test_float_input(self):
        """Test with float input."""
        samples = np.array([0.5, 0.5, 0.5], dtype=np.float32)
        result = calculate_rms_from_array(samples)

        assert result == pytest.approx(0.5, rel=1e-6)


class TestCalculateDBNP:
    """Tests for calculate_db_np."""

    def test_silence(self):
        """Test with silence."""
        samples = np.zeros(100, dtype=np.int16)
        result = calculate_db_np(samples.tobytes())

        assert result == float('-inf')

    def test_full_scale(self):
        """Test with full scale signal."""
        samples = np.full(100, 32767, dtype=np.int16)
        result = calculate_db_np(samples.tobytes())

        # Full scale = 0 dB
        assert result == pytest.approx(0.0, abs=0.1)


class TestResampleAudioNP:
    """Tests for resample_audio_np."""

    def test_same_rate(self):
        """Test with same sample rate."""
        samples = np.array([1, 2, 3, 4, 5], dtype=np.int16)
        result = resample_audio_np(samples.tobytes(), 16000, 16000)

        np.testing.assert_array_equal(
            np.frombuffer(result, dtype=np.int16),
            samples
        )

    def test_empty_input(self):
        """Test with empty input."""
        result = resample_audio_np(b"", 16000, 8000)
        assert result == b""

    def test_downsample(self):
        """Test downsampling."""
        # 10 samples at 20kHz -> ~5 samples at 10kHz
        samples = np.arange(10, dtype=np.int16)
        result = resample_audio_np(samples.tobytes(), 20000, 10000)

        result_arr = np.frombuffer(result, dtype=np.int16)
        assert len(result_arr) == 5

    def test_upsample(self):
        """Test upsampling."""
        # 5 samples at 8kHz -> 10 samples at 16kHz
        samples = np.arange(5, dtype=np.int16)
        result = resample_audio_np(samples.tobytes(), 8000, 16000)

        result_arr = np.frombuffer(result, dtype=np.int16)
        assert len(result_arr) == 10


class TestMixAudioNP:
    """Tests for mix_audio_np."""

    def test_empty_first(self):
        """Test with empty first input."""
        samples = np.array([1, 2, 3], dtype=np.int16)
        result = mix_audio_np(b"", samples.tobytes())

        np.testing.assert_array_equal(
            np.frombuffer(result, dtype=np.int16),
            samples
        )

    def test_empty_second(self):
        """Test with empty second input."""
        samples = np.array([1, 2, 3], dtype=np.int16)
        result = mix_audio_np(samples.tobytes(), b"")

        np.testing.assert_array_equal(
            np.frombuffer(result, dtype=np.int16),
            samples
        )

    def test_equal_mix(self):
        """Test equal mix."""
        samples1 = np.array([1000, 2000], dtype=np.int16)
        samples2 = np.array([1000, 2000], dtype=np.int16)

        result = mix_audio_np(samples1.tobytes(), samples2.tobytes())
        result_arr = np.frombuffer(result, dtype=np.int16)

        # Sum should be double
        np.testing.assert_array_equal(result_arr, [2000, 4000])

    def test_weighted_mix(self):
        """Test weighted mix."""
        samples1 = np.array([1000], dtype=np.int16)
        samples2 = np.array([1000], dtype=np.int16)

        result = mix_audio_np(
            samples1.tobytes(),
            samples2.tobytes(),
            weight1=0.5,
            weight2=0.5
        )
        result_arr = np.frombuffer(result, dtype=np.int16)

        assert result_arr[0] == 1000  # 500 + 500

    def test_clipping(self):
        """Test that mixing clips properly."""
        samples1 = np.array([30000], dtype=np.int16)
        samples2 = np.array([30000], dtype=np.int16)

        result = mix_audio_np(samples1.tobytes(), samples2.tobytes())
        result_arr = np.frombuffer(result, dtype=np.int16)

        # Should be clipped to max
        assert result_arr[0] == 32767


class TestApplyGainNP:
    """Tests for apply_gain_np."""

    def test_zero_gain(self):
        """Test with 0 dB gain."""
        samples = np.array([1000, 2000], dtype=np.int16)
        result = apply_gain_np(samples.tobytes(), 0.0)

        np.testing.assert_array_equal(
            np.frombuffer(result, dtype=np.int16),
            samples
        )

    def test_empty_input(self):
        """Test with empty input."""
        result = apply_gain_np(b"", 6.0)
        assert result == b""

    def test_positive_gain(self):
        """Test positive gain (louder)."""
        samples = np.array([1000], dtype=np.int16)
        result = apply_gain_np(samples.tobytes(), 6.0)  # ~2x

        result_arr = np.frombuffer(result, dtype=np.int16)
        assert result_arr[0] > 1000

    def test_negative_gain(self):
        """Test negative gain (quieter)."""
        samples = np.array([1000], dtype=np.int16)
        result = apply_gain_np(samples.tobytes(), -6.0)  # ~0.5x

        result_arr = np.frombuffer(result, dtype=np.int16)
        assert result_arr[0] < 1000


class TestNormalizeAudioNP:
    """Tests for normalize_audio_np."""

    def test_empty_input(self):
        """Test with empty input."""
        result = normalize_audio_np(b"")
        assert result == b""

    def test_silence(self):
        """Test with silence."""
        samples = np.zeros(100, dtype=np.int16)
        result = normalize_audio_np(samples.tobytes())

        # Should return unchanged
        np.testing.assert_array_equal(
            np.frombuffer(result, dtype=np.int16),
            samples
        )

    def test_normalization(self):
        """Test that audio is normalized."""
        samples = np.array([100, 200, 100], dtype=np.int16)
        result = normalize_audio_np(samples.tobytes(), target_db=-3.0)

        result_arr = np.frombuffer(result, dtype=np.int16)

        # Peak should be at target level
        peak = np.max(np.abs(result_arr))
        expected_peak = 32768 * (10 ** (-3.0 / 20))
        assert peak == pytest.approx(expected_peak, rel=0.01)


# =============================================================================
# Performance Tests (marked for benchmarking)
# =============================================================================


class TestPerformance:
    """Performance comparison tests."""

    def test_ring_buffer_append_works(self):
        """Test that RingBuffer append works correctly (smoke test).

        Note: This is NOT a benchmark. RingBuffer's main advantage is
        zero-copy views and pre-allocated memory, not raw append speed.
        Deque append of bytes is extremely fast but requires copying
        on read via b"".join().
        """
        import time

        n_iterations = 1000
        chunk_size = 320  # 20ms at 16kHz

        # RingBuffer
        ring = RingBuffer(sample_rate=16000, max_duration_seconds=5.0)
        chunk = np.random.randint(-32768, 32767, chunk_size, dtype=np.int16)

        start = time.perf_counter()
        for _ in range(n_iterations):
            ring.append(chunk)
        ring_time = time.perf_counter() - start

        # Just verify it completed in reasonable time (< 1 second)
        assert ring_time < 1.0

        # Verify data integrity
        assert ring.count > 0
        view = ring.get_view()
        assert len(view) > 0

    def test_numpy_conversion_vs_python(self):
        """Compare numpy conversion vs pure Python."""
        import time
        from voice_pipeline.utils.audio import pcm16_to_float, float_to_pcm16

        n_samples = 16000  # 1 second at 16kHz
        samples_np = np.random.randint(-32768, 32767, n_samples, dtype=np.int16)
        audio_bytes = samples_np.tobytes()

        # Numpy version
        start = time.perf_counter()
        result_np = pcm16_to_float_np(audio_bytes)
        _ = float_to_pcm16_np(result_np)
        numpy_time = time.perf_counter() - start

        # Python version
        start = time.perf_counter()
        result_py = pcm16_to_float(audio_bytes)
        _ = float_to_pcm16(result_py)
        python_time = time.perf_counter() - start

        # Numpy should be significantly faster
        assert numpy_time < python_time

    def test_buffer_pool_reuses_buffers(self):
        """Test that buffer pool reuses buffers (smoke test).

        Note: The main advantage of BufferPool is memory reuse, not raw speed.
        Small buffers may not show speed improvements due to numpy's
        efficient allocation. The benefit is more visible with larger
        buffers or in memory-constrained environments.
        """
        import time

        n_iterations = 100
        chunk_size = 320

        # With pool
        pool = BufferPool(chunk_size=chunk_size, pool_size=10)

        start = time.perf_counter()
        for _ in range(n_iterations):
            buf = pool.acquire()
            buf[0] = 1  # Use buffer
            pool.release(buf)
        pool_time = time.perf_counter() - start

        # Just verify it completed in reasonable time
        assert pool_time < 1.0

        # Verify pool is reusing buffers (not allocating new ones)
        assert pool.total_allocated == 10  # No new allocations
        assert pool.available == 10  # All returned to pool
