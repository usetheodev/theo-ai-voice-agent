#!/bin/bash
#===============================================
# Script para Ver Status do PABX Docker
#===============================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}          PABX Docker - Status                  ${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""

# Status dos containers
echo -e "${BLUE}🐳 Containers:${NC}"
echo ""

# Asterisk
if docker ps | grep -q asterisk-pabx; then
    echo -e "   Asterisk:  ${GREEN}✅ Rodando${NC}"
else
    echo -e "   Asterisk:  ${RED}❌ Parado${NC}"
fi

# Agente
if docker ps | grep -q sip-agent; then
    echo -e "   Agente:    ${GREEN}✅ Rodando${NC}"
else
    echo -e "   Agente:    ${RED}❌ Parado${NC}"
fi

echo ""

# Endpoints registrados
if docker ps | grep -q asterisk-pabx; then
    echo -e "${BLUE}📞 Endpoints PJSIP:${NC}"
    echo ""
    docker exec asterisk-pabx asterisk -rx "pjsip show endpoints" 2>/dev/null | grep -E "Endpoint:|Contact:" | head -20 || echo "   Nenhum endpoint"
    echo ""

    echo -e "${BLUE}📱 Ramais Online:${NC}"
    echo ""
    docker exec asterisk-pabx asterisk -rx "pjsip show contacts" 2>/dev/null | grep -E "Contact|aor" | head -20 || echo "   Nenhum ramal online"
fi

echo ""
echo -e "${BLUE}================================================${NC}"
