"""Local Providers Example.

This example demonstrates how to create a voice pipeline
using local providers (Whisper, Ollama, Kokoro, Silero).

Requirements:
    pip install voice-pipeline
    pip install openai-whisper  # or faster-whisper
    pip install ollama
    pip install kokoro-onnx
    pip install torch

    # Start Ollama server:
    ollama serve

Usage:
    python local_providers.py
"""

import asyncio
from typing import AsyncIterator

from voice_pipeline import (
    PipelineBuilder,
    PipelineEventType,
)


def create_local_pipeline():
    """Create a pipeline with local providers.

    This uses:
    - Whisper for ASR (speech-to-text)
    - Ollama for LLM (text generation)
    - Kokoro for TTS (text-to-speech)
    - Silero for VAD (voice activity detection)
    """
    from voice_pipeline.providers.asr_whisper import WhisperASR
    from voice_pipeline.providers.llm_ollama import OllamaLLM
    from voice_pipeline.providers.tts_kokoro import KokoroTTS
    from voice_pipeline.providers.vad_silero import SileroVAD

    return (
        PipelineBuilder()
        .with_config(
            system_prompt="You are a helpful voice assistant.",
            language="en",
        )
        .with_asr(WhisperASR, model="base")  # Options: tiny, base, small, medium, large
        .with_llm(OllamaLLM, model="llama3")  # Use any model available in Ollama
        .with_tts(KokoroTTS, voice="af_bella")  # Kokoro voice
        .with_vad(SileroVAD)  # Silero VAD
        .build()
    )


def create_chain_only():
    """Create a simple ASR | LLM | TTS chain without VAD."""
    from voice_pipeline.providers.asr_whisper import WhisperASR
    from voice_pipeline.providers.llm_ollama import OllamaLLM
    from voice_pipeline.providers.tts_kokoro import KokoroTTS

    return (
        PipelineBuilder()
        .with_asr(WhisperASR, model="base")
        .with_llm(OllamaLLM, model="llama3")
        .with_tts(KokoroTTS, voice="af_bella")
        .build_chain()
    )


async def process_audio_file(audio_path: str):
    """Process an audio file through the chain."""
    import wave

    # Read audio file
    with wave.open(audio_path, "rb") as wf:
        audio_data = wf.readframes(wf.getnframes())

    print(f"Processing {audio_path}...")

    # Create chain
    chain = create_chain_only()

    # Process audio
    result = await chain.ainvoke(audio_data)

    print(f"Generated audio output: {len(result)} bytes")

    # Save output
    output_path = audio_path.replace(".wav", "_response.wav")
    with wave.open(output_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)  # Kokoro outputs 24kHz
        wf.writeframes(result)

    print(f"Saved response to: {output_path}")


async def streaming_example():
    """Example of streaming audio through the chain."""
    from voice_pipeline.providers.asr_whisper import WhisperASR
    from voice_pipeline.providers.llm_ollama import OllamaLLM
    from voice_pipeline.providers.tts_kokoro import KokoroTTS

    chain = (
        PipelineBuilder()
        .with_asr(WhisperASR, model="base")
        .with_llm(OllamaLLM, model="llama3")
        .with_tts(KokoroTTS, voice="af_bella")
        .build_chain()
    )

    # Simulate audio input
    audio_input = b"\x00\x00" * 16000 * 2  # 2 seconds of silence

    print("Streaming audio output...")
    async for audio_chunk in chain.astream(audio_input):
        print(f"  Received audio chunk: {len(audio_chunk)} bytes")


async def main():
    """Main example entry point."""
    print("Local Providers Example")
    print("=" * 60)

    print("\nChecking provider availability...")

    # Check Ollama
    try:
        import ollama
        models = ollama.list()
        print(f"  Ollama: OK ({len(models.get('models', []))} models available)")
    except Exception as e:
        print(f"  Ollama: NOT AVAILABLE ({e})")

    # Check Whisper
    try:
        import whisper
        print("  Whisper: OK")
    except ImportError:
        print("  Whisper: NOT INSTALLED (pip install openai-whisper)")

    # Check Kokoro
    try:
        import kokoro_onnx
        print("  Kokoro: OK")
    except ImportError:
        print("  Kokoro: NOT INSTALLED (pip install kokoro-onnx)")

    print("\n" + "=" * 60)

    # Run streaming example
    # await streaming_example()

    print("\nTo process an audio file, run:")
    print("  python local_providers.py path/to/audio.wav")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        # Process audio file
        asyncio.run(process_audio_file(sys.argv[1]))
    else:
        # Run main example
        asyncio.run(main())
