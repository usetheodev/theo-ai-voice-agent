#!/bin/bash
# Voice Agent Web App Launcher

echo "================================"
echo "  Voice Agent Demo"
echo "================================"
echo ""

# Check if in correct directory
if [ ! -f "backend/main.py" ]; then
    echo "Error: Run this script from the webapp directory"
    echo "  cd examples/webapp && ./run.sh"
    exit 1
fi

# Check dependencies
echo "Checking dependencies..."

python3 -c "import fastapi" 2>/dev/null || {
    echo "Installing FastAPI..."
    pip3 install fastapi uvicorn websockets
}

echo ""
echo "Starting server on http://localhost:8000"
echo ""
echo "Press Ctrl+C to stop"
echo "================================"
echo ""

# Start server
cd backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000
