#!/bin/bash
set -e

echo "========================================"
echo "  📞 Starting Asterisk"
echo "========================================"
echo ""
echo "Configuration:"
echo "  - SIP Port: 5060 (UDP/TCP)"
echo "  - RTP Range: 10000-10100"
echo "  - ARI HTTP: 8088"
echo "  - AI Agent: ${AI_AGENT_HOST}:${AI_AGENT_PORT}"
echo ""
echo "Asterisk version:"
asterisk -V
echo ""
echo "========================================"
echo "  Asterisk starting..."
echo "========================================"
echo ""

# Execute Asterisk
exec "$@"
