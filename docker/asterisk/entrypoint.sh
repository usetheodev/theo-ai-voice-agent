#!/bin/bash
set -e

echo "========================================" echo "  📞 Starting Asterisk with WebRTC"
echo "========================================"
echo ""

CERT_DIR="/etc/asterisk/keys"
mkdir -p "$CERT_DIR"

if [ ! -f "$CERT_DIR/asterisk.pem" ]; then
    echo "🔐 Generating SSL certificates..."
    cd "$CERT_DIR"
    
    openssl genrsa -out ca.key 4096 2>/dev/null
    openssl req -new -x509 -days 365 -key ca.key -out ca.crt -subj "/C=BR/ST=SP/L=SP/O=AIAgent/CN=CA" 2>/dev/null
    openssl genrsa -out asterisk.key 4096 2>/dev/null
    openssl req -new -key asterisk.key -out asterisk.csr -subj "/C=BR/ST=SP/L=SP/O=AIAgent/CN=asterisk.local" 2>/dev/null
    
    cat > san.cnf <<EOL
[req]
req_extensions = v3_req
[v3_req]
subjectAltName = @alt_names
[alt_names]
DNS.1 = asterisk.local
DNS.2 = localhost
IP.1 = 127.0.0.1
IP.2 = 172.20.0.10
EOL
    
    openssl x509 -req -in asterisk.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out asterisk.crt -days 365 -extensions v3_req -extfile san.cnf 2>/dev/null
    cat asterisk.crt asterisk.key > asterisk.pem
    chmod 600 *.key *.pem
    echo "  ✅ Certificates ready"
fi

echo ""
echo "WebRTC: https://localhost:8089/"
echo "WebSocket: wss://localhost:8089/ws"
echo ""
echo "Users: webuser/webpass (ext 100), testuser/test123 (ext 1000)"
echo ""

exec /usr/sbin/asterisk -f -vvv
