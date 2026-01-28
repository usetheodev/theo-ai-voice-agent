#!/bin/bash
# Cleanup script for webapp-webrtc demo
# Kills all related processes and frees ports

echo "=== Limpando processos do webapp-webrtc ==="

# Kill backend processes
echo "Matando processos backend..."
pkill -9 -f "backend.main" 2>/dev/null
pkill -9 -f "uvicorn.*backend" 2>/dev/null

# Kill frontend processes
echo "Matando processos frontend..."
pkill -9 -f "vite.*webapp-webrtc" 2>/dev/null
pkill -9 -f "node.*webapp-webrtc/frontend" 2>/dev/null

# Kill processes on specific ports
echo "Liberando porta 8000 (backend)..."
fuser -k 8000/tcp 2>/dev/null

echo "Liberando porta 5173 (frontend)..."
fuser -k 5173/tcp 2>/dev/null

# Wait a moment
sleep 1

# Verify ports are free
echo ""
echo "=== Verificando portas ==="
if lsof -i :8000 2>/dev/null | grep -q LISTEN; then
    echo "AVISO: Porta 8000 ainda em uso!"
    lsof -i :8000
else
    echo "Porta 8000: LIVRE"
fi

if lsof -i :5173 2>/dev/null | grep -q LISTEN; then
    echo "AVISO: Porta 5173 ainda em uso!"
    lsof -i :5173
else
    echo "Porta 5173: LIVRE"
fi

echo ""
echo "=== Cleanup concluído ==="
