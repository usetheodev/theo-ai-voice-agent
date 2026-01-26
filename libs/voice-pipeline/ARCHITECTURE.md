# Architecture

## Overview

Voice Pipeline is organized in layers, from low-level interfaces to high-level agents:

```
┌─────────────────────────────────────────────┐
│                  Agents                      │
│  (VoiceAgent, VoiceAgentBuilder)            │
├─────────────────────────────────────────────┤
│                  Chains                      │
│  (VoiceChain, StreamingVoiceChain,          │
│   ConversationChain)                         │
├─────────────────────────────────────────────┤
│              Streaming Layer                 │
│  (SentenceStreamer, StreamingStrategy,       │
│   ClauseStrategy, Metrics)                   │
├─────────────────────────────────────────────┤
│               Providers                      │
│  (ASR, LLM, TTS, VAD — via Registry)       │
├─────────────────────────────────────────────┤
│              Interfaces                      │
│  (ASRInterface, LLMInterface, TTSInterface, │
│   VADInterface, Warmable)                    │
├─────────────────────────────────────────────┤
│            Runnable (Base)                   │
│  (VoiceRunnable, VoiceSequence, pipe |)     │
└─────────────────────────────────────────────┘
```

## Decision Tree: Which Component to Use

| Use Case | Component |
|----------|-----------|
| Simple audio → text → audio | `VoiceChain` |
| Multi-turn conversation | `ConversationChain` |
| Low-latency streaming | `StreamingVoiceChain` |
| Agent with tools & memory | `VoiceAgent` |
| Custom pipeline | `VoiceRunnable` pipe (`\|`) |
| Quick prototyping | `VoiceAgent.local()` |

## Streaming Pipeline

The `StreamingVoiceChain` uses a producer-consumer pattern for minimal latency:

```
Audio Input
    │
    ▼
┌────────┐
│  ASR   │  (batch or streaming)
└───┬────┘
    │ text
    ▼
┌────────┐
│  LLM   │  streaming tokens
└───┬────┘
    │ tokens
    ▼
┌──────────────────┐
│ Streaming Strategy│  (sentence / clause / word)
│ + SentenceStreamer │
└───┬──────────────┘
    │ text chunks
    ▼
┌────────────────┐
│ asyncio.Queue  │  producer-consumer bridge
└───┬────────────┘
    │
    ▼
┌────────┐
│  TTS   │  streaming audio chunks
└───┬────┘
    │ AudioChunk
    ▼
Audio Output
```

### Streaming Strategies

- **SentenceStreamingStrategy**: Buffers until sentence boundaries (`.!?`). Best for natural speech.
- **ClauseStreamingStrategy**: Buffers until clause boundaries (`,;:—` or conjunctions). Lower latency.
- **WordStreamingStrategy**: Emits every N words. Lowest latency but less natural.

## Provider Registry

Providers are registered using decorators:

```python
@register_tts(
    name="my-tts",
    capabilities=TTSCapabilities(streaming=True, languages=["en"]),
)
class MyTTSProvider(BaseProvider, TTSInterface):
    ...
```

The registry enables:
- Discovery: `get_registry().list_tts()`
- Creation by name: `get_registry().get_tts("my-tts", voice="default")`
- Capability queries: Check what a provider supports before using it

## Callback System

The callback system uses `contextvars` for zero-overhead when not in use:

```python
from voice_pipeline.callbacks import RunContext, run_with_callbacks

class MyHandler(VoiceCallbackHandler):
    async def on_llm_token(self, token: str, **kwargs):
        print(token, end="", flush=True)

async with run_with_callbacks([MyHandler()]):
    result = await chain.ainvoke(audio)
```

Key callbacks: `on_asr_start/end`, `on_llm_start/end/token`, `on_tts_start/end/chunk`.

## Turn-Taking

Turn-taking determines when the user has finished speaking:

- **FixedSilenceTurnTaking**: Fixed silence threshold (simple, reliable).
- **AdaptiveSilenceTurnTaking**: Adjusts threshold based on context (utterance length, conversation state).

## Interruption Strategies

Controls how the system handles user speech during agent output:

- **ImmediateInterruption**: Stop immediately on any speech.
- **GracefulInterruption**: Finish current sentence, then stop.
- **BackchannelAwareInterruption**: Distinguish backchannels ("uh-huh") from real interruptions.
