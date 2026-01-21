# AI Models Directory

This directory contains AI models required for the AI Voice Agent.

**⚠️ Models are NOT versioned in git** (they are large binary files).

---

## 📥 How to Download Models

### Option 1: Automatic Download (Recommended)

Run the download script from the project root:

```bash
./scripts/download_models.sh
```

This will download all required models automatically.

---

### Option 2: Manual Download

#### Whisper ASR Model

**Model:** `ggml-base.bin` (142 MB)
**Location:** `models/whisper/ggml-base.bin`
**URL:** https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin

```bash
# Create directory
mkdir -p models/whisper

# Download with wget
wget https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin \
     -O models/whisper/ggml-base.bin

# Or with curl
curl -L https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin \
     -o models/whisper/ggml-base.bin
```

**Other Whisper models available:**
- `ggml-tiny.bin` (75 MB) - Fastest, less accurate
- `ggml-small.bin` (466 MB) - Good balance
- `ggml-medium.bin` (1.5 GB) - Better accuracy
- `ggml-large-v3.bin` (3.1 GB) - Best accuracy

To use a different model, update `config/default.yaml`:
```yaml
ai:
  asr_model_path: models/whisper/ggml-small.bin
```

---

## 📁 Directory Structure

```
models/
├── README.md           # This file
├── whisper/            # Whisper ASR models
│   └── ggml-base.bin   # 142 MB (download required)
├── llm/                # LLM models (downloaded by transformers)
└── tts/                # TTS models (downloaded by kokoro)
```

---

## 🔒 Why Models Are Not in Git

AI model files are:
- **Large** (100MB - 3GB+) → Bloats git history
- **Binary** → Git can't diff them efficiently
- **Frequently updated** → New versions released often
- **Not source code** → Better hosted on model hubs

**Solution:** Download on-demand from HuggingFace.

---

## 🤖 LLM Models (Auto-Downloaded)

The Qwen2.5 LLM models are automatically downloaded by the `transformers` library on first run:

- **Model:** `Qwen/Qwen2.5-1.5B-Instruct` (3 GB)
- **Cache:** `~/.cache/huggingface/hub/`

No manual download needed!

---

## 🎤 TTS Models (Auto-Downloaded)

Kokoro TTS models are automatically downloaded by the `kokoro` library on first run:

- **Voice:** `pf_dora` (Brazilian Portuguese, Female)
- **Cache:** `~/.cache/kokoro/`

No manual download needed!

---

## 🆘 Troubleshooting

### Model download fails

```bash
# Check internet connection
ping huggingface.co

# Try manual download with curl
curl -L https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin \
     -o models/whisper/ggml-base.bin
```

### Model not found error

```
FileNotFoundError: models/whisper/ggml-base.bin
```

**Solution:** Run `./scripts/download_models.sh`

### Insufficient disk space

Check available space:
```bash
df -h .
```

Required space:
- Whisper: 142 MB
- Qwen LLM: ~3 GB
- Kokoro TTS: ~500 MB
- **Total: ~4 GB**

---

## 📚 Model Sources

- **Whisper:** https://github.com/ggerganov/whisper.cpp
- **Qwen2.5:** https://huggingface.co/Qwen
- **Kokoro:** https://github.com/hexgrad/kokoro
