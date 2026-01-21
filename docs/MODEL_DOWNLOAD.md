# Model Download Guide

## ⚠️ Important Notice

**AI model files are NOT versioned in this repository.**

### Why?

Binary model files (100MB - 3GB) should never be committed to git because:
- ❌ Bloats repository size
- ❌ Slows down cloning
- ❌ Git can't diff binary files efficiently
- ❌ Makes history unnecessarily large

### Historical Note

In commit `71e5719`, the Whisper model (`ggml-base.bin`, 142MB) was accidentally committed.
This was corrected in commit `0b09468` by:
- Removing the file from tracking
- Adding proper `.gitignore` rules
- Creating an automatic download script

**If you cloned before `0b09468`**: The binary is in your local history but won't affect you.
**If you clone after `0b09468`**: You won't download the binary at all.

---

## 📥 How to Download Models

### Quick Start (Recommended)

```bash
./scripts/download_models.sh
```

This downloads all required models automatically.

---

### Manual Download

#### Whisper ASR

```bash
mkdir -p models/whisper

# Download with wget
wget https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin \
     -O models/whisper/ggml-base.bin

# Or with curl
curl -L https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin \
     -o models/whisper/ggml-base.bin
```

**Model Size:** 142 MB
**Language:** Multilingual (Portuguese, English, Spanish, etc.)

---

### Alternative Whisper Models

| Model | Size | Speed | Accuracy |
|-------|------|-------|----------|
| `ggml-tiny.bin` | 75 MB | ⚡⚡⚡ Fastest | ⭐⭐ Basic |
| `ggml-base.bin` | 142 MB | ⚡⚡ Fast | ⭐⭐⭐ Good |
| `ggml-small.bin` | 466 MB | ⚡ Medium | ⭐⭐⭐⭐ Better |
| `ggml-medium.bin` | 1.5 GB | 🐌 Slow | ⭐⭐⭐⭐⭐ Excellent |
| `ggml-large-v3.bin` | 3.1 GB | 🐌🐌 Very Slow | ⭐⭐⭐⭐⭐ Best |

**To use a different model**, update `config/default.yaml`:

```yaml
ai:
  asr_model: openai/whisper-small  # For documentation
  asr_model_path: models/whisper/ggml-small.bin
```

---

## 🤖 Other Models (Auto-Downloaded)

### Qwen2.5 LLM

- **Model:** `Qwen/Qwen2.5-1.5B-Instruct`
- **Size:** ~3 GB
- **Downloaded by:** `transformers` library on first run
- **Cache:** `~/.cache/huggingface/hub/`

### Kokoro TTS

- **Voice:** `pf_dora` (Brazilian Portuguese, Female)
- **Size:** ~500 MB
- **Downloaded by:** `kokoro` library on first run
- **Cache:** `~/.cache/kokoro/`

**Total disk space needed:** ~4.5 GB

---

## 🔧 Troubleshooting

### Error: Model file not found

```
FileNotFoundError: models/whisper/ggml-base.bin
```

**Solution:**
```bash
./scripts/download_models.sh
```

### Error: Download fails

```bash
# Check internet connection
ping huggingface.co

# Try with curl instead of wget
curl -L https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin \
     -o models/whisper/ggml-base.bin
```

### Error: Insufficient disk space

```bash
# Check available space
df -h .

# Required: ~4.5 GB total
```

---

## 📚 References

- **Whisper.cpp:** https://github.com/ggerganov/whisper.cpp
- **Qwen2.5:** https://huggingface.co/Qwen
- **Kokoro TTS:** https://github.com/hexgrad/kokoro
- **HuggingFace Models:** https://huggingface.co/models
