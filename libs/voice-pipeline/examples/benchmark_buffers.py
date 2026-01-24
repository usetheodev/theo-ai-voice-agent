"""Benchmark: Optimized Buffers vs Standard Buffers.

Compares performance of optimized numpy-based buffers against
standard Python implementations.

Usage:
    python examples/benchmark_buffers.py
"""

import time
from collections import deque
from typing import Callable

import numpy as np

from voice_pipeline.streaming.optimized_buffer import (
    RingBuffer,
    BufferPool,
    pcm16_to_float_np,
    float_to_pcm16_np,
    calculate_rms_np,
)
from voice_pipeline.streaming.buffer import AudioBuffer
from voice_pipeline.utils.audio import (
    pcm16_to_float,
    float_to_pcm16,
    calculate_rms,
)


def benchmark(name: str, func: Callable, n_iterations: int = 1000) -> float:
    """Run benchmark and return time in milliseconds."""
    start = time.perf_counter()
    for _ in range(n_iterations):
        func()
    elapsed_ms = (time.perf_counter() - start) * 1000
    return elapsed_ms


def format_speedup(baseline: float, optimized: float) -> str:
    """Format speedup ratio."""
    if optimized == 0:
        return "∞x faster"
    ratio = baseline / optimized
    if ratio >= 1:
        return f"{ratio:.1f}x faster"
    else:
        return f"{1/ratio:.1f}x slower"


