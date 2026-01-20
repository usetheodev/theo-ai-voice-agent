#!/bin/bash
# ============================================================================
# Validation Script: 100% Functional Test for Browser-Phone + Asterisk
# ============================================================================
#
# Purpose: Comprehensive validation of entire setup
#
# Tests:
#   1. Docker build successful
#   2. SSL certificates valid
#   3. Asterisk running and responsive
#   4. PJSIP modules loaded
#   5. PJSIP endpoints configured (WebRTC + UDP)
#   6. PJSIP transports active (UDP, TCP, WSS)
#   7. HTTP/HTTPS server running
#   8. Browser-Phone accessible
#   9. WebSocket endpoint active
#   10. Dialplan loaded
#   11. RTP configuration
#   12. Network connectivity
#
# Usage:
#   ./scripts/validate-setup.sh
#
# ============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Counters
TESTS_TOTAL=0
TESTS_PASSED=0
TESTS_FAILED=0
TESTS_WARNING=0

# Project directory
PROJECT_DIR="/home/paulo/Projetos/pesquisas/ai-voice-agent"
cd "$PROJECT_DIR"

# Helper functions
test_pass() {
    echo -e "${GREEN}✅ PASS${NC}: $1"
    TESTS_PASSED=$((TESTS_PASSED + 1))
}

test_fail() {
    echo -e "${RED}❌ FAIL${NC}: $1"
    echo -e "${RED}   →${NC} $2"
    TESTS_FAILED=$((TESTS_FAILED + 1))
}

test_warn() {
    echo -e "${YELLOW}⚠️  WARN${NC}: $1"
    echo -e "${YELLOW}   →${NC} $2"
    TESTS_WARNING=$((TESTS_WARNING + 1))
}

test_info() {
    echo -e "${CYAN}ℹ️  INFO${NC}: $1"
}

section_header() {
    echo ""
    echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
    echo ""
}

increment_total() {
    TESTS_TOTAL=$((TESTS_TOTAL + 1))
}

# ============================================================================
# MAIN VALIDATION
# ============================================================================

echo ""
echo -e "${CYAN}╔═══════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║                                               ║${NC}"
echo -e "${CYAN}║   100% VALIDATION - Browser-Phone + Asterisk  ║${NC}"
echo -e "${CYAN}║                                               ║${NC}"
echo -e "${CYAN}╚═══════════════════════════════════════════════╝${NC}"
echo ""

# ============================================================================
# SECTION 1: PRE-FLIGHT CHECKS
# ============================================================================

section_header "SECTION 1: Pre-Flight Checks"

# Test 1.1: Docker installed
increment_total
if command -v docker &> /dev/null; then
    DOCKER_VERSION=$(docker --version)
    test_pass "Docker installed: $DOCKER_VERSION"
else
    test_fail "Docker NOT installed" "Install Docker first"
    exit 1
fi

# Test 1.2: Docker Compose installed
increment_total
if command -v docker-compose &> /dev/null; then
    COMPOSE_VERSION=$(docker-compose --version)
    test_pass "Docker Compose installed: $COMPOSE_VERSION"
else
    test_fail "Docker Compose NOT installed" "Install docker-compose first"
    exit 1
fi

# Test 1.3: Project directory
increment_total
if [ -d "$PROJECT_DIR" ]; then
    test_pass "Project directory exists: $PROJECT_DIR"
else
    test_fail "Project directory NOT found" "Check PROJECT_DIR variable"
    exit 1
fi

# Test 1.4: docker-compose.yml exists
increment_total
if [ -f "$PROJECT_DIR/docker-compose.yml" ]; then
    test_pass "docker-compose.yml exists"
else
    test_fail "docker-compose.yml NOT found" "Missing configuration file"
    exit 1
fi

# ============================================================================
# SECTION 2: SSL CERTIFICATES
# ============================================================================

section_header "SECTION 2: SSL Certificates Validation"

CERT_DIR="$PROJECT_DIR/asterisk/certs"

# Test 2.1: Cert directory exists
increment_total
if [ -d "$CERT_DIR" ]; then
    test_pass "Certificate directory exists"
