"""OpenAI Realtime API Example.

This example demonstrates how to use the OpenAI Realtime API
for real-time voice conversations.

Requirements:
    pip install voice-pipeline
    pip install websockets

    Set OPENAI_API_KEY environment variable

Usage:
    export OPENAI_API_KEY=your_api_key
    python openai_realtime.py
"""

import asyncio
import os
from typing import AsyncIterator

from voice_pipeline import (
    PipelineBuilder,
)
from voice_pipeline.interfaces.realtime import (
    RealtimeInterface,
    RealtimeEvent,
    RealtimeEventType,
    RealtimeSessionConfig,
)


def get_api_key() -> str:
    """Get OpenAI API key from environment."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable not set")
    return api_key


async def realtime_conversation_example():
    """Example of real-time voice conversation with OpenAI."""
    print("OpenAI Realtime API Example")
    print("=" * 60)

    api_key = get_api_key()

    # Import OpenAI Realtime provider
    from voice_pipeline.providers.realtime_openai import OpenAIRealtimeProvider

    # Create realtime provider
    realtime = OpenAIRealtimeProvider(
        api_key=api_key,
        model="gpt-4o-realtime-preview",
        voice="alloy",  # Options: alloy, echo, shimmer
    )

    # Configure session
    config = RealtimeSessionConfig(
        instructions="You are a helpful voice assistant. Keep responses brief and conversational.",
        voice="alloy",
        input_audio_format="pcm16",
        output_audio_format="pcm16",
        enable_turn_detection=True,
        turn_detection_threshold=0.5,
        turn_detection_silence_duration_ms=500,
    )

    print("\nConnecting to OpenAI Realtime API...")

    try:
        # Connect
        await realtime.connect()
        print("Connected!")

        # Configure session
        await realtime.configure(config)
        print("Session configured!")

        # Simulate audio input
        async def audio_input() -> AsyncIterator[bytes]:
            """Generate simulated audio input."""
            # In a real application, this would come from a microphone
            for _ in range(50):  # 1 second of audio (50 x 20ms chunks)
                yield b"\x00\x00" * 320  # 20ms at 16kHz
                await asyncio.sleep(0.02)

        print("\nSending audio...")

        # Process audio
        async for event in realtime.process(audio_input()):
            if event.type == RealtimeEventType.TRANSCRIPT:
                print(f"[Transcript] {event.data.get('text', '')}")
            elif event.type == RealtimeEventType.AUDIO:
                audio_data = event.data.get("audio", b"")
                print(f"[Audio] Received {len(audio_data)} bytes")
            elif event.type == RealtimeEventType.RESPONSE_START:
                print("[Response] Starting...")
            elif event.type == RealtimeEventType.RESPONSE_END:
                print("[Response] Complete")
            elif event.type == RealtimeEventType.ERROR:
                print(f"[Error] {event.data.get('message', 'Unknown error')}")

    finally:
        # Disconnect
        await realtime.disconnect()
        print("\nDisconnected")


async def realtime_with_builder():
    """Create realtime pipeline with builder pattern."""
    api_key = get_api_key()

    from voice_pipeline.providers.realtime_openai import OpenAIRealtimeProvider

    # Use builder
    builder = (
        PipelineBuilder()
        .with_config(
            system_prompt="You are a helpful voice assistant.",
        )
        .with_realtime(
            OpenAIRealtimeProvider,
            api_key=api_key,
            voice="alloy",
        )
    )

    # Get realtime instance
    realtime = builder._realtime_instance or builder._build_provider(builder._realtime)

    print("\nRealtime provider created with builder!")
    print(f"Provider type: {type(realtime).__name__}")


async def main():
    """Main example entry point."""
    print("OpenAI Realtime API Examples")
    print("=" * 60)

    # Check API key
    try:
        get_api_key()
        print("API Key: Found")
    except ValueError as e:
        print(f"API Key: {e}")
        print("\nSet your API key:")
        print("  export OPENAI_API_KEY=your_api_key")
        return

    print("\nAvailable examples:")
    print("  1. realtime_conversation_example() - Full conversation flow")
    print("  2. realtime_with_builder() - Builder pattern example")

    print("\nTo run the full example, uncomment the appropriate line below.")

    # Uncomment to run:
    # await realtime_conversation_example()
    # await realtime_with_builder()


if __name__ == "__main__":
    asyncio.run(main())
