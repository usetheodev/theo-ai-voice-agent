#!/bin/bash

# Voice Pipeline WebRTC Demo - Startup Script
# This script starts both the backend and frontend servers

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}======================================${NC}"
echo -e "${BLUE}  Voice Pipeline WebRTC Demo${NC}"
echo -e "${BLUE}======================================${NC}"
echo ""

# Check if we're in the right directory
if [ ! -f "$SCRIPT_DIR/requirements.txt" ]; then
    echo -e "${RED}Error: requirements.txt not found. Are you in the webapp-webrtc directory?${NC}"
    exit 1
fi

# Function to cleanup background processes
cleanup() {
    echo -e "\n${YELLOW}Shutting down servers...${NC}"
    kill $BACKEND_PID 2>/dev/null || true
    kill $FRONTEND_PID 2>/dev/null || true
    exit 0
}

trap cleanup SIGINT SIGTERM

# Check Python version
echo -e "${YELLOW}Checking Python version...${NC}"
PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2 | cut -d'.' -f1,2)
if [ "$(echo "$PYTHON_VERSION < 3.10" | bc)" -eq 1 ]; then
    echo -e "${RED}Error: Python 3.10+ is required (found $PYTHON_VERSION)${NC}"
    exit 1
fi
echo -e "${GREEN}Python $PYTHON_VERSION OK${NC}"

# Check Node version
echo -e "${YELLOW}Checking Node.js version...${NC}"
if ! command -v node &> /dev/null; then
    echo -e "${RED}Error: Node.js is required but not installed${NC}"
    exit 1
fi
NODE_VERSION=$(node --version | cut -d'v' -f2 | cut -d'.' -f1)
if [ "$NODE_VERSION" -lt 18 ]; then
    echo -e "${RED}Error: Node.js 18+ is required${NC}"
    exit 1
fi
echo -e "${GREEN}Node.js $(node --version) OK${NC}"

# Create virtual environment if it doesn't exist
if [ ! -d "$SCRIPT_DIR/venv" ]; then
    echo -e "${YELLOW}Creating Python virtual environment...${NC}"
    python3 -m venv "$SCRIPT_DIR/venv"
fi

# Activate virtual environment
source "$SCRIPT_DIR/venv/bin/activate"

# Install Python dependencies
echo -e "${YELLOW}Installing Python dependencies...${NC}"
pip install -q --upgrade pip
pip install -q -r "$SCRIPT_DIR/requirements.txt"

# Install voice-pipeline from parent directory
if [ -f "$SCRIPT_DIR/../../pyproject.toml" ]; then
    echo -e "${YELLOW}Installing voice-pipeline...${NC}"
    pip install -q -e "$SCRIPT_DIR/../.."
fi

# Install frontend dependencies
echo -e "${YELLOW}Installing frontend dependencies...${NC}"
cd "$SCRIPT_DIR/frontend"
if [ ! -d "node_modules" ]; then
    npm install --silent
fi

# Start backend
echo -e "${YELLOW}Starting backend server...${NC}"
cd "$SCRIPT_DIR"
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

# Wait for backend to start
echo -e "${YELLOW}Waiting for backend to start...${NC}"
sleep 3

# Check if backend is running
if ! kill -0 $BACKEND_PID 2>/dev/null; then
    echo -e "${RED}Error: Backend failed to start${NC}"
    exit 1
fi

# Start frontend
echo -e "${YELLOW}Starting frontend server...${NC}"
cd "$SCRIPT_DIR/frontend"
npm run dev &
FRONTEND_PID=$!

# Wait for frontend to start
sleep 2

echo ""
echo -e "${GREEN}======================================${NC}"
echo -e "${GREEN}  Servers are running!${NC}"
echo -e "${GREEN}======================================${NC}"
echo ""
echo -e "  Frontend: ${BLUE}http://localhost:5173${NC}"
echo -e "  Backend:  ${BLUE}http://localhost:8000${NC}"
echo -e "  API Docs: ${BLUE}http://localhost:8000/docs${NC}"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop all servers${NC}"
echo ""

# Wait for processes
wait
