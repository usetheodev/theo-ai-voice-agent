# Voice Pipeline Examples

This directory contains examples demonstrating how to use the voice-pipeline library.

## Examples

### 1. Basic Pipeline (`basic_pipeline.py`)

Demonstrates the core concepts:
- Creating a pipeline with `PipelineBuilder`
- Using mock providers for testing
- Event handling
- Pipeline metrics

```bash
python basic_pipeline.py
```

### 2. Local Providers (`local_providers.py`)

Shows how to use local providers for offline processing:
- **Whisper** for ASR (speech-to-text)
- **Ollama** for LLM (text generation)
- **Kokoro** for TTS (text-to-speech)
- **Silero** for VAD (voice activity detection)

```bash
# Install dependencies
pip install openai-whisper ollama kokoro-onnx torch

# Start Ollama
ollama serve

# Run example
python local_providers.py
```

### 3. OpenAI Realtime (`openai_realtime.py`)

Demonstrates the OpenAI Realtime API for real-time voice conversations:

```bash
# Set API key
export OPENAI_API_KEY=your_api_key

# Run example
python openai_realtime.py
```

## Quick Start

```python
from voice_pipeline import PipelineBuilder

# Create a simple chain
chain = (
    PipelineBuilder()
    .with_asr(MyASR())
    .with_llm(MyLLM())
    .with_tts(MyTTS())
    .build_chain()
)

# Process audio
result = await chain.ainvoke(audio_bytes)

# Or stream output
async for chunk in chain.astream(audio_bytes):
    play(chunk)
```

## Full Pipeline with VAD

```python
from voice_pipeline import PipelineBuilder

# Create full pipeline
pipeline = (
    PipelineBuilder()
    .with_config(
        system_prompt="You are a helpful assistant.",
        language="en",
    )
    .with_asr(MyASR())
    .with_llm(MyLLM())
    .with_tts(MyTTS())
    .with_vad(MyVAD())
    .build()
)

# Process audio stream
async for audio_out in pipeline.process(audio_input_stream):
    play(audio_out)
```

## Provider Options

| Component | Options |
|-----------|---------|
| ASR | WhisperASR, OpenAI Whisper API |
| LLM | OllamaLLM, OpenAI, Anthropic |
| TTS | KokoroTTS, OpenAITTS |
| VAD | SileroVAD, WebRTCVAD |
| Realtime | OpenAIRealtimeProvider |
