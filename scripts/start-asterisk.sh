#!/bin/bash
# ============================================================================
# Start Asterisk - Complete Setup and Health Check
# ============================================================================
#
# Purpose: Start Asterisk with all configurations and run health checks
#
# Usage:
#   ./scripts/start-asterisk.sh [options]
#
# Options:
#   --rebuild    Force rebuild of Docker image
#   --clean      Clean all containers and volumes before start
#   --logs       Follow logs after start
#   --help       Show this help message
#
# ============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default options
REBUILD=false
CLEAN=false
FOLLOW_LOGS=false
PROJECT_DIR="/home/paulo/Projetos/pesquisas/ai-voice-agent"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --rebuild)
            REBUILD=true
            shift
            ;;
        --clean)
            CLEAN=true
            shift
            ;;
        --logs)
            FOLLOW_LOGS=true
            shift
            ;;
        --help)
            head -n 20 "$0" | tail -n +3 | sed 's/^# //' | sed 's/^#//'
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

cd "$PROJECT_DIR"

echo "========================================"
echo "  📞 Starting Asterisk"
echo "========================================"
echo ""

# ===== Step 0: Clean if requested =====
if [ "$CLEAN" = true ]; then
    echo -e "${YELLOW}Step 0: Cleaning containers and volumes...${NC}"
    docker-compose down -v 2>/dev/null || true
    docker system prune -f 2>/dev/null || true
    echo -e "${GREEN}  ✅ Cleanup complete${NC}"
    echo ""
fi

# ===== Step 1: Check if certificates exist =====
echo "Step 1: Checking SSL certificates..."
CERT_DIR="$PROJECT_DIR/asterisk/certs"

if [ ! -f "$CERT_DIR/ca.crt" ] || [ ! -f "$CERT_DIR/asterisk.pem" ]; then
    echo -e "${YELLOW}  ⚠️  Certificates not found${NC}"

    if [ -f "$CERT_DIR/generate_ssl_certs.sh" ]; then
        echo "  🔐 Generating SSL certificates..."
        cd "$CERT_DIR"
        ./generate_ssl_certs.sh > /dev/null 2>&1
        cd "$PROJECT_DIR"
        echo -e "${GREEN}  ✅ Certificates generated${NC}"
    else
        echo -e "${RED}  ❌ Certificate generation script not found!${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}  ✅ Certificates exist${NC}"
    ls -lh "$CERT_DIR"/{ca.crt,asterisk.pem} | awk '{print "     " $9 " (" $5 ")"}'
fi
echo ""

# ===== Step 2: Build or pull image =====
if [ "$REBUILD" = true ]; then
    echo -e "${YELLOW}Step 2: Rebuilding Asterisk Docker image...${NC}"
    echo "  (This may take several minutes)"
    docker-compose build --no-cache asterisk
    echo -e "${GREEN}  ✅ Rebuild complete${NC}"
else
    echo "Step 2: Checking Docker image..."

    if docker images | grep -q "ai-voice-agent.*asterisk"; then
        echo -e "${GREEN}  ✅ Docker image exists${NC}"
    else
        echo -e "${YELLOW}  ⚠️  Image not found, building...${NC}"
        docker-compose build asterisk
        echo -e "${GREEN}  ✅ Build complete${NC}"
    fi
fi
echo ""

# ===== Step 3: Stop existing container =====
echo "Step 3: Checking existing containers..."
if docker ps -a | grep -q "asterisk"; then
    echo -e "${YELLOW}  ⚠️  Stopping existing Asterisk container...${NC}"
    docker-compose stop asterisk 2>/dev/null || true
    docker-compose rm -f asterisk 2>/dev/null || true
    echo -e "${GREEN}  ✅ Old container removed${NC}"
else
    echo -e "${GREEN}  ✅ No existing container${NC}"
fi
echo ""

# ===== Step 4: Start Asterisk =====
echo "Step 4: Starting Asterisk container..."
docker-compose up -d asterisk

if [ $? -eq 0 ]; then
    echo -e "${GREEN}  ✅ Container started${NC}"
else
    echo -e "${RED}  ❌ Failed to start container${NC}"
    exit 1
fi
echo ""

# ===== Step 5: Wait for initialization =====
echo "Step 5: Waiting for Asterisk to initialize..."
echo -n "  "

