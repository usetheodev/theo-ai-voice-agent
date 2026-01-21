#!/bin/bash
#
# Download AI Models Script
# Downloads required models for AI Voice Agent
#

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}🤖 AI Voice Agent - Model Download Script${NC}"
echo "=============================================="
echo ""

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
MODELS_DIR="$PROJECT_ROOT/models"

# Create models directory structure
echo -e "${YELLOW}📁 Creating models directory structure...${NC}"
mkdir -p "$MODELS_DIR/whisper"
mkdir -p "$MODELS_DIR/llm"
mkdir -p "$MODELS_DIR/tts"

# ===== WHISPER MODEL =====
WHISPER_MODEL="ggml-base.bin"
WHISPER_PATH="$MODELS_DIR/whisper/$WHISPER_MODEL"
WHISPER_URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin"

if [ -f "$WHISPER_PATH" ]; then
    echo -e "${GREEN}✅ Whisper model already exists: $WHISPER_MODEL${NC}"
    WHISPER_SIZE=$(du -h "$WHISPER_PATH" | cut -f1)
    echo "   Size: $WHISPER_SIZE"
else
    echo -e "${YELLOW}📥 Downloading Whisper model: $WHISPER_MODEL (142 MB)...${NC}"
    echo "   From: $WHISPER_URL"
    echo ""

    if command -v wget &> /dev/null; then
        wget -O "$WHISPER_PATH" "$WHISPER_URL" --progress=bar:force 2>&1
    elif command -v curl &> /dev/null; then
        curl -L "$WHISPER_URL" -o "$WHISPER_PATH" --progress-bar
    else
        echo -e "${RED}❌ Error: wget or curl is required to download models${NC}"
        exit 1
    fi

    if [ -f "$WHISPER_PATH" ]; then
        echo -e "${GREEN}✅ Whisper model downloaded successfully!${NC}"
    else
        echo -e "${RED}❌ Failed to download Whisper model${NC}"
        exit 1
    fi
fi

echo ""
echo -e "${GREEN}🎉 All models ready!${NC}"
echo ""
echo "Model locations:"
echo "  - Whisper: $WHISPER_PATH"
echo ""
echo "You can now start the application:"
echo "  python3 src/main.py --config config/default.yaml"
echo ""
