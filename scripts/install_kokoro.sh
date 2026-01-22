#!/bin/bash
set -e

echo "================================================"
echo "Installing Kokoro TTS"
echo "================================================"

echo "→ Installing kokoro-onnx from GitHub..."
pip install --no-cache-dir git+https://github.com/thewh1teagle/kokoro-onnx.git

echo "→ Verifying installation..."
python3 -c "import kokoro_onnx; print('✓ kokoro-onnx installed successfully')" || echo "✗ kokoro-onnx installation failed"

echo "================================================"
echo "Kokoro TTS installation completed!"
echo "================================================"
