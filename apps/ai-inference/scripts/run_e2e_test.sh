#!/bin/bash
#
# Script para executar teste E2E do AI Inference WebRTC
#
# Uso:
#   ./scripts/run_e2e_test.sh           # Inicia servidor + abre browser
#   ./scripts/run_e2e_test.sh --no-browser  # Só inicia servidor
#   ./scripts/run_e2e_test.sh --test-only   # Só roda teste Python
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
HOST="${HOST:-localhost}"
PORT="${PORT:-8080}"

cd "$PROJECT_DIR"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║       AI Inference - Teste E2E WebRTC                    ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# Parse arguments
OPEN_BROWSER=true
TEST_ONLY=false

for arg in "$@"; do
    case $arg in
        --no-browser)
            OPEN_BROWSER=false
            ;;
        --test-only)
            TEST_ONLY=true
            ;;
    esac
done

# Function to open browser
open_browser() {
    local url="$1"
    echo -e "${YELLOW}Abrindo browser...${NC}"

    if command -v xdg-open &> /dev/null; then
        xdg-open "$url" 2>/dev/null &
    elif command -v open &> /dev/null; then
        open "$url" &
    elif command -v start &> /dev/null; then
        start "$url" &
    else
        echo -e "${YELLOW}Abra manualmente: $url${NC}"
    fi
}

# Function to wait for server
wait_for_server() {
    echo -e "${YELLOW}Aguardando servidor iniciar...${NC}"
    for i in {1..30}; do
        if curl -s "http://$HOST:$PORT/health" > /dev/null 2>&1; then
            echo -e "${GREEN}Servidor pronto!${NC}"
            return 0
        fi
        sleep 1
    done
    echo "Timeout aguardando servidor"
    return 1
}

# Main
if [ "$TEST_ONLY" = true ]; then
    echo -e "${BLUE}Executando apenas teste Python...${NC}"
    echo ""
    python3 "$SCRIPT_DIR/test_e2e_webrtc.py" --host "$HOST" --port "$PORT"
    exit $?
fi

# Check if server is already running
if curl -s "http://$HOST:$PORT/health" > /dev/null 2>&1; then
    echo -e "${GREEN}Servidor já está rodando em http://$HOST:$PORT${NC}"
else
    echo -e "${YELLOW}Iniciando servidor...${NC}"
    echo ""

    # Start server in background
    python3 -m uvicorn src.main:app --host 0.0.0.0 --port "$PORT" --reload &
    SERVER_PID=$!

    # Trap to kill server on exit
    trap "echo ''; echo 'Parando servidor...'; kill $SERVER_PID 2>/dev/null; exit" INT TERM EXIT

    wait_for_server || exit 1
fi

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}Servidor rodando em: http://$HOST:$PORT${NC}"
echo -e "${GREEN}Swagger UI: http://$HOST:$PORT/docs${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
echo ""

# Open browser test
if [ "$OPEN_BROWSER" = true ]; then
    HTML_FILE="file://$SCRIPT_DIR/test_webrtc_browser.html"
    open_browser "$HTML_FILE"
    echo -e "${BLUE}Teste no browser: $HTML_FILE${NC}"
fi

echo ""
echo -e "${YELLOW}Comandos disponíveis:${NC}"
echo "  Teste Python:  python3 scripts/test_e2e_webrtc.py"
echo "  Teste cURL:"
echo "    curl http://$HOST:$PORT/health"
echo "    curl -X POST http://$HOST:$PORT/v1/realtime/sessions -H 'Content-Type: application/json' -d '{\"instructions\": \"Olá\"}'"
echo ""
echo -e "${YELLOW}Pressione Ctrl+C para parar o servidor${NC}"
echo ""

# Keep running
wait
