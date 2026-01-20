#!/bin/bash
# ============================================================================
# Quick Start: Browser-Phone with Asterisk
# ============================================================================

set -e

echo "========================================"
echo "  🌐 Starting Browser-Phone Setup"
echo "========================================"
echo ""

PROJECT_DIR="/home/paulo/Projetos/pesquisas/ai-voice-agent"
CERT_DIR="$PROJECT_DIR/asterisk/certs"

cd "$PROJECT_DIR"

# ===== Step 1: Check if certificates exist =====
echo "Step 1: Checking SSL certificates..."
if [ ! -f "$CERT_DIR/ca.crt" ]; then
    echo "  ⚠️  Certificates not found, generating..."
    cd "$CERT_DIR"
    ./generate_ssl_certs.sh
    echo ""
else
    echo "  ✅ Certificates already exist"
    echo ""
fi

# ===== Step 2: Build Asterisk with Browser-Phone =====
echo "Step 2: Building Asterisk container..."
echo "  (This may take a few minutes on first build)"
echo ""

docker-compose build asterisk

echo "  ✅ Build complete"
echo ""

# ===== Step 3: Start Asterisk =====
echo "Step 3: Starting Asterisk..."
docker-compose up -d asterisk

echo "  ⏳ Waiting for Asterisk to initialize (30s)..."
sleep 5

# Show startup logs
docker logs asterisk 2>&1 | tail -20

echo ""
echo "  ✅ Asterisk is running"
echo ""

# ===== Step 4: Display Access Information =====
HOST_IP=$(hostname -I | awk '{print $1}' || echo "localhost")

echo "========================================"
echo "  📋 Access Information"
echo "========================================"
echo ""
echo "Browser-Phone URL:"
echo "  - Local: https://localhost:8089/"
echo "  - Network: https://$HOST_IP:8089/"
echo ""
echo "WebRTC Credentials (Extension 100):"
echo "  - Username: webuser"
echo "  - Password: webpass"
echo "  - WebSocket: wss://localhost:8089/ws"
echo ""
echo "Softphone Credentials (Extension 1000):"
echo "  - Server: $HOST_IP:5060"
echo "  - Username: testuser"
echo "  - Password: test123"
echo ""
echo "Test Extensions:"
echo "  - 101: Echo test (verify audio)"
echo "  - 102: Playback test (Asterisk sounds)"
echo "  - 100: Call AI Voice Agent (main test)"
echo ""

# ===== Step 5: Check if CA cert is installed =====
echo "========================================"
echo "  🔐 SSL Certificate Setup"
echo "========================================"
echo ""
echo "⚠️  IMPORTANT: Install CA certificate in your browser!"
echo ""
echo "Certificate location:"
echo "  $CERT_DIR/ca.crt"
echo ""
echo "Installation instructions:"
echo ""
echo "Chrome/Edge:"
echo "  1. Settings → Security → Manage certificates"
echo "  2. Authorities → Import → Select ca.crt"
echo "  3. ✅ Trust for identifying websites"
echo "  4. Restart browser"
echo ""
echo "Firefox:"
echo "  1. Settings → Privacy → View Certificates"
echo "  2. Authorities → Import → Select ca.crt"
echo "  3. ✅ Trust this CA to identify websites"
echo "  4. Restart browser"
echo ""
echo "macOS:"
echo "  1. Double-click ca.crt"
echo "  2. Keychain Access → System → Find cert"
echo "  3. Get Info → Trust → Always Trust"
echo ""

# ===== Step 6: Quick Health Check =====
echo "========================================"
echo "  🏥 Health Check"
echo "========================================"
echo ""

echo "Checking Asterisk status..."
if docker ps | grep -q asterisk; then
    echo "  ✅ Asterisk container running"
else
    echo "  ❌ Asterisk container NOT running"
    exit 1
fi

sleep 3

echo "Checking PJSIP endpoints..."
ENDPOINTS=$(docker exec asterisk asterisk -rx "pjsip show endpoints" 2>/dev/null | grep -c "100\|1000" || echo "0")
if [ "$ENDPOINTS" -ge 2 ]; then
    echo "  ✅ PJSIP endpoints configured"
else
    echo "  ⚠️  PJSIP endpoints not ready yet (wait ~30s)"
fi

echo ""
echo "Checking WebSocket transport..."
WSS=$(docker exec asterisk asterisk -rx "pjsip show transports" 2>/dev/null | grep -c "transport-wss" || echo "0")
if [ "$WSS" -ge 1 ]; then
    echo "  ✅ WebSocket transport active"
else
    echo "  ⚠️  WebSocket transport not ready yet"
fi

echo ""

# ===== Step 7: Next Steps =====
echo "========================================"
echo "  🚀 Next Steps"
echo "========================================"
echo ""
echo "1. Install CA certificate (see instructions above)"
echo ""
echo "2. Open Browser-Phone:"
echo "   https://localhost:8089/"
echo ""
echo "3. Configure SIP account:"
echo "   - Display Name: Web User"
echo "   - Username: webuser"
echo "   - Password: webpass"
echo "   - WebSocket: wss://localhost:8089/ws"
echo ""
echo "4. Test with Echo (dial 101):"
echo "   - Call should connect"
echo "   - Speak → You should hear your voice back"
echo ""
echo "5. Call AI Voice Agent (dial 100):"
echo "   - Will fail until AI is implemented"
echo "   - This is expected!"
echo ""
echo "📖 Full documentation:"
echo "  - BROWSER_PHONE_SETUP.md"
echo "  - SOFTPHONE_SETUP.md"
echo ""
echo "🐛 Troubleshooting:"
echo "  docker logs -f asterisk"
echo ""
echo "✅ Setup complete!"
echo ""
