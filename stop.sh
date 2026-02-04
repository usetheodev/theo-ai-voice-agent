#!/bin/bash
#===============================================
# Script para Parar o PABX Docker
#===============================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}🛑 Parando PABX Docker...${NC}"

# Para o Agente
echo -e "${YELLOW}   Parando Agente Python...${NC}"
cd agent && docker-compose down 2>/dev/null || true
cd "$SCRIPT_DIR"

# Para o Asterisk
echo -e "${YELLOW}   Parando Asterisk...${NC}"
docker-compose down 2>/dev/null || true

echo -e "${GREEN}✅ Sistema parado${NC}"
