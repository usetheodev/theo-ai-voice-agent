#!/bin/bash
# ============================================================================
# Generate Self-Signed SSL Certificates for Asterisk WebRTC
# ============================================================================
#
# Purpose: Create SSL certificates for HTTPS/WSS (WebSocket Secure)
#          Required for Browser-Phone WebRTC connection
#
# Usage:
#   cd /home/paulo/Projetos/pesquisas/ai-voice-agent/asterisk/certs
#   ./generate_ssl_certs.sh
#
# Output:
#   asterisk.key - Private key
#   asterisk.crt - Certificate
#   asterisk.pem - Combined (cert + key)
#   ca.crt - CA certificate (install in browser)
#
# ============================================================================

set -e

CERT_DIR="/home/paulo/Projetos/pesquisas/ai-voice-agent/asterisk/certs"
DAYS_VALID=365
COUNTRY="BR"
STATE="Sao Paulo"
CITY="Sao Paulo"
ORG="AI Voice Agent"
ORG_UNIT="Development"
COMMON_NAME="asterisk.local"

echo "========================================"
echo "  🔐 Generating SSL Certificates"
echo "========================================"
echo ""
echo "Certificate Details:"
echo "  - CN: $COMMON_NAME"
echo "  - Organization: $ORG"
echo "  - Validity: $DAYS_VALID days"
echo "  - Output: $CERT_DIR"
echo ""

cd "$CERT_DIR"

# ===== Step 1: Generate CA (Certificate Authority) =====
echo "Step 1: Generating Certificate Authority (CA)..."

if [ ! -f ca.key ]; then
    openssl genrsa -out ca.key 4096
    echo "  ✅ CA private key created: ca.key"
else
    echo "  ⚠️  CA private key already exists: ca.key"
fi

if [ ! -f ca.crt ]; then
    openssl req -new -x509 -days $DAYS_VALID -key ca.key -out ca.crt \
        -subj "/C=$COUNTRY/ST=$STATE/L=$CITY/O=$ORG/OU=$ORG_UNIT/CN=AI Voice Agent CA"
    echo "  ✅ CA certificate created: ca.crt"
else
    echo "  ⚠️  CA certificate already exists: ca.crt"
fi

echo ""

# ===== Step 2: Generate Server Private Key =====
echo "Step 2: Generating Asterisk server private key..."

if [ ! -f asterisk.key ]; then
    openssl genrsa -out asterisk.key 4096
    echo "  ✅ Server private key created: asterisk.key"
else
    echo "  ⚠️  Server private key already exists: asterisk.key"
fi

echo ""

# ===== Step 3: Generate Certificate Signing Request (CSR) =====
echo "Step 3: Generating Certificate Signing Request (CSR)..."

if [ ! -f asterisk.csr ]; then
    openssl req -new -key asterisk.key -out asterisk.csr \
        -subj "/C=$COUNTRY/ST=$STATE/L=$CITY/O=$ORG/OU=$ORG_UNIT/CN=$COMMON_NAME"
    echo "  ✅ CSR created: asterisk.csr"
else
    echo "  ⚠️  CSR already exists: asterisk.csr"
fi

echo ""

# ===== Step 4: Create SAN (Subject Alternative Names) config =====
echo "Step 4: Creating SAN configuration..."

cat > asterisk_san.cnf <<EOF
[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req
prompt = no

[req_distinguished_name]
C = $COUNTRY
ST = $STATE
L = $CITY
O = $ORG
OU = $ORG_UNIT
CN = $COMMON_NAME

[v3_req]
keyUsage = keyEncipherment, dataEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = asterisk.local
DNS.2 = localhost
DNS.3 = asterisk
IP.1 = 127.0.0.1
IP.2 = 172.20.0.10
EOF

echo "  ✅ SAN config created: asterisk_san.cnf"
echo ""

# ===== Step 5: Sign Certificate with CA =====
echo "Step 5: Signing certificate with CA..."

openssl x509 -req -in asterisk.csr \
    -CA ca.crt -CAkey ca.key -CAcreateserial \
    -out asterisk.crt \
    -days $DAYS_VALID \
    -extensions v3_req \
    -extfile asterisk_san.cnf

echo "  ✅ Server certificate created: asterisk.crt"
echo ""

# ===== Step 6: Create Combined PEM file =====
echo "Step 6: Creating combined PEM file (cert + key)..."

cat asterisk.crt asterisk.key > asterisk.pem
chmod 600 asterisk.pem

echo "  ✅ Combined PEM created: asterisk.pem"
echo ""

# ===== Step 7: Verify Certificate =====
echo "Step 7: Verifying certificate..."

openssl x509 -in asterisk.crt -text -noout | grep -A 2 "Subject Alternative Name" || true
openssl x509 -in asterisk.crt -text -noout | grep "Subject:" || true
openssl x509 -in asterisk.crt -text -noout | grep "Issuer:" || true

echo ""

# ===== Summary =====
echo "========================================"
echo "  ✅ SSL Certificates Generated!"
echo "========================================"
echo ""
echo "Files created:"
ls -lh ca.key ca.crt asterisk.key asterisk.crt asterisk.pem | awk '{print "  " $9 " (" $5 ")"}'
echo ""
echo "========================================"
echo "  📋 Next Steps"
echo "========================================"
echo ""
echo "1. Copy certificates to Docker volume:"
echo "   (This will be done automatically by Docker build)"
echo ""
echo "2. Install CA certificate in your browser:"
echo "   File: $CERT_DIR/ca.crt"
echo ""
echo "   Chrome/Edge:"
echo "   - Settings → Privacy and security → Security"
echo "   - Manage certificates → Authorities → Import"
echo "   - Select ca.crt → Trust for websites"
echo ""
echo "   Firefox:"
echo "   - Settings → Privacy & Security → Certificates"
echo "   - View Certificates → Authorities → Import"
echo "   - Select ca.crt → Trust this CA to identify websites"
echo ""
echo "   macOS:"
echo "   - Double-click ca.crt"
echo "   - Keychain Access → System → Find certificate"
echo "   - Right-click → Get Info → Trust → Always Trust"
echo ""
echo "3. Build and start Asterisk:"
echo "   docker-compose build asterisk"
echo "   docker-compose up -d asterisk"
echo ""
echo "4. Access Browser-Phone:"
echo "   https://localhost:8089/"
echo ""
echo "5. Register WebRTC user:"
echo "   Username: webuser"
echo "   Password: webpass"
echo "   WebSocket: wss://localhost:8089/ws"
echo ""
echo "========================================"

# Set proper permissions
chmod 600 *.key *.pem
chmod 644 *.crt

echo ""
echo "✅ Certificate permissions set correctly"
echo "✅ Done!"