MAX_WAIT=60
WAIT_COUNT=0

while [ $WAIT_COUNT -lt $MAX_WAIT ]; do
    if docker exec asterisk asterisk -rx "core show version" &>/dev/null; then
        echo ""
        echo -e "${GREEN}  ✅ Asterisk is running${NC}"
        break
    fi

    echo -n "."
    sleep 2
    WAIT_COUNT=$((WAIT_COUNT + 2))
done

if [ $WAIT_COUNT -ge $MAX_WAIT ]; then
    echo ""
    echo -e "${RED}  ❌ Timeout waiting for Asterisk${NC}"
    echo ""
    echo "Logs:"
    docker logs asterisk --tail 50
    exit 1
fi
echo ""

# ===== Step 6: Health checks =====
echo "Step 6: Running health checks..."

# Check 6.1: Asterisk version
VERSION=$(docker exec asterisk asterisk -rx "core show version" 2>/dev/null | head -n1)
if [ -n "$VERSION" ]; then
    echo -e "${GREEN}  ✅ Asterisk version:${NC} $VERSION"
else
    echo -e "${RED}  ❌ Cannot get Asterisk version${NC}"
fi

# Check 6.2: PJSIP module
if docker exec asterisk asterisk -rx "module show like res_pjsip.so" 2>/dev/null | grep -q "res_pjsip.so"; then
    echo -e "${GREEN}  ✅ PJSIP module loaded${NC}"
else
    echo -e "${RED}  ❌ PJSIP module NOT loaded${NC}"
fi

# Check 6.3: HTTP/HTTPS
if docker exec asterisk asterisk -rx "http show status" 2>/dev/null | grep -q "Enabled"; then
    echo -e "${GREEN}  ✅ HTTP server enabled${NC}"
else
    echo -e "${YELLOW}  ⚠️  HTTP server status unknown${NC}"
fi

# Check 6.4: PJSIP endpoints
sleep 2
ENDPOINTS=$(docker exec asterisk asterisk -rx "pjsip show endpoints" 2>/dev/null | grep -E "100|1000|voiceagent" | wc -l)
if [ "$ENDPOINTS" -ge 3 ]; then
    echo -e "${GREEN}  ✅ PJSIP endpoints configured ($ENDPOINTS found)${NC}"
else
    echo -e "${YELLOW}  ⚠️  PJSIP endpoints not fully ready yet${NC}"
fi

# Check 6.5: PJSIP transports
TRANSPORTS=$(docker exec asterisk asterisk -rx "pjsip show transports" 2>/dev/null | grep -c "transport-" || echo "0")
if [ "$TRANSPORTS" -ge 2 ]; then
    echo -e "${GREEN}  ✅ PJSIP transports active ($TRANSPORTS)${NC}"
else
    echo -e "${YELLOW}  ⚠️  PJSIP transports not fully ready${NC}"
fi

# Check 6.6: WebSocket transport (WSS)
if docker exec asterisk asterisk -rx "pjsip show transports" 2>/dev/null | grep -q "wss"; then
    echo -e "${GREEN}  ✅ WebSocket Secure (WSS) transport active${NC}"
else
    echo -e "${YELLOW}  ⚠️  WSS transport not found${NC}"
fi

# Check 6.7: Dialplan
EXTENSIONS=$(docker exec asterisk asterisk -rx "dialplan show default" 2>/dev/null | grep -c "Extension:" || echo "0")
if [ "$EXTENSIONS" -ge 5 ]; then
    echo -e "${GREEN}  ✅ Dialplan loaded ($EXTENSIONS extensions)${NC}"
else
    echo -e "${YELLOW}  ⚠️  Dialplan not fully loaded${NC}"
fi

# Check 6.8: Port bindings
if docker port asterisk 5060 &>/dev/null; then
    echo -e "${GREEN}  ✅ SIP port 5060 exposed${NC}"
else
    echo -e "${YELLOW}  ⚠️  SIP port not exposed${NC}"
fi

if docker port asterisk 8089 &>/dev/null; then
    echo -e "${GREEN}  ✅ HTTPS/WSS port 8089 exposed${NC}"
else
    echo -e "${YELLOW}  ⚠️  HTTPS/WSS port not exposed${NC}"