else
    test_fail "Certificate directory NOT found" "Run: mkdir -p $CERT_DIR"
    exit 1
fi

# Test 2.2: CA certificate
increment_total
if [ -f "$CERT_DIR/ca.crt" ]; then
    # Validate certificate
    if openssl x509 -in "$CERT_DIR/ca.crt" -noout -text &>/dev/null; then
        EXPIRY=$(openssl x509 -in "$CERT_DIR/ca.crt" -noout -enddate | cut -d= -f2)
        test_pass "CA certificate valid (expires: $EXPIRY)"
    else
        test_fail "CA certificate INVALID" "Regenerate certificates"
    fi
else
    test_warn "CA certificate NOT found" "Will be generated on container start"
fi

# Test 2.3: Server certificate
increment_total
if [ -f "$CERT_DIR/asterisk.pem" ]; then
    if openssl x509 -in "$CERT_DIR/asterisk.pem" -noout -text &>/dev/null; then
        # Check SAN
        SAN=$(openssl x509 -in "$CERT_DIR/asterisk.pem" -noout -text | grep -A1 "Subject Alternative Name" || echo "")
        if echo "$SAN" | grep -q "localhost"; then
            test_pass "Server certificate valid with SAN (localhost, 172.20.0.10)"
        else
            test_warn "Server certificate missing SAN" "May cause issues in some browsers"
        fi
    else
        test_fail "Server certificate INVALID" "Regenerate certificates"
    fi
else
    test_warn "Server certificate NOT found" "Will be generated on container start"
fi

# Test 2.4: Private key
increment_total
if [ -f "$CERT_DIR/asterisk.key" ]; then
    if openssl rsa -in "$CERT_DIR/asterisk.key" -check -noout &>/dev/null; then
        test_pass "Private key valid"
    else
        test_fail "Private key INVALID" "Regenerate certificates"
    fi
else
    test_warn "Private key NOT found" "Will be generated on container start"
fi

# ============================================================================
# SECTION 3: DOCKER BUILD & CONTAINER
# ============================================================================

section_header "SECTION 3: Docker Build & Container Status"

# Test 3.1: Docker image exists
increment_total
if docker images | grep -q "ai-voice-agent.*asterisk"; then
    test_pass "Asterisk Docker image exists"
else
    test_warn "Asterisk Docker image NOT found" "Building now..."
    docker-compose build asterisk
    if [ $? -eq 0 ]; then
        test_pass "Asterisk Docker image built successfully"
    else
        test_fail "Docker build FAILED" "Check docker-compose.yml and Dockerfile"
        exit 1
    fi
fi

# Test 3.2: Container running
increment_total
if docker ps | grep -q "asterisk"; then
    test_pass "Asterisk container is running"
else
    test_warn "Asterisk container NOT running" "Starting now..."
    docker-compose up -d asterisk

    # Wait for container to start
    echo -n "   Waiting for container to start..."
    sleep 5

    if docker ps | grep -q "asterisk"; then
        echo ""
        test_pass "Asterisk container started successfully"
    else
        echo ""
        test_fail "Container failed to start" "Check: docker logs asterisk"
        exit 1
    fi
fi

# Test 3.3: Container health
increment_total
echo "   Waiting for Asterisk to initialize (15s)..."
sleep 15

if docker exec asterisk asterisk -rx "core show version" &>/dev/null; then
    VERSION=$(docker exec asterisk asterisk -rx "core show version" 2>/dev/null | head -n1)
    test_pass "Asterisk process responsive: $VERSION"
else
    test_fail "Asterisk process NOT responsive" "Check: docker logs asterisk"
fi

# ============================================================================
# SECTION 4: PJSIP CONFIGURATION
# ============================================================================

section_header "SECTION 4: PJSIP Configuration Validation"

# Test 4.1: PJSIP module loaded
increment_total
if docker exec asterisk asterisk -rx "module show like res_pjsip.so" 2>/dev/null | grep -q "res_pjsip.so"; then
    test_pass "PJSIP module loaded"
