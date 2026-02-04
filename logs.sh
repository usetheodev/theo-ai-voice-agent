#!/bin/bash
#===============================================
# Script para Ver Logs do PABX Docker
#===============================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Cores
BLUE='\033[0;34m'
NC='\033[0m'

case "${1:-all}" in
    asterisk|ast)
        echo -e "${BLUE}📋 Logs do Asterisk:${NC}"
        docker logs -f asterisk-pabx
        ;;
    agent|agente)
        echo -e "${BLUE}📋 Logs do Agente:${NC}"
        docker logs -f sip-agent
        ;;
    all|*)
        echo -e "${BLUE}📋 Logs de todos os serviços:${NC}"
        echo "   (Ctrl+C para sair)"
        echo ""
        docker logs -f asterisk-pabx &
        docker logs -f sip-agent &
        wait
        ;;
esac
