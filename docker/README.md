# voice-base

Base Docker image for voice AI pipeline services including speech recognition, text-to-speech, and VoIP capabilities.

## Features

- **ASR (Speech-to-Text)**: Faster-Whisper with pre-downloaded models
- **TTS (Text-to-Speech)**: Kokoro and gTTS engines
- **VoIP**: PJSIP 2.14 compiled with Python bindings
- **Embeddings**: Sentence-transformers (E5 multilingual)
- **LLM Integration**: Anthropic and OpenAI SDKs
- **VAD**: WebRTC Voice Activity Detection
- **Monitoring**: Prometheus metrics support

## Pre-loaded Models

| Model | Purpose | Size |
|-------|---------|------|
| Whisper (configurable) | Speech Recognition | tiny/small/medium |
| Kokoro | Text-to-Speech | ~100MB |
| E5 multilingual | Sentence Embeddings | ~500MB |

## Usage

```dockerfile
FROM paulohenriquevn/voice-base:latest

COPY your-app/ /app/
CMD ["python", "your-app.py"]
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `PJSIP_INSTALLED` | Set to 1 when PJSIP is available |
| `HF_HOME` | Hugging Face cache directory |
| `TORCH_HOME` | PyTorch cache directory |

## Build Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `WHISPER_MODEL` | tiny | Whisper model size (tiny/small/medium/large) |

## Tags

- `latest` - Latest stable with Whisper tiny
- `whisper-small` - With Whisper small model
- `whisper-medium` - With Whisper medium model

## Build

```bash
# Build with default settings (Whisper tiny)
./docker/build-base.sh

# Build with different Whisper model
./docker/build-base.sh --model small
./docker/build-base.sh --model medium

# Build without cache
./docker/build-base.sh --no-cache

# Build and push to registry
./docker/build-base.sh --push
```

## Cache Volumes

The build uses Docker volumes for persistent caching:

| Volume | Purpose |
|--------|---------|
| `voice-pip-cache` | Python packages |
| `voice-apt-cache` | System packages |
| `voice-model-cache` | ML models (Whisper, Kokoro) |

## Source

GitHub: [theo-ai-voice-agent](https://github.com/paulohenriquevn/ai-voice-agent)

## License

MIT