def main():
    print("=" * 70)
    print("Voice Pipeline - Buffer Performance Benchmark")
    print("=" * 70)
    print()

    # Test data
    chunk_size = 320  # 20ms at 16kHz
    n_chunks = 1000
    n_samples = 16000  # 1 second at 16kHz

    audio_chunk = np.random.randint(-32768, 32767, chunk_size, dtype=np.int16)
    audio_bytes = audio_chunk.tobytes()
    audio_1sec = np.random.randint(-32768, 32767, n_samples, dtype=np.int16)
    audio_1sec_bytes = audio_1sec.tobytes()

    # =========================================================================
    # 1. Buffer Append Comparison
    # =========================================================================
    print("[1] Buffer Append Performance")
    print("-" * 50)

    # RingBuffer (optimized)
    ring = RingBuffer(sample_rate=16000, max_duration_seconds=5.0)
    ring_time = benchmark(
        "RingBuffer.append",
        lambda: ring.append(audio_chunk),
        n_chunks
    )
    ring.clear()

    # AudioBuffer (standard)
    audio_buf = AudioBuffer(sample_rate=16000, max_duration_seconds=5.0)
    audiobuf_time = benchmark(
        "AudioBuffer.append",
        lambda: audio_buf.append(audio_bytes),
        n_chunks
    )
    audio_buf.clear()

    # Deque with bytes (baseline)
    d: deque = deque(maxlen=250)
    deque_time = benchmark(
        "deque.append (bytes)",
        lambda: d.append(audio_bytes),
        n_chunks
    )

    print(f"  RingBuffer.append:      {ring_time:.2f}ms ({n_chunks} iterations)")
    print(f"  AudioBuffer.append:     {audiobuf_time:.2f}ms ({n_chunks} iterations)")
    print(f"  deque.append (bytes):   {deque_time:.2f}ms ({n_chunks} iterations)")
    print()

    # =========================================================================
    # 2. Buffer Read Comparison
    # =========================================================================
    print("[2] Buffer Read Performance")
    print("-" * 50)

    # Fill buffers
    for _ in range(100):
        ring.append(audio_chunk)
        audio_buf.append(audio_bytes)
        d.append(audio_bytes)

    # RingBuffer get_view (zero-copy when possible)
    ring_read_time = benchmark(
        "RingBuffer.get_view",
        lambda: ring.get_view(),
        n_chunks
    )

    # AudioBuffer peek_all (requires join)
    audiobuf_read_time = benchmark(
        "AudioBuffer.peek_all",
        lambda: audio_buf.peek_all(),
        n_chunks
    )

    # Deque join (always copies)
    deque_read_time = benchmark(
        "b''.join(deque)",
        lambda: b"".join(d),
        n_chunks
    )

    print(f"  RingBuffer.get_view:    {ring_read_time:.2f}ms ({n_chunks} iterations)")
    print(f"  AudioBuffer.peek_all:   {audiobuf_read_time:.2f}ms ({n_chunks} iterations)")
    print(f"  b''.join(deque):        {deque_read_time:.2f}ms ({n_chunks} iterations)")
    print(f"    → get_view vs peek_all: {format_speedup(audiobuf_read_time, ring_read_time)}")
    print()

    # =========================================================================
    # 3. PCM16 ↔ Float Conversion
    # =========================================================================
    print("[3] PCM16 ↔ Float Conversion (1 second of audio)")
    print("-" * 50)

    # Numpy version
    np_to_float_time = benchmark(
        "pcm16_to_float_np",
        lambda: pcm16_to_float_np(audio_1sec_bytes),
        100
    )

    # Python version
    py_to_float_time = benchmark(
        "pcm16_to_float (Python)",
        lambda: pcm16_to_float(audio_1sec_bytes),
        100
    )

    print(f"  pcm16_to_float_np:      {np_to_float_time:.2f}ms (100 iterations)")
    print(f"  pcm16_to_float (Python):{py_to_float_time:.2f}ms (100 iterations)")
    print(f"    → Numpy speedup: {format_speedup(py_to_float_time, np_to_float_time)}")
    print()

    # Float to PCM16
    float_samples_np = pcm16_to_float_np(audio_1sec_bytes)
    float_samples_py = pcm16_to_float(audio_1sec_bytes)

    np_to_pcm_time = benchmark(
        "float_to_pcm16_np",
        lambda: float_to_pcm16_np(float_samples_np),
        100
    )

    py_to_pcm_time = benchmark(
        "float_to_pcm16 (Python)",
        lambda: float_to_pcm16(float_samples_py),
        100
    )

    print(f"  float_to_pcm16_np:      {np_to_pcm_time:.2f}ms (100 iterations)")
    print(f"  float_to_pcm16 (Python):{py_to_pcm_time:.2f}ms (100 iterations)")
    print(f"    → Numpy speedup: {format_speedup(py_to_pcm_time, np_to_pcm_time)}")
    print()

    # =========================================================================
    # 4. RMS Calculation
    # =========================================================================
    print("[4] RMS Calculation (1 second of audio)")
    print("-" * 50)

    np_rms_time = benchmark(
        "calculate_rms_np",
        lambda: calculate_rms_np(audio_1sec_bytes),
        100
    )

    py_rms_time = benchmark(
        "calculate_rms (Python)",
        lambda: calculate_rms(audio_1sec_bytes),
        100
    )

    print(f"  calculate_rms_np:       {np_rms_time:.2f}ms (100 iterations)")
    print(f"  calculate_rms (Python): {py_rms_time:.2f}ms (100 iterations)")
    print(f"    → Numpy speedup: {format_speedup(py_rms_time, np_rms_time)}")
    print()

    # =========================================================================
    # 5. Buffer Pool
    # =========================================================================
    print("[5] Buffer Pool vs New Allocation")
    print("-" * 50)

    pool = BufferPool(chunk_size=chunk_size, pool_size=10)

    # With pool
    def with_pool():
        buf = pool.acquire()
        buf[0] = 1
        pool.release(buf)

    pool_time = benchmark("BufferPool.acquire/release", with_pool, n_chunks)

    # Without pool
    def without_pool():
        buf = np.zeros(chunk_size, dtype=np.int16)
        buf[0] = 1

    no_pool_time = benchmark("np.zeros (new alloc)", without_pool, n_chunks)

    print(f"  BufferPool:             {pool_time:.2f}ms ({n_chunks} iterations)")
    print(f"  np.zeros (new alloc):   {no_pool_time:.2f}ms ({n_chunks} iterations)")
    print(f"  Pool allocations:       {pool.total_allocated} (reused)")
    print()

    # =========================================================================
    # Summary
    # =========================================================================
    print("=" * 70)
    print("SUMMARY - Recommended Usage")
    print("=" * 70)
    print()
    print("  ✓ RingBuffer: Use for continuous audio streaming")
    print("    - Pre-allocated memory, no allocation during streaming")
    print("    - Zero-copy views when data is contiguous")
    print("    - Thread-safe for producer-consumer patterns")
    print()
    print("  ✓ BufferPool: Use for chunk processing pipelines")
    print("    - Reuses buffers to reduce GC pressure")
    print("    - Best with context manager for automatic release")
    print()
    print("  ✓ pcm16_to_float_np / float_to_pcm16_np:")
    print(f"    - {format_speedup(py_to_float_time, np_to_float_time)} than Python version")
    print("    - Use for all audio format conversions")
    print()
    print("  ✓ calculate_rms_np:")
    print(f"    - {format_speedup(py_rms_time, np_rms_time)} than Python version")
    print("    - Use for VAD energy detection")
    print()


if __name__ == "__main__":
    main()
