# Voice Pipeline

A modular, streaming voice conversation framework for building voice AI agents in Python.

Inspired by LangChain's composability patterns (LCEL), Voice Pipeline provides a `VoiceRunnable` base that lets you compose ASR, LLM, TTS, and VAD components with the `|` operator.

## Features

- **Builder pattern**: Configure agents fluently with `VoiceAgent.builder()`
- **LCEL composition**: Pipe components with `asr | llm | tts`
- **Streaming at every stage**: VAD → ASR → LLM → TTS with minimal latency
- **Provider registry**: Plug-and-play providers registered by name
- **Built-in providers**: Faster-Whisper, Deepgram, Ollama, Kokoro, Piper, Silero, WebRTC, and more
- **Turn-taking strategies**: Fixed, adaptive, and semantic end-of-turn detection
- **Interruption handling**: Immediate, graceful, and backchannel-aware modes
- **Streaming granularity**: Word, sentence, clause, and adaptive chunking
- **Conversation memory**: Buffer, window, summary, and summary-buffer strategies
- **Barge-in support**: User can interrupt the assistant mid-speech
- **State machine**: `IDLE → LISTENING → PROCESSING → SPEAKING` with full-duplex support
- **Event-driven**: Monitor every pipeline stage via events
- **Multi-agent**: LangGraph-style graphs, supervisors, teams, and handoffs
- **MCP support**: Model Context Protocol for tool integration

## Installation

```bash
pip install voice-pipeline

# With specific provider dependencies
pip install voice-pipeline[faster-whisper]   # FasterWhisper ASR
pip install voice-pipeline[qwen3-tts]        # Qwen3-TTS
```

## Quick Start

### Builder Pattern (recommended)

```python
import asyncio
from voice_pipeline import VoiceAgent

async def main():
    agent = (
        VoiceAgent.builder()
        .asr("faster-whisper", model="base", language="en", compute_type="int8")
        .llm("ollama", model="llama3.2:1b")
        .tts("kokoro")
        .streaming(True)
        .build()
    )

    # Process audio
    async for audio_chunk in agent.chain.astream(audio_bytes):
        play(audio_chunk)

asyncio.run(main())
```

### LCEL Composition

```python
from voice_pipeline import WhisperASR, OllamaLLM, KokoroTTS

# Compose with pipe operator
chain = WhisperASR(model="base") | OllamaLLM(model="llama3.2:1b") | KokoroTTS()

# Invoke
result = await chain.ainvoke(audio_bytes)

# Stream
async for chunk in chain.astream(audio_bytes):
    play(chunk)
```

### Full-Featured Agent

```python
agent = await (
    VoiceAgent.builder()
    .asr("faster-whisper", model="base", language="pt",
         compute_type="int8", vad_filter=True, beam_size=1)
    .llm("ollama", model="llama3.2:1b", keep_alive="-1")
    .tts("kokoro", voice="af_bella")
    .vad("silero")
    .turn_taking("adaptive", base_threshold_ms=600)
    .streaming_granularity("adaptive",
        first_chunk_words=3, clause_min_chars=10, language="pt")
    .interruption("backchannel", language="pt")
    .system_prompt("You are a helpful voice assistant.")
    .streaming(True)
    .build_async()
)
```

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        Voice Pipeline                            │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Audio In → [VAD] → [ASR] → [LLM] → [TTS] → Audio Out           │
│               │        │       │       │                         │
│               ▼        ▼       ▼       ▼                         │
│            Events   Events  Events  Events                       │
│                                                                  │
│  State Machine: IDLE → LISTENING → PROCESSING → SPEAKING         │
│                   ↑                                ↓             │
│                   └────────── (barge-in) ─────────┘             │
│                                                                  │
│  Strategies:                                                     │
│    Turn-Taking: fixed | adaptive | semantic                      │
│    Streaming:   word | sentence | clause | adaptive              │
│    Interruption: immediate | graceful | backchannel              │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

## Built-in Providers

| Type | Provider | Name | Description |
|------|----------|------|-------------|
| ASR  | Faster-Whisper | `faster-whisper` | CTranslate2, 4x faster, CPU optimized |
| ASR  | whisper.cpp | `whispercpp` | Local, GPU support |
| ASR  | Deepgram | `deepgram` | Real-time streaming via WebSocket |
| LLM  | Ollama | `ollama` | Local LLM inference |
| LLM  | HuggingFace | `huggingface` | HuggingFace Inference API |
| TTS  | Kokoro | `kokoro` | Fast local TTS, multi-language |
| TTS  | Piper | `piper` | Lightweight local TTS |
| TTS  | Qwen3-TTS | `qwen3-tts` | Voice cloning, multi-language |
| VAD  | Silero | `silero` | Fast PyTorch VAD, < 1ms on CPU |
| VAD  | WebRTC | `webrtc` | Lightweight, simple |

