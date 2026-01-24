"""Basic Voice Pipeline Example.

This example demonstrates how to create and run a voice pipeline
using the builder pattern.

Requirements:
    pip install voice-pipeline
    # For local providers:
    pip install whisper kokoro ollama

Usage:
    python basic_pipeline.py
"""

import asyncio
from typing import AsyncIterator

from voice_pipeline import (
    Pipeline,
    PipelineBuilder,
    PipelineConfig,
    PipelineEventType,
    ASRInterface,
    LLMInterface,
    TTSInterface,
    VADInterface,
    TranscriptionResult,
    LLMChunk,
    AudioChunk,
    VADEvent,
    SpeechState,
)


# ==============================================================================
# Example Mock Providers (for demonstration)
# ==============================================================================


class DemoASR(ASRInterface):
    """Demo ASR that simulates transcription."""

    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        language: str | None = None,
    ) -> AsyncIterator[TranscriptionResult]:
        # Consume audio stream
        async for _ in audio_stream:
            pass

        # Simulate transcription result
        yield TranscriptionResult(
            text="Hello, how are you today?",
            is_final=True,
            confidence=0.95,
            language=language,
        )


class DemoLLM(LLMInterface):
    """Demo LLM that generates responses."""

    async def generate_stream(
        self,
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs,
    ) -> AsyncIterator[LLMChunk]:
        response = "I'm doing great, thank you for asking! How can I help you?"

        # Stream word by word
        words = response.split()
        for i, word in enumerate(words):
            text = word + (" " if i < len(words) - 1 else "")
            yield LLMChunk(text=text)
            await asyncio.sleep(0.05)  # Simulate generation time


class DemoTTS(TTSInterface):
    """Demo TTS that generates audio."""

    async def synthesize_stream(
        self,
        text_stream: AsyncIterator[str],
        voice: str | None = None,
        speed: float = 1.0,
        **kwargs,
    ) -> AsyncIterator[AudioChunk]:
        async for text in text_stream:
            # Generate fake audio (silence for demo)
            audio_data = b"\x00\x00" * len(text) * 100
            yield AudioChunk(data=audio_data, sample_rate=16000)


class DemoVAD(VADInterface):
    """Demo VAD that simulates speech detection."""

    def __init__(self):
        self._frame_count = 0

    async def process(
        self,
        audio_chunk: bytes,
        sample_rate: int,
    ) -> VADEvent:
        self._frame_count += 1
        # Simulate speech for first 10 frames
        is_speech = self._frame_count <= 10
        return VADEvent(
            is_speech=is_speech,
            confidence=0.9 if is_speech else 0.1,
            state=SpeechState.SPEECH if is_speech else SpeechState.SILENCE,
        )

    def reset(self) -> None:
        self._frame_count = 0


# ==============================================================================
# Pipeline Example
# ==============================================================================


def create_pipeline() -> Pipeline:
    """Create a voice pipeline with demo providers."""
    return (
        PipelineBuilder()
        .with_config(
            system_prompt="You are a helpful voice assistant.",
            language="en",
            enable_barge_in=True,
        )
        .with_asr(DemoASR())
        .with_llm(DemoLLM())
        .with_tts(DemoTTS())
        .with_vad(DemoVAD())
        .build()
    )


async def run_pipeline_example():
    """Run the voice pipeline with simulated audio input."""
    print("=" * 60)
    print("Voice Pipeline Example")
    print("=" * 60)

    # Create pipeline
    pipeline = create_pipeline()

    # Register event handlers
    pipeline.on(PipelineEventType.PIPELINE_START, lambda e: print("[Pipeline] Started"))
    pipeline.on(PipelineEventType.VAD_SPEECH_START, lambda e: print("[VAD] Speech detected"))
    pipeline.on(PipelineEventType.VAD_SPEECH_END, lambda e: print("[VAD] Speech ended"))
    pipeline.on(PipelineEventType.TRANSCRIPTION, lambda e: print(f"[ASR] Transcription: {e.data['text']}"))
    pipeline.on(PipelineEventType.LLM_CHUNK, lambda e: print(f"[LLM] Chunk: {e.data['text']}", end=""))
    pipeline.on(PipelineEventType.LLM_COMPLETE, lambda e: print("\n[LLM] Response complete"))
    pipeline.on(PipelineEventType.TTS_CHUNK, lambda e: print("[TTS] Audio chunk generated"))
    pipeline.on(PipelineEventType.PIPELINE_STOP, lambda e: print("[Pipeline] Stopped"))

    # Simulate audio input
    async def audio_input_generator() -> AsyncIterator[bytes]:
        """Generate fake audio chunks (silence)."""
        for _ in range(20):  # 20 chunks
            yield b"\x00\x00" * 320  # 20ms of silence at 16kHz
            await asyncio.sleep(0.02)

    print("\nProcessing audio input...")
    print("-" * 40)

    # Process audio
    output_chunks = []
    try:
        async for audio_chunk in pipeline.process(audio_input_generator()):
            output_chunks.append(audio_chunk)
    except asyncio.TimeoutError:
        pass

    print("-" * 40)
    print(f"\nGenerated {len(output_chunks)} audio output chunks")

    # Show metrics
    metrics = pipeline.get_metrics()
    print(f"\nMetrics:")
    print(f"  - Total latency: {metrics.total_latency_ms:.2f}ms")
    print(f"  - ASR latency: {metrics.asr_latency_ms:.2f}ms")
    print(f"  - LLM TTFT: {metrics.llm_ttft_ms:.2f}ms")
    print(f"  - TTS TTFA: {metrics.tts_ttfa_ms:.2f}ms")

    print("=" * 60)


# ==============================================================================
# Chain Example (Simple ASR | LLM | TTS)
# ==============================================================================


async def run_chain_example():
    """Run a simple chain without full pipeline (no VAD)."""
    print("\n" + "=" * 60)
    print("Voice Chain Example (ASR | LLM | TTS)")
    print("=" * 60)

    # Build chain
    chain = (
        PipelineBuilder()
        .with_asr(DemoASR())
        .with_llm(DemoLLM())
        .with_tts(DemoTTS())
        .build_chain()
    )

    # Process audio
    audio_input = b"\x00\x00" * 16000  # 1 second of silence

    print("\nProcessing audio through chain...")
    result = await chain.ainvoke(audio_input)

    if result:
        print(f"Generated audio output: {len(result)} bytes")

    print("=" * 60)


# ==============================================================================
# Main
# ==============================================================================


if __name__ == "__main__":
    print("\nVoice Pipeline Examples")
    print("=" * 60)

    # Run examples
    # asyncio.run(run_pipeline_example())  # Full pipeline example (requires async processing)
    asyncio.run(run_chain_example())  # Simple chain example
