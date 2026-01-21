#!/bin/bash
set -e

echo "🛑 Stopping AI Voice Agent stack..."
docker-compose down
echo "✅ Stack stopped"
