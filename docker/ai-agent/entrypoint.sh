#!/bin/bash
set -e

echo "========================================"
echo "  🤖 Starting AI Voice Agent"
echo "========================================"
echo ""
echo "Configuration:"
echo "  - RTP Port: ${RTP_PORT:-5080}"
echo "  - Whisper Model: ${WHISPER_MODEL:-base}"
echo "  - LLM Model: ${LLM_MODEL:-qwen2.5-3b-instruct}"
echo "  - TTS Voice: ${TTS_VOICE:-pf_dora} (Kokoro-82M)"
echo "  - Log Level: ${LOG_LEVEL:-INFO}"
echo ""

# Download models if they don't exist
echo "Checking AI models..."

# Whisper
WHISPER_PATH="/app/models/whisper/ggml-${WHISPER_MODEL}.bin"
if [ ! -f "$WHISPER_PATH" ]; then
    echo "📥 Downloading Whisper model: ${WHISPER_MODEL}..."
    mkdir -p /app/models/whisper
    wget -q --show-progress \
        -O "$WHISPER_PATH" \
        "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-${WHISPER_MODEL}.bin"
    echo "✅ Whisper model downloaded"
else
    echo "✅ Whisper model already exists"
fi

# LLM - Support for multiple models
LLM_MODEL_NAME="${LLM_MODEL:-qwen2.5-3b-instruct}"
if [ "${LLM_MODEL_NAME}" = "qwen2.5-3b-instruct" ]; then
    LLM_PATH="/app/models/llm/qwen2.5-3b-instruct-q4_k_m.gguf"
else
    LLM_PATH="/app/models/llm/${LLM_MODEL_NAME}.gguf"
fi

if [ ! -f "$LLM_PATH" ]; then
    echo "📥 Downloading LLM model: ${LLM_MODEL_NAME}..."
    mkdir -p /app/models/llm

    if [ "${LLM_MODEL_NAME}" = "qwen2.5-3b-instruct" ]; then
        echo "   Model: Qwen2.5-3B-Instruct (Q4_K_M quantization)"
        echo "   Size: ~2.3GB - Best for Portuguese voice agents"
        wget -q --show-progress \
            -O "$LLM_PATH" \
            "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf"
    elif [ "${LLM_MODEL_NAME}" = "phi-3-mini" ]; then
        wget -q --show-progress \
            -O "$LLM_PATH" \
            "https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf/resolve/main/Phi-3-mini-4k-instruct-q4.gguf"
    fi
    echo "✅ LLM model downloaded"
else
    echo "✅ LLM model already exists: $(basename $LLM_PATH)"
fi

# TTS (Kokoro-82M)
# Kokoro downloads models automatically on first use via Python API
# No manual download needed - models are cached in HuggingFace cache
echo "✅ TTS (Kokoro-82M) - Models will be downloaded automatically on first use"

echo ""
echo "All models ready!"
echo ""
echo "========================================"
echo "  Starting application..."
echo "========================================"
echo ""

# Execute application
exec "$@"