```python
# List all registered providers
from voice_pipeline import get_registry
registry = get_registry()
print(registry.list_providers())
# {'asr': ['whispercpp', 'deepgram', 'faster-whisper'],
#  'llm': ['ollama', 'huggingface'],
#  'tts': ['kokoro', 'piper', 'qwen3-tts'],
#  'vad': ['silero', 'webrtc']}
```

## Chains

| Chain | Use Case |
|-------|----------|
| `VoiceChain` | Basic ASR → LLM → TTS |
| `StreamingVoiceChain` | Low-latency streaming with strategies |
| `ConversationChain` | Multi-turn with memory and state machine |
| `ParallelStreamingChain` | Parallel LLM + TTS processing |

All chains inherit from `BaseVoiceChain` which provides shared behavior (message history, config creation, `ainvoke`, `reset`).

## Strategies

### Turn-Taking

Controls when the system decides the user has finished speaking.

```python
builder.turn_taking("fixed", silence_threshold_ms=800)
builder.turn_taking("adaptive", base_threshold_ms=600)
builder.turn_taking("semantic")  # Uses LLM to detect turn completion
```

### Streaming Granularity

Controls how LLM output is chunked for TTS.

```python
builder.streaming_granularity("word")
builder.streaming_granularity("sentence")
builder.streaming_granularity("adaptive",
    first_chunk_words=3, clause_min_chars=10, language="en")
```

### Interruption

Controls how the system handles user interruptions.

```python
builder.interruption("immediate")   # Stop immediately
builder.interruption("graceful")    # Finish current sentence
builder.interruption("backchannel", language="en")  # Ignore "uh-huh"
```

## Conversation Memory

```python
from voice_pipeline import ConversationBufferMemory, ConversationWindowMemory

# Keep all messages
agent = (
    VoiceAgent.builder()
    .asr("faster-whisper").llm("ollama").tts("kokoro")
    .memory(ConversationBufferMemory())
    .build()
)

# Keep last N turns
agent = (
    VoiceAgent.builder()
    .asr("faster-whisper").llm("ollama").tts("kokoro")
    .memory(ConversationWindowMemory(k=10))
    .build()
)
```

## Custom Providers

Register your own providers with decorators:

```python
from voice_pipeline import register_asr, ASRCapabilities, ASRInterface

@register_asr(
    name="my-asr",
    capabilities=ASRCapabilities(streaming=True, languages=["en", "pt"]),
)
class MyASR(ASRInterface):
    async def transcribe_stream(self, audio_stream, language=None):
        async for chunk in audio_stream:
            yield TranscriptionResult(text="...", is_final=True)
```

Or register manually:

```python
from voice_pipeline import get_registry

registry = get_registry()
registry.register_asr(
    name="my-asr",
    provider_class=MyASR,
    capabilities=ASRCapabilities(streaming=True),
)
```

## Implementing Provider Interfaces

### ASR (Speech-to-Text)

```python
from voice_pipeline import ASRInterface, TranscriptionResult

class MyASR(ASRInterface):
    async def transcribe_stream(self, audio_stream, language=None):
        async for chunk in audio_stream:
            yield TranscriptionResult(text="Hello", is_final=True)
```

### LLM (Language Model)

```python
from voice_pipeline import LLMInterface, LLMChunk

class MyLLM(LLMInterface):
    async def generate_stream(self, messages, system_prompt=None, **kwargs):
        yield LLMChunk(text="Hello!")
```

### TTS (Text-to-Speech)

```python
from voice_pipeline import TTSInterface, AudioChunk

class MyTTS(TTSInterface):
    async def synthesize_stream(self, text_stream, voice=None):
        yield AudioChunk(data=audio_bytes, sample_rate=24000)
```

### VAD (Voice Activity Detection)

```python
from voice_pipeline import VADInterface, VADEvent

class MyVAD(VADInterface):
    async def process(self, audio_chunk, sample_rate):
        return VADEvent(is_speech=True, confidence=0.95)
```

## Web Demo

A full-featured web demo is included in `examples/webapp/`:

```bash
cd examples/webapp
pip install -r requirements.txt
./run.sh
# Open http://localhost:8000
```

Environment variables for configuration:

```bash
export VP_LLM_MODEL="llama3.2:1b"
export VP_TTS_PROVIDER="kokoro"
export VP_TTS_VOICE="af_bella"
export VP_LANGUAGE="en"
export VP_SYSTEM_PROMPT="You are a helpful assistant."
```

## License

MIT
