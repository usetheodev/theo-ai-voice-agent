#!/bin/bash
set -e

echo "========================================"
echo "  🤖 Starting AI Voice Agent"
echo "========================================"
echo ""
echo "Configuration:"
echo "  - RTP Port: ${RTP_PORT:-5080}"
echo "  - Whisper Model: ${WHISPER_MODEL:-base}"
echo "  - LLM Model: ${LLM_MODEL:-phi-3-mini}"
echo "  - TTS Voice: ${TTS_VOICE:-pt_BR-faber-medium}"
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

# LLM (Phi-3-mini)
LLM_PATH="/app/models/llm/${LLM_MODEL}.gguf"
if [ ! -f "$LLM_PATH" ]; then
    echo "📥 Downloading LLM model: ${LLM_MODEL}..."
    mkdir -p /app/models/llm
    if [ "${LLM_MODEL}" = "phi-3-mini" ]; then
        wget -q --show-progress \
            -O "$LLM_PATH" \
            "https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf/resolve/main/Phi-3-mini-4k-instruct-q4.gguf"
    fi
    echo "✅ LLM model downloaded"
else
    echo "✅ LLM model already exists"
fi

# TTS (Piper)
TTS_ONNX="/app/models/tts/${TTS_VOICE}.onnx"
TTS_JSON="/app/models/tts/${TTS_VOICE}.onnx.json"
if [ ! -f "$TTS_ONNX" ]; then
    echo "📥 Downloading TTS model: ${TTS_VOICE}..."
    mkdir -p /app/models/tts
    wget -q --show-progress \
        -O "$TTS_ONNX" \
        "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx"
    wget -q --show-progress \
        -O "$TTS_JSON" \
        "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx.json"
    echo "✅ TTS model downloaded"
else
    echo "✅ TTS model already exists"
fi

echo ""
echo "All models ready!"
echo ""
echo "========================================"
echo "  Starting application..."
echo "========================================"
echo ""

# Execute application
exec "$@"
