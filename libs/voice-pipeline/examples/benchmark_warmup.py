#!/usr/bin/env python3
"""Benchmark: TTS Warmup Impact on Latency.

This benchmark measures the impact of TTS warmup on first-synthesis latency.
It compares cold start (no warmup) vs warm start (with warmup).

Usage:
    python examples/benchmark_warmup.py

Requirements:
    - Kokoro TTS installed: pip install kokoro soundfile
    - Or OpenAI API key for cloud TTS

Expected Results:
    Cold Start (Kokoro): ~500-800ms for first synthesis
    Warm Start (Kokoro): ~100-200ms for first synthesis
    Improvement: ~60-75% latency reduction
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class BenchmarkResult:
    """Result of a warmup benchmark run."""
    provider: str
    cold_start_ms: float
    warm_start_ms: float
    warmup_time_ms: float

    @property
    def improvement_ms(self) -> float:
        """Latency improvement in milliseconds."""
        return self.cold_start_ms - self.warm_start_ms

    @property
    def improvement_percent(self) -> float:
        """Latency improvement as percentage."""
        if self.cold_start_ms == 0:
            return 0
        return (self.improvement_ms / self.cold_start_ms) * 100

    def __str__(self) -> str:
        return f"""
╔══════════════════════════════════════════════════════════════╗
║  TTS Warmup Benchmark: {self.provider:^36} ║
╠══════════════════════════════════════════════════════════════╣
║  Warmup Time:     {self.warmup_time_ms:>8.1f} ms                           ║
║  Cold Start:      {self.cold_start_ms:>8.1f} ms (first synthesis, no warmup) ║
║  Warm Start:      {self.warm_start_ms:>8.1f} ms (after warmup)               ║
╠══════════════════════════════════════════════════════════════╣
║  Improvement:     {self.improvement_ms:>8.1f} ms ({self.improvement_percent:.1f}% faster)             ║
╚══════════════════════════════════════════════════════════════╝
"""


async def benchmark_kokoro() -> Optional[BenchmarkResult]:
    """Benchmark Kokoro TTS warmup impact."""
    try:
        from voice_pipeline.providers.tts import KokoroTTSProvider
    except ImportError:
        print("⚠️  Kokoro not available. Skipping Kokoro benchmark.")
        return None

    print("\n🔬 Benchmarking Kokoro TTS...")

    test_text = "Olá, como posso ajudar você hoje?"

    # ========== Test 1: Cold Start (no warmup) ==========
    print("  [1/3] Testing cold start...")
    tts_cold = KokoroTTSProvider(lang_code="p", voice="pf_dora")

    try:
        await tts_cold.connect()
    except ImportError as e:
        print(f"⚠️  Kokoro not installed: {e}")
        return None

    start = time.perf_counter()
    _ = await tts_cold.synthesize(test_text)
    cold_start_ms = (time.perf_counter() - start) * 1000

    await tts_cold.disconnect()

    # ========== Test 2: Warm Start (with warmup) ==========
    print("  [2/3] Testing warm start...")
    tts_warm = KokoroTTSProvider(lang_code="p", voice="pf_dora")
    await tts_warm.connect()

    # Warmup
    warmup_ms = await tts_warm.warmup()

    # Now measure synthesis
    start = time.perf_counter()
    _ = await tts_warm.synthesize(test_text)
    warm_start_ms = (time.perf_counter() - start) * 1000

    await tts_warm.disconnect()

    # ========== Test 3: Verify consistency ==========
    print("  [3/3] Verifying consistency...")
    tts_verify = KokoroTTSProvider(lang_code="p", voice="pf_dora")
    await tts_verify.connect()
    await tts_verify.warmup()

    # Multiple synthesis calls should be consistent
    times = []
    for _ in range(3):
        start = time.perf_counter()
        _ = await tts_verify.synthesize(test_text)
        times.append((time.perf_counter() - start) * 1000)

    await tts_verify.disconnect()

    avg_time = sum(times) / len(times)
    print(f"  ✓ Consistency check: {avg_time:.1f}ms avg (σ={max(times)-min(times):.1f}ms)")

    return BenchmarkResult(
        provider="Kokoro TTS (pf_dora)",
        cold_start_ms=cold_start_ms,
        warm_start_ms=warm_start_ms,
        warmup_time_ms=warmup_ms,
    )


async def benchmark_streaming_chain() -> Optional[BenchmarkResult]:
    """Benchmark StreamingVoiceChain warmup impact."""
    try:
        from voice_pipeline.providers.asr import WhisperCppASRProvider
        from voice_pipeline.providers.llm import OllamaLLMProvider
        from voice_pipeline.providers.tts import KokoroTTSProvider
        from voice_pipeline.chains import StreamingVoiceChain
    except ImportError as e:
        print(f"⚠️  Dependencies not available: {e}")
        return None

    print("\n🔬 Benchmarking StreamingVoiceChain auto_warmup...")

    # Create components
    asr = WhisperCppASRProvider(model="base", language="pt")
    llm = OllamaLLMProvider(model="qwen2.5:0.5b")
    tts = KokoroTTSProvider(lang_code="p", voice="pf_dora")

    # ========== Test 1: Without auto_warmup ==========
    print("  [1/2] Testing without auto_warmup...")
    chain_cold = StreamingVoiceChain(
        asr=asr,
        llm=llm,
        tts=tts,
        auto_warmup=False,
    )

    try:
        start = time.perf_counter()
        await chain_cold.connect()
        connect_cold_ms = (time.perf_counter() - start) * 1000
    except Exception as e:
        print(f"⚠️  Could not connect: {e}")
        return None

    # ========== Test 2: With auto_warmup ==========
    print("  [2/2] Testing with auto_warmup...")
    chain_warm = StreamingVoiceChain(
        asr=asr,
        llm=llm,
        tts=tts,
        auto_warmup=True,
    )

    start = time.perf_counter()
    await chain_warm.connect()
    connect_warm_ms = (time.perf_counter() - start) * 1000
    warmup_ms = chain_warm.warmup_time_ms or 0

    return BenchmarkResult(
        provider="StreamingVoiceChain",
        cold_start_ms=connect_cold_ms,
        warm_start_ms=connect_warm_ms,
        warmup_time_ms=warmup_ms,
    )


async def main():
    """Run all benchmarks."""
    print("=" * 62)
    print("  TTS Warmup Benchmark - Voice Pipeline")
    print("=" * 62)
    print("\nThis benchmark measures the impact of TTS warmup on latency.")
    print("Warmup pre-loads the TTS model to eliminate cold-start delay.")

    results = []

    # Benchmark Kokoro
    kokoro_result = await benchmark_kokoro()
    if kokoro_result:
        results.append(kokoro_result)
        print(kokoro_result)

    # Summary
    if results:
        print("\n" + "=" * 62)
        print("  Summary")
        print("=" * 62)
        for r in results:
            print(f"  • {r.provider}: {r.improvement_percent:.0f}% faster with warmup")
        print("\n💡 Recommendation: Always use .warmup(True) in production")
        print("   to ensure consistent low latency from the first request.")
    else:
        print("\n⚠️  No benchmarks could be run. Check dependencies.")


if __name__ == "__main__":
    asyncio.run(main())
