#!/bin/bash
set -e

echo "🔄 Resetting AI Voice Agent stack..."
echo ""
echo "⚠️  WARNING: This will:"
echo "   - Stop all containers"
echo "   - Remove all volumes (including downloaded models)"
echo "   - Remove all images"
echo ""
read -p "Are you sure? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo "❌ Reset cancelled"
    exit 0
fi

echo ""
echo "Stopping containers..."
docker-compose down

echo "Removing volumes..."
docker-compose down -v

echo "Removing images..."
docker-compose down --rmi all

echo ""
echo "✅ Reset complete!"
echo ""
echo "Run './scripts/setup.sh' to start fresh"
