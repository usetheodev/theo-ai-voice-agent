#!/bin/bash
set -e

echo "🚀 Starting AI Voice Agent stack..."
echo ""

docker-compose up -d

echo ""
echo "⏳ Waiting for services to be healthy..."
sleep 5

docker-compose ps

echo ""
echo "✅ Stack started!"
echo ""
echo "To view logs: ./scripts/logs.sh"
echo "To stop: ./scripts/stop.sh"
echo ""
