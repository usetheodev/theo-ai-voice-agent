#!/bin/bash

echo "📋 Showing logs from all services..."
echo "   Press Ctrl+C to exit"
echo ""

docker-compose logs -f
