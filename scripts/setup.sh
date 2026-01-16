#!/bin/bash
set -e

echo "========================================"
echo "  🐳 AI Voice Agent - Setup"
echo "========================================"
echo ""

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker not found. Please install Docker first."
    echo "   Visit: https://docs.docker.com/get-docker/"
    exit 1
fi

echo "✅ Docker found: $(docker --version)"

# Check if Docker Compose is installed
if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose not found. Please install Docker Compose first."
    echo "   Visit: https://docs.docker.com/compose/install/"
    exit 1
fi

echo "✅ Docker Compose found: $(docker-compose --version)"
echo ""

# Create .env if it doesn't exist
if [ ! -f .env ]; then
    echo "📝 Creating .env file from .env.example..."
    cp .env.example .env
    echo "✅ .env file created."
    echo ""
    echo "⚠️  IMPORTANT: Please review and edit .env file with your settings:"
    echo "   - FREESWITCH_PASSWORD (change default password)"
    echo "   - WHISPER_MODEL (tiny, base, small, medium)"
    echo "   - LLM_MODEL (phi-3-mini recommended for CPU)"
    echo ""
    read -p "Press Enter to continue after reviewing .env..."
else
    echo "✅ .env file already exists"
fi

echo ""
echo "🔨 Building Docker images..."
echo "   This may take 5-10 minutes on first run..."
echo ""

docker-compose build

echo ""
echo "✅ Docker images built successfully!"
echo ""
echo "📥 Downloading AI models..."
echo "   This will happen automatically on first container start"
echo "   Models will be downloaded to Docker volume 'ai-models'"
echo ""
echo "========================================"
echo "  ✅ Setup Complete!"
echo "========================================"
echo ""
echo "Next steps:"
echo "  1. Review .env file if needed"
echo "  2. Run './scripts/start.sh' to start the stack"
echo "  3. Configure your SIP softphone (see README.md)"
echo "  4. Call extension 9999 to talk to AI Agent"
echo ""
