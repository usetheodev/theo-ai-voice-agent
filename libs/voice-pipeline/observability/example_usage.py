"""
Example: send synthetic voice pipeline telemetry to the observability stack.

Usage:
    1. Start the stack:
       cd observability && docker compose up -d

    2. Install dependencies:
       pip install voice-pipeline[observability]

    3. Run this script:
       python observability/example_usage.py

    4. Open the dashboards:
       - Grafana:  http://localhost:3030  (admin/admin)
       - Jaeger:   http://localhost:16686
       - Prometheus: http://localhost:9090

    The script simulates voice pipeline turns in a loop, generating
    realistic traces and metrics that populate the Grafana dashboard.
"""

import asyncio
import random
import time
import uuid

from voice_pipeline.callbacks.base import RunContext
from voice_pipeline.callbacks.handlers.tracing import OpenTelemetryHandler
from voice_pipeline.interfaces import AudioChunk, TranscriptionResult, VADEvent
from voice_pipeline.telemetry import setup_telemetry


async def simulate_turn(handler: OpenTelemetryHandler, ctx: RunContext) -> None:
    """Simulate a single conversation turn with realistic timings."""

    await handler.on_turn_start(ctx)

    # --- VAD ---
    vad_confidence = random.uniform(0.8, 1.0)
    await handler.on_vad_speech_start(
        ctx, VADEvent(is_speech=True, confidence=vad_confidence)
    )
    await asyncio.sleep(random.uniform(0.3, 1.5))  # speech duration
    await handler.on_vad_speech_end(
        ctx, VADEvent(is_speech=False, confidence=vad_confidence * 0.95)
    )

    # --- ASR ---
    audio_bytes = random.randint(16000, 96000)
    await handler.on_asr_start(ctx, b"\x00" * audio_bytes)
    await asyncio.sleep(random.uniform(0.05, 0.3))  # ASR processing
    await handler.on_asr_end(
        ctx,
        TranscriptionResult(
            text="Olá, como posso te ajudar?",
            is_final=True,
            confidence=random.uniform(0.85, 0.99),
            language="pt-BR",
        ),
    )

    # --- LLM ---
    messages = [
        {"role": "system", "content": "Você é um assistente de voz."},
        {"role": "user", "content": "Olá, como posso te ajudar?"},
    ]
    await handler.on_llm_start(ctx, messages)

    # Simulate streaming tokens with TTFT
    await asyncio.sleep(random.uniform(0.03, 0.15))  # time to first token

    response_tokens = random.randint(10, 50)
    response_text = ""
    for i in range(response_tokens):
        token = f"token_{i} "
        response_text += token
        await handler.on_llm_token(ctx, token)
        await asyncio.sleep(random.uniform(0.01, 0.04))  # inter-token delay

    await handler.on_llm_end(ctx, response_text.strip())

    # --- TTS ---
    await handler.on_tts_start(ctx, response_text.strip())

    # Simulate streaming audio chunks with TTFA
    await asyncio.sleep(random.uniform(0.02, 0.1))  # time to first audio

    num_chunks = random.randint(5, 20)
    for _ in range(num_chunks):
        chunk_size = random.randint(480, 4800)
        await handler.on_tts_chunk(
            ctx,
            AudioChunk(
                data=b"\x00" * chunk_size,
                sample_rate=24000,
            ),
        )
        await asyncio.sleep(random.uniform(0.01, 0.03))

    await handler.on_tts_end(ctx)

    # Occasional barge-in
    if random.random() < 0.15:
        await handler.on_barge_in(ctx)

    await handler.on_turn_end(ctx)


async def main():
    # Setup telemetry pointing at the local OTel Collector
    providers = setup_telemetry(
        service_name="voice-pipeline-demo",
        service_version="0.1.0",
        otlp_endpoint="http://localhost:4317",
    )

    handler = OpenTelemetryHandler(
        tracer_provider=providers["tracer_provider"],
        meter_provider=providers["meter_provider"],
        session_id=str(uuid.uuid4()),
        provider_info={
            "asr": {"name": "deepgram", "model": "nova-2", "is_streaming": True},
            "llm": {"name": "openai", "model": "gpt-4o", "temperature": "0.7"},
            "tts": {
                "name": "elevenlabs",
                "model": "eleven_turbo_v2",
                "voice": "rachel",
            },
        },
    )

    print("Sending telemetry to http://localhost:4317 ...")
    print("Grafana:    http://localhost:3030  (admin/admin)")
    print("Jaeger:     http://localhost:16686")
    print("Prometheus: http://localhost:9090")
    print()

    cycle = 0
    while True:
        cycle += 1
        ctx = RunContext(
            run_id=str(uuid.uuid4()),
            run_name="voice-pipeline-demo",
        )

        await handler.on_pipeline_start(ctx)

        turns = random.randint(1, 4)
        for t in range(turns):
            await simulate_turn(handler, ctx)

        # Occasional error
        if random.random() < 0.05:
            await handler.on_pipeline_error(ctx, RuntimeError("Simulated error"))
        else:
            await handler.on_pipeline_end(ctx)

        print(f"  cycle {cycle}: {turns} turn(s) sent")

        await asyncio.sleep(random.uniform(1.0, 3.0))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