fi

echo ""

# ===== Step 7: Display access information =====
HOST_IP=$(hostname -I | awk '{print $1}' || echo "localhost")

echo "========================================"
echo -e "${BLUE}  📋 Access Information${NC}"
echo "========================================"
echo ""
echo -e "${YELLOW}Browser-Phone (WebRTC):${NC}"
echo "  URL (Local):   https://localhost:8089/"
echo "  URL (Network): https://$HOST_IP:8089/"
echo ""
echo -e "${YELLOW}WebRTC Credentials:${NC}"
echo "  Extension:  100"
echo "  Username:   webuser"
echo "  Password:   webpass"
echo "  WebSocket:  wss://localhost:8089/ws"
echo ""
echo -e "${YELLOW}Softphone (UDP):${NC}"
echo "  Server:     $HOST_IP:5060"
echo "  Extension:  1000"
echo "  Username:   testuser"
echo "  Password:   test123"
echo ""
echo -e "${YELLOW}Test Extensions:${NC}"
echo "  100 → Call AI Voice Agent (main test)"
echo "  101 → Echo test (verify audio)"
echo "  102 → Playback test (Asterisk sounds)"
echo "  103 → Milliwatt test (1000Hz tone)"
echo ""

# ===== Step 8: SSL Certificate reminder =====
echo "========================================"
echo -e "${BLUE}  🔐 SSL Certificate Setup${NC}"
echo "========================================"
echo ""
echo -e "${YELLOW}⚠️  IMPORTANT: Install CA certificate in your browser!${NC}"
echo ""
echo "Certificate location:"
echo "  $CERT_DIR/ca.crt"
echo ""
echo "Quick install:"
echo "  Chrome/Edge: chrome://settings/certificates → Authorities → Import"
echo "  Firefox:     about:preferences#privacy → Certificates → Import"
echo "  macOS:       Double-click ca.crt → Keychain Access → Always Trust"
echo ""
echo "Or temporarily accept the certificate warning in browser."
echo ""

# ===== Step 9: Useful commands =====
echo "========================================"
echo -e "${BLUE}  🛠️  Useful Commands${NC}"
echo "========================================"
echo ""
echo "View logs:"
echo "  docker logs -f asterisk"
echo ""
echo "Asterisk CLI:"
echo "  docker exec -it asterisk asterisk -rvvv"
echo ""
echo "Check endpoints:"
echo "  docker exec asterisk asterisk -rx 'pjsip show endpoints'"
echo ""
echo "Check transports:"
echo "  docker exec asterisk asterisk -rx 'pjsip show transports'"
echo ""
echo "Check active calls:"
echo "  docker exec asterisk asterisk -rx 'core show channels'"
echo ""
echo "Restart Asterisk:"
echo "  docker-compose restart asterisk"
echo ""
echo "Stop Asterisk:"
echo "  docker-compose stop asterisk"
echo ""
echo "Run tests:"
echo "  ./scripts/test_asterisk_setup.sh"
echo ""

# ===== Step 10: Follow logs if requested =====
if [ "$FOLLOW_LOGS" = true ]; then
    echo "========================================"
    echo -e "${BLUE}  📜 Following logs (Ctrl+C to exit)${NC}"
    echo "========================================"
    echo ""
    docker logs -f asterisk
fi

# ===== Final summary =====
echo "========================================"
echo -e "${GREEN}  ✅ Asterisk Started Successfully!${NC}"
echo "========================================"
echo ""
echo -e "${YELLOW}Next Steps:${NC}"
echo "  1. Install CA certificate (see above)"
echo "  2. Open https://localhost:8089/ (Browser-Phone)"
echo "  3. Register WebRTC user (webuser/webpass)"
echo "  4. Test echo: Dial 101"
echo "  5. Call AI: Dial 100 (will fail until AI is implemented)"
echo ""
echo -e "${BLUE}Documentation:${NC}"
echo "  - BROWSER_PHONE_SETUP.md (WebRTC guide)"
echo "  - SOFTPHONE_SETUP.md (Softphone guide)"
echo "  - TESTING_STRATEGY.md (Testing guide)"
echo ""
echo -e "${GREEN}Happy Testing! 🎉${NC}"
echo ""