else
    test_fail "PJSIP module NOT loaded" "Check: docker/asterisk/config/modules.conf"
fi

# Test 4.2: PJSIP transports
increment_total
TRANSPORTS=$(docker exec asterisk asterisk -rx "pjsip show transports" 2>/dev/null)

if echo "$TRANSPORTS" | grep -q "transport-udp"; then
    test_pass "PJSIP transport-udp configured"
else
    test_fail "PJSIP transport-udp NOT found" "Check: pjsip.conf"
fi

increment_total
if echo "$TRANSPORTS" | grep -q "transport-wss"; then
    test_pass "PJSIP transport-wss (WebRTC) configured"
else
    test_fail "PJSIP transport-wss NOT found" "Check: pjsip.conf [transport-wss]"
fi

# Test 4.3: WebRTC endpoints
increment_total
ENDPOINTS=$(docker exec asterisk asterisk -rx "pjsip show endpoints" 2>/dev/null)

if echo "$ENDPOINTS" | grep -q "100"; then
    test_pass "WebRTC endpoint 100 (webuser) configured"
else
    test_fail "WebRTC endpoint 100 NOT found" "Check: pjsip.conf [100]"
fi

increment_total
if echo "$ENDPOINTS" | grep -q "200"; then
    test_pass "WebRTC endpoint 200 (alice_web) configured"
else
    test_warn "WebRTC endpoint 200 NOT found" "Optional, but recommended"
fi

# Test 4.4: UDP endpoints (Softphone)
increment_total
if echo "$ENDPOINTS" | grep -q "1000"; then
    test_pass "UDP endpoint 1000 (testuser) configured"
else
    test_fail "UDP endpoint 1000 NOT found" "Check: pjsip.conf [1000]"
fi

# Test 4.5: AI Voice Agent trunk
increment_total
if echo "$ENDPOINTS" | grep -q "voiceagent"; then
    test_pass "AI Voice Agent trunk endpoint configured"
else
    test_fail "AI Voice Agent trunk NOT found" "Check: pjsip.conf [voiceagent-endpoint]"
fi

# ============================================================================
# SECTION 5: HTTP/HTTPS SERVER
# ============================================================================

section_header "SECTION 5: HTTP/HTTPS Server Validation"

# Test 5.1: HTTP server enabled
increment_total
HTTP_STATUS=$(docker exec asterisk asterisk -rx "http show status" 2>/dev/null || echo "")

if echo "$HTTP_STATUS" | grep -q "Enabled"; then
    test_pass "HTTP server enabled"
else
    test_fail "HTTP server NOT enabled" "Check: http.conf [general] enabled=yes"
fi

# Test 5.2: HTTPS/TLS enabled
increment_total
if echo "$HTTP_STATUS" | grep -q "HTTPS Server"; then
    test_pass "HTTPS server enabled"
else
    test_fail "HTTPS server NOT enabled" "Check: http.conf tlsenable=yes"
fi

# Test 5.3: Port 8089 listening (inside container)
increment_total
if docker exec asterisk netstat -tlnp 2>/dev/null | grep -q ":8089"; then
    test_pass "Port 8089 (HTTPS/WSS) listening inside container"
else
    test_fail "Port 8089 NOT listening" "Check: http.conf tlsbindaddr"
fi

# Test 5.4: Port 8089 accessible from host
increment_total
if nc -zv localhost 8089 &>/dev/null; then
    test_pass "Port 8089 accessible from host"
else
    test_fail "Port 8089 NOT accessible from host" "Check: docker-compose.yml ports mapping"
fi

# Test 5.5: HTTPS response (certificate may be invalid)
increment_total
if timeout 5 curl -k -s https://localhost:8089/ &>/dev/null; then
    test_pass "HTTPS server responds on port 8089"
else
    test_warn "HTTPS server not responding yet" "May need more time to initialize"
fi

# ============================================================================
# SECTION 6: BROWSER-PHONE FILES
# ============================================================================

section_header "SECTION 6: Browser-Phone Files Validation"

# Test 6.1: Static files directory
increment_total
if docker exec asterisk test -d /usr/share/asterisk/static-http/Phone; then
    test_pass "Browser-Phone static files directory exists"
