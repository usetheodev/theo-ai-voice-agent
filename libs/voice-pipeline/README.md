# Voice Pipeline

A modular, streaming voice conversation pipeline for building voice agents.

## Features

- **Streaming at every stage**: VAD → ASR → LLM → TTS
- **Barge-in support**: User can interrupt the assistant
- **Sentence-level streaming**: Start TTS before LLM finishes
- **Provider-agnostic interfaces**: Plug in any ASR, LLM, TTS, VAD
- **Event-driven architecture**: Monitor every stage of the pipeline
- **State machine**: Clear conversation flow management

## Installation

```bash
pip install voice-pipeline
```

## Quick Start

```python
import asyncio
from voice_pipeline import Pipeline, PipelineConfig

# Implement the interfaces for your providers
from my_providers import MyASR, MyLLM, MyTTS, MyVAD

async def main():
    # Create pipeline
    pipeline = Pipeline(
        config=PipelineConfig(
            system_prompt="You are a helpful voice assistant.",
            language="en",
        ),
        asr=MyASR(),
        llm=MyLLM(),
        tts=MyTTS(),
        vad=MyVAD(),
    )

    # Register event handlers
    pipeline.on(PipelineEventType.TRANSCRIPTION, lambda e: print(f"User: {e.data['text']}"))
    pipeline.on(PipelineEventType.LLM_RESPONSE, lambda e: print(f"Assistant: {e.data['text']}"))

    # Process audio
    async for audio_chunk in pipeline.process(audio_input_stream):
        play_audio(audio_chunk)

asyncio.run(main())
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Voice Pipeline                         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Audio In → [VAD] → [ASR] → [LLM] → [TTS] → Audio Out      │
│               │        │       │       │                    │
│               ▼        ▼       ▼       ▼                    │
│            Events   Events  Events  Events                  │
│                                                             │
│  State Machine: IDLE → LISTENING → PROCESSING → SPEAKING   │
│                   ↑                                ↓        │
│                   └────────── (barge-in) ─────────┘        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Implementing Providers

Each provider must implement its interface:

### ASR (Speech-to-Text)

```python
from voice_pipeline import ASRInterface, TranscriptionResult

class MyASR(ASRInterface):
    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        language: Optional[str] = None,
    ) -> AsyncIterator[TranscriptionResult]:
        yield TranscriptionResult(text="Hello", is_final=True)
```

### LLM (Language Model)

```python
from voice_pipeline import LLMInterface, LLMChunk

class MyLLM(LLMInterface):
    async def generate_stream(
        self,
        messages: list[dict],
        system_prompt: Optional[str] = None,
        **kwargs,
    ) -> AsyncIterator[LLMChunk]:
        yield LLMChunk(text="Hello!")
```

### TTS (Text-to-Speech)

```python
from voice_pipeline import TTSInterface, AudioChunk

class MyTTS(TTSInterface):
    async def synthesize_stream(
        self,
        text_stream: AsyncIterator[str],
        voice: Optional[str] = None,
    ) -> AsyncIterator[AudioChunk]:
        yield AudioChunk(data=audio_bytes, sample_rate=24000)
```

### VAD (Voice Activity Detection)

```python
from voice_pipeline import VADInterface, VADEvent

class MyVAD(VADInterface):
    async def process(
        self,
        audio_chunk: bytes,
        sample_rate: int,
    ) -> VADEvent:
        return VADEvent(is_speech=True, confidence=0.95)
```

## License

MIT