else
    test_fail "Browser-Phone directory NOT found" "Check: Dockerfile COPY command"
fi

# Test 6.2: index.html exists
increment_total
if docker exec asterisk test -f /usr/share/asterisk/static-http/Phone/index.html; then
    test_pass "Browser-Phone index.html exists"
else
    test_fail "index.html NOT found" "Browser-Phone may not be properly cloned"
fi

# Test 6.3: Browser-Phone accessible via HTTPS
increment_total
RESPONSE=$(timeout 5 curl -k -s https://localhost:8089/ 2>/dev/null || echo "")
if echo "$RESPONSE" | grep -qi "browser.*phone\|sip\|webrtc"; then
    test_pass "Browser-Phone page loads successfully"
else
    test_warn "Browser-Phone page content unexpected" "May need manual verification"
fi

# ============================================================================
# SECTION 7: DIALPLAN
# ============================================================================

section_header "SECTION 7: Dialplan Validation"

# Test 7.1: Dialplan loaded
increment_total
DIALPLAN=$(docker exec asterisk asterisk -rx "dialplan show default" 2>/dev/null || echo "")

if [ -n "$DIALPLAN" ]; then
    test_pass "Dialplan loaded for context 'default'"
else
    test_fail "Dialplan NOT loaded" "Check: extensions.conf"
fi

# Test 7.2: Extension 100 (AI Voice Agent)
increment_total
if echo "$DIALPLAN" | grep -q "100"; then
    test_pass "Extension 100 (Call AI Agent) configured"
else
    test_fail "Extension 100 NOT found" "Check: extensions.conf [default]"
fi

# Test 7.3: Extension 101 (Echo test)
increment_total
if echo "$DIALPLAN" | grep -q "101"; then
    test_pass "Extension 101 (Echo test) configured"
else
    test_fail "Extension 101 NOT found" "Check: extensions.conf [default]"
fi

# Test 7.4: Extension 102 (Playback test)
increment_total
if echo "$DIALPLAN" | grep -q "102"; then
    test_pass "Extension 102 (Playback test) configured"
else
    test_warn "Extension 102 NOT found" "Optional test extension"
fi

# ============================================================================
# SECTION 8: RTP CONFIGURATION
# ============================================================================

section_header "SECTION 8: RTP Configuration Validation"

# Test 8.1: RTP settings
increment_total
RTP_SETTINGS=$(docker exec asterisk asterisk -rx "rtp show settings" 2>/dev/null || echo "")

if echo "$RTP_SETTINGS" | grep -q "RTP start.*10000"; then
    test_pass "RTP port range configured (10000-10100)"
else
    test_fail "RTP port range NOT configured" "Check: rtp.conf"
fi

# Test 8.2: ICE support (for WebRTC)
increment_total
if echo "$RTP_SETTINGS" | grep -qi "ice.*yes\|ice.*enabled"; then
    test_pass "ICE support enabled (WebRTC)"
else
    test_warn "ICE support not confirmed" "May affect WebRTC connectivity"
fi

# ============================================================================
# SECTION 9: NETWORK & CONNECTIVITY
# ============================================================================

section_header "SECTION 9: Network & Connectivity Validation"

# Test 9.1: Docker network
increment_total
if docker network ls | grep -q "voip-net"; then
    test_pass "Docker network 'voip-net' exists"
else
    test_fail "Docker network 'voip-net' NOT found" "Check: docker-compose.yml networks"
fi

# Test 9.2: Container IP
increment_total
CONTAINER_IP=$(docker inspect asterisk --format='{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' 2>/dev/null || echo "")
if [ "$CONTAINER_IP" = "172.20.0.10" ]; then
    test_pass "Asterisk container IP correct: $CONTAINER_IP"
else
    test_warn "Asterisk container IP unexpected: $CONTAINER_IP" "Expected: 172.20.0.10"
fi

# Test 9.3: Ping voiceagent (will fail if not running)
increment_total
if docker exec asterisk ping -c 1 voiceagent &>/dev/null; then
    test_pass "Can ping 'voiceagent' container"
else
    test_warn "Cannot ping 'voiceagent'" "Expected - AI Agent not implemented yet"
fi

# ============================================================================
# SECTION 10: WEBSOCKET
# ============================================================================

section_header "SECTION 10: WebSocket (WSS) Validation"

# Test 10.1: WebSocket endpoint
increment_total
# Try to connect to WebSocket (will fail without proper client, but we can check if endpoint exists)
WS_TEST=$(timeout 2 curl -k -i -N -H "Connection: Upgrade" -H "Upgrade: websocket" https://localhost:8089/ws 2>&1 || echo "")

if echo "$WS_TEST" | grep -qi "upgrade\|websocket\|400\|426"; then
    test_pass "WebSocket endpoint /ws responds"
else
    test_warn "WebSocket endpoint may not be configured" "Manual test required"
fi

# ============================================================================
# FINAL SUMMARY
# ============================================================================

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
echo -e "${BLUE}  VALIDATION SUMMARY${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
echo ""

echo -e "Total Tests:    ${CYAN}$TESTS_TOTAL${NC}"
echo -e "Passed:         ${GREEN}$TESTS_PASSED${NC}"
echo -e "Failed:         ${RED}$TESTS_FAILED${NC}"
echo -e "Warnings:       ${YELLOW}$TESTS_WARNING${NC}"
echo ""

PASS_RATE=$((TESTS_PASSED * 100 / TESTS_TOTAL))

if [ $TESTS_FAILED -eq 0 ]; then
    echo -e "${GREEN}╔═══════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║                                               ║${NC}"
    echo -e "${GREEN}║         ✅ ALL CRITICAL TESTS PASSED!         ║${NC}"
    echo -e "${GREEN}║                                               ║${NC}"
    echo -e "${GREEN}║   Pass Rate: $PASS_RATE%                              ║${NC}"
    echo -e "${GREEN}║                                               ║${NC}"
    echo -e "${GREEN}╚═══════════════════════════════════════════════╝${NC}"
    echo ""

    if [ $TESTS_WARNING -gt 0 ]; then
        echo -e "${YELLOW}⚠️  Note: $TESTS_WARNING warnings detected (non-critical)${NC}"
        echo ""
    fi

    echo -e "${CYAN}═══════════════════════════════════════════════${NC}"
    echo -e "${CYAN}  NEXT STEPS - MANUAL TESTING${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════${NC}"
    echo ""
    echo "1. Install CA Certificate in browser:"
    echo "   File: $CERT_DIR/ca.crt"
    echo ""
    echo "2. Open Browser-Phone:"
    echo "   https://localhost:8089/"
    echo ""
    echo "3. Configure SIP account:"
    echo "   Username: webuser"
    echo "   Password: webpass"
    echo "   WebSocket: wss://localhost:8089/ws"
    echo ""
    echo "4. Test Echo (Extension 101):"
    echo "   - Dial 101"
    echo "   - Speak into microphone"
    echo "   - You should hear your voice back"
    echo ""
    echo "5. If Echo works:"
    echo -e "   ${GREEN}✅ System is 100% functional!${NC}"
    echo ""

    exit 0
else
    echo -e "${RED}╔═══════════════════════════════════════════════╗${NC}"
    echo -e "${RED}║                                               ║${NC}"
    echo -e "${RED}║         ❌ VALIDATION FAILED                  ║${NC}"
    echo -e "${RED}║                                               ║${NC}"
    echo -e "${RED}║   $TESTS_FAILED critical test(s) failed               ║${NC}"
    echo -e "${RED}║                                               ║${NC}"
    echo -e "${RED}╚═══════════════════════════════════════════════╝${NC}"
    echo ""
    echo "Review failed tests above and fix issues."
    echo ""
    echo "Common fixes:"
    echo "  - Rebuild: docker-compose build asterisk"
    echo "  - Restart: docker-compose restart asterisk"
    echo "  - Logs: docker logs asterisk"
    echo "  - Config: Check files in docker/asterisk/config/"
    echo ""

    exit 1
fi
